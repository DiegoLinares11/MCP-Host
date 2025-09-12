# src/host.py
import os, json, typer, uuid, re
from typing import Any, Dict, List
from dotenv import load_dotenv
from openai import OpenAI

from .mcp_client import MCPClient
from .memory import Memory
from .logging_middleware import JSONLLogger

app = typer.Typer(help="Chat Host (OpenAI) + Tool Calling hacia MCP (SQLScout/FS/Git)")

def _pretty(x): 
    return json.dumps(x, ensure_ascii=False, indent=2)

def _openai_client():
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Falta OPENAI_API_KEY en .env")
    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return client, model

def render_tool_result(result: Dict[str, Any]) -> str:
    sc = result.get("structuredContent", {})
    if sc and "result" in sc:
        data = sc["result"]
        if isinstance(data, list) and data and isinstance(data[0], dict):
            headers = list(data[0].keys())
            head = "| " + " | ".join(headers) + " |"
            sep  = "| " + " | ".join("---" for _ in headers) + " |"
            rows = ["| " + " | ".join(str(r.get(h, "")) for h in headers) + " |" for r in data]
            return "\n".join([head, sep] + rows)
        return _pretty(data)
    parts = result.get("content", [])
    if isinstance(parts, list):
        texts = [p.get("text","") for p in parts if isinstance(p, dict) and p.get("type")=="text"]
        if texts:
            return "\n".join(texts)
    return _pretty(result)

# === Catálogo de tools para OpenAI (function calling) ===
OPENAI_TOOLS = [
    {"type":"function","function":{
        "name":"sql_load","description":"Carga un esquema SQL (texto completo .sql).",
        "parameters":{"type":"object","properties":{"schema":{"type":"string"}},"required":["schema"]}
    }},
    {"type":"function","function":{
        "name":"sql_explain","description":"EXPLAIN QUERY PLAN de una consulta.",
        "parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}
    }},
    {"type":"function","function":{
        "name":"sql_diagnose","description":"Diagnóstico estático (select *, like '%', funciones en WHERE...).",
        "parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}
    }},
    {"type":"function","function":{
        "name":"sql_optimize","description":"Sugerencias de índice/reescrituras basadas en diagnóstico.",
        "parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}
    }},
    {"type":"function","function":{
        "name":"sql_apply","description":"Aplica DDL (CREATE/DROP INDEX, ALTER...).",
        "parameters":{"type":"object","properties":{"ddl":{"type":"string"}},"required":["ddl"]}
    }},
    {"type":"function","function":{
        "name":"sql_optimize_apply","description":"Compara plan antes/después aplicando DDL temporalmente.",
        "parameters":{"type":"object","properties":{"query":{"type":"string"},"ddl":{"type":"string"}},"required":["query","ddl"]}
    }},
    # Genérica: permite llamar cualquier tool de cualquier server declarado en mcp_config.json
    {"type":"function","function":{
        "name":"mcp_run","description":"Llama una tool de un servidor MCP (FS/Git/SQLScout/otros).",
        "parameters":{
            "type":"object",
            "properties":{
                "server":{"type":"string","description":"Nombre de servidor (mcp_config.json)"},
                "name":{"type":"string","description":"Nombre de la tool (según tools/list)"},
                "arguments":{"type":"object","description":"Argumentos JSON","additionalProperties":True}
            },
            "required":["server","name","arguments"]
        }
    }},
]

# Mapeo OpenAI -> tools del server SQLScout
OPENAI_TO_MCP = {
    "sql_load": "sql.load",
    "sql_explain": "sql.explain",
    "sql_diagnose": "sql.diagnose",
    "sql_optimize": "sql.optimize",
    "sql_apply": "sql.apply",
    "sql_optimize_apply": "sql.optimize_apply",
}

def _exec_mcp_sql(clients: Dict[str, MCPClient], tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    mcp_method = OPENAI_TO_MCP.get(tool_name)
    if not mcp_method:
        return {"content":[{"type":"text","text":f"Tool '{tool_name}' no mapeada a MCP (SQLScout)."}],"isError":True}
    return clients["SQLScout"].call(mcp_method, args)

def exec_mcp_generic(clients: Dict[str, MCPClient], server: str, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if server not in clients:
        return {"content":[{"type":"text","text":f"Servidor '{server}' no está configurado."}],"isError":True}
    return clients[server].call(name, arguments)

@app.callback(invoke_without_command=True)
def chat(
    server: str = typer.Option("SQLScout", help="Nombre del server MCP por defecto (para atajos)")
):
    """
    Chat natural: el modelo decide qué tools usar (tool-calling).
    Atajos: :tools [FS|Git|SQLScout], :load <file.sql>, :explain <SQL>, :diagnose <SQL>, :optimize <SQL>, :apply <DDL>, :quit
    """
    client, model = _openai_client()
    memory = Memory()
    logger = JSONLLogger()

    # crea clientes por nombre (deben existir en mcp_config.json)
    SERVERS = ["SQLScout", "FS", "Git"]
    clients: Dict[str, MCPClient] = {}
    for name in SERVERS:
        try:
            clients[name] = MCPClient(server_name=name)
        except Exception as e:
            # No pasa nada si alguno no existe; solo avisa en pantalla
            typer.echo(f"(nota) servidor '{name}' no disponible: {e}")

    system_prompt = (
        "Eres un asistente de bases de datos con herramientas MCP. "
        "Si el usuario pide cargar un esquema .sql, explicar/diagnosticar/optimizar una consulta, "
        "elige y llama a las funciones adecuadas ANTES de responder. "
        "También puedes usar servidores MCP oficiales (FS = filesystem, Git = git). "
        "Cuando recibas resultados de herramientas, resume y recomienda pasos siguientes."
    )
    memory.add("system", system_prompt)

    typer.echo("Chat iniciado. (Comandos: ':tools [FS|Git|SQLScout]', ':load <ruta.sql>', ':explain <SQL>', ':diagnose <SQL>', ':optimize <SQL>', ':apply <DDL>', ':quit')")

    while True:
        user = typer.prompt("you").strip()
        if not user:
            continue
        if user == ":quit":
            break

        # ===== Router NL -> :load si menciona .sql =====
        low = user.lower()
        if (("carga" in low) or ("load" in low)) and ".sql" in low:
            m = re.search(r'([^\s"\'`]+\.sql)', user)
            if not m:
                typer.echo("No pude detectar la ruta .sql. Prueba con :load <ruta.sql>")
            else:
                path = os.path.normpath(m.group(1))
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        schema = f.read()
                except Exception as e:
                    typer.echo(f"Error leyendo {path}: {e}")
                else:
                    resp = _exec_mcp_sql(clients, "sql_load", {"schema": schema})
                    typer.echo(render_tool_result(resp.get("result", resp)))
                    logger.log({"event":"tools/call","name":"sql.load","path":path})
            continue

        # ===== Atajos manuales =====
        if user.startswith(":tools"):
            parts = user.split()
            target = parts[1] if len(parts) > 1 else server
            if target in clients:
                resp = clients[target].list_tools()
                typer.echo(_pretty(resp))
            else:
                typer.echo(f"Servidor '{target}' no está configurado.")
            continue

        if user.startswith(":load "):
            path = user.replace(":load","",1).strip()
            try:
                schema = open(path, "r", encoding="utf-8").read()
            except Exception as e:
                typer.echo(f"Error leyendo {path}: {e}")
                continue
            resp = _exec_mcp_sql(clients, "sql_load", {"schema": schema})
            typer.echo(render_tool_result(resp.get("result", resp)))
            logger.log({"event":"tools/call","name":"sql.load","path":path})
            continue

        if user.startswith(":explain "):
            q = user.replace(":explain","",1).strip()
            resp = _exec_mcp_sql(clients, "sql_explain", {"query": q})
            typer.echo(render_tool_result(resp.get("result", resp)))
            logger.log({"event":"tools/call","name":"sql.explain","query":q})
            continue

        if user.startswith(":diagnose "):
            q = user.replace(":diagnose","",1).strip()
            resp = _exec_mcp_sql(clients, "sql_diagnose", {"query": q})
            typer.echo(render_tool_result(resp.get("result", resp)))
            logger.log({"event":"tools/call","name":"sql.diagnose","query":q})
            continue

        if user.startswith(":optimize "):
            q = user.replace(":optimize","",1).strip()
            resp = _exec_mcp_sql(clients, "sql_optimize", {"query": q})
            typer.echo(render_tool_result(resp.get("result", resp)))
            logger.log({"event":"tools/call","name":"sql.optimize","query":q})
            continue

        if user.startswith(":apply "):
            ddl = user.replace(":apply","",1).strip()
            resp = _exec_mcp_sql(clients, "sql_apply", {"ddl": ddl})
            typer.echo(render_tool_result(resp.get("result", resp)))
            logger.log({"event":"tools/call","name":"sql.apply","ddl":ddl})
            continue
        # ===== Fin atajos =====

        # ===== Flujo natural con tool-calling =====
        messages: List[Dict[str, Any]] = memory.dump() + [{"role":"user","content":user}]
        reply = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=OPENAI_TOOLS,
            tool_choice="auto",
            temperature=0.3,
            max_tokens=600
        )

        msg = reply.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)

        if tool_calls:
            tool_results_msgs = []
            for tc in tool_calls:
                tname = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}

                if tname == "mcp_run":
                    mcp_resp = exec_mcp_generic(
                        clients,
                        server=args.get("server",""),
                        name=args.get("name",""),
                        arguments=args.get("arguments",{})
                    )
                elif tname in OPENAI_TO_MCP:
                    mcp_resp = _exec_mcp_sql(clients, tname, args)
                else:
                    mcp_resp = {"content":[{"type":"text","text":f"Tool '{tname}' no soportada en host."}],"isError":True}

                tool_results_msgs.append({
                    "role":"tool",
                    "tool_call_id": getattr(tc, "id", str(uuid.uuid4())),
                    "content": render_tool_result(mcp_resp.get("result", mcp_resp))
                })

            follow = client.chat.completions.create(
                model=model,
                messages=messages + [
                    {"role":"assistant","content":msg.content or "", "tool_calls":[tc.__dict__ for tc in tool_calls]}
                ] + tool_results_msgs,
                temperature=0.2,
                max_tokens=600
            )
            final_text = follow.choices[0].message.content
            typer.echo(f"assistant:\n{final_text}")
            memory.add("user", user)
            memory.add("assistant", final_text)
            logger.log({"event":"chat+tools","user":user,"assistant":final_text})
        else:
            text = msg.content
            typer.echo(f"assistant:\n{text}")
            memory.add("user", user)
            memory.add("assistant", text)
            logger.log({"event":"chat","user":user,"assistant":text})

    for c in clients.values():
        try: c.close()
        except: pass
    typer.echo("Chat finalizado.")

if __name__ == "__main__":
    app()
