import os, json, typer, uuid
from openai import OpenAI
from dotenv import load_dotenv
from typing import Any, Dict, List
from .mcp_client import MCPClient
from .memory import Memory
from .logging_middleware import JSONLLogger

app = typer.Typer(help="Chat Host (OpenAI) + Tool Calling hacia MCP SQLScout")

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

# ---- Render rápido para structuredContent.result del server
def render_tool_result(result: Dict[str, Any]) -> str:
    """
    Adapta la respuesta del servidor MCP (fastmcp) a texto lindo.
    Respeta 'structuredContent.result' cuando exista.
    """
    # fastmcp suele devolver {"content":[{"type":"text","text": "..."}], "structuredContent":{...}}
    sc = result.get("structuredContent", {})
    if sc and "result" in sc:
        data = sc["result"]
        if isinstance(data, list) and data and isinstance(data[0], dict):
            # tabla markdown minimal (cabeceras = keys del 1er dict)
            headers = list(data[0].keys())
            rows = []
            for r in data:
                rows.append("| " + " | ".join(str(r.get(h, "")) for h in headers) + " |")
            head = "| " + " | ".join(headers) + " |"
            sep  = "| " + " | ".join("---" for _ in headers) + " |"
            return "\n".join([head, sep] + rows)
        # dict o string
        return _pretty(data)
    # fallback: concatena textos
    parts = result.get("content", [])
    if isinstance(parts, list):
        texts = [p.get("text","") for p in parts if isinstance(p, dict) and p.get("type")=="text"]
        if texts:
            return "\n".join(texts)
    return _pretty(result)

# ---- Catálogo de tools expuestas al LLM (OpenAI function calling)
# Importante: el "name" aquí es lo que el LLM invoca; luego lo mapeamos a las tools MCP reales.
OPENAI_TOOLS = [
    {"type": "function", "function": {
        "name": "sql_load",
        "description": "Carga un esquema SQL en SQLite (texto del .sql completo).",
        "parameters": {"type":"object","properties":{"schema":{"type":"string"}},"required":["schema"]}
    }},
    {"type": "function", "function": {
        "name": "sql_explain",
        "description": "Muestra EXPLAIN QUERY PLAN de una consulta SQL.",
        "parameters": {"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}
    }},
    {"type": "function", "function": {
        "name": "sql_diagnose",
        "description": "Aplica reglas estáticas de diagnóstico (select *, like '%', funciones en WHERE, etc.).",
        "parameters": {"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}
    }},
    {"type": "function", "function": {
        "name": "sql_optimize",
        "description": "Sugiere índices o reescrituras basado en el diagnóstico.",
        "parameters": {"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}
    }},
    {"type": "function", "function": {
        "name": "sql_apply",
        "description": "Aplica DDL como CREATE/DROP INDEX, ALTER TABLE.",
        "parameters": {"type":"object","properties":{"ddl":{"type":"string"}},"required":["ddl"]}
    }},
    # Si agregaste la tool extra en el server_mcp:
    {"type": "function", "function": {
        "name": "sql_optimize_apply",
        "description": "Compara plan antes/después aplicando DDL en una transacción.",
        "parameters": {"type":"object","properties":{
            "query":{"type":"string"},"ddl":{"type":"string"}
        },"required":["query","ddl"]}
    }},
]

# Mapeo nombre OpenAI -> nombre MCP (tal cual los registraste en FastMCP)
OPENAI_TO_MCP = {
    "sql_load": "sql.load",
    "sql_explain": "sql.explain",
    "sql_diagnose": "sql.diagnose",
    "sql_optimize": "sql.optimize",
    "sql_apply": "sql.apply",                # asegúrate de tenerla definida
    "sql_optimize_apply": "sql.optimize_apply",  # si la agregaste
}

def _exec_mcp(mcp: MCPClient, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    mcp_method = OPENAI_TO_MCP.get(tool_name)
    if not mcp_method:
        return {"content":[{"type":"text","text":f"Tool '{tool_name}' no mapeada a MCP."}],"isError":True}
    return mcp.call(mcp_method, args)

@app.command("chat")
def chat(
    server: str = typer.Option("SQLScout", help="Nombre del server MCP en mcp_config.json")
):
    """
    Chat natural: el modelo decide qué tools usar (tool-calling).
    Comandos manuales (fallback): :tools, :load <file.sql>, :explain <SQL>, :diagnose <SQL>, :optimize <SQL>, :apply <DDL>, :quit
    """
    client, model = _openai_client()
    memory = Memory()
    logger = JSONLLogger()
    mcp = MCPClient(server_name=server)

    system_prompt = (
        "Eres un asistente de base de datos con herramientas MCP. "
        "Si el usuario pide análisis SQL, esquemas, diagnóstico o índices, decide y llama a las funciones adecuadas. "
        "Tras recibir resultados de herramientas, resume y recomienda mejoras prácticas."
    )
    memory.add("system", system_prompt)

    typer.echo("Chat iniciado. (Escribe en lenguaje natural o usa comandos ':tools', ':load', ':explain', ':diagnose', ':optimize', ':apply', ':quit')")

    while True:
        user = typer.prompt("you")
        if user.strip() == ":quit":
            break

        # ====== Fallback manual opcional ======
        if user.strip() == ":tools":
            resp = mcp.list_tools()
            typer.echo(_pretty(resp))
            logger.log({"event":"tools/list","resp":resp})
            continue

        if user.startswith(":load "):
            path = user.replace(":load","",1).strip()
            try:
                schema = open(path, "r", encoding="utf-8").read()
            except Exception as e:
                typer.echo(f"Error leyendo {path}: {e}")
                continue
            resp = _exec_mcp(mcp, "sql_load", {"schema": schema})
            typer.echo(render_tool_result(resp.get("result", resp)))
            logger.log({"event":"tools/call","name":"sql.load"})
            continue

        if user.startswith(":explain "):
            q = user.replace(":explain","",1).strip()
            resp = _exec_mcp(mcp, "sql_explain", {"query": q})
            typer.echo(render_tool_result(resp.get("result", resp)))
            logger.log({"event":"tools/call","name":"sql.explain","query":q})
            continue

        if user.startswith(":diagnose "):
            q = user.replace(":diagnose","",1).strip()
            resp = _exec_mcp(mcp, "sql_diagnose", {"query": q})
            typer.echo(render_tool_result(resp.get("result", resp)))
            logger.log({"event":"tools/call","name":"sql.diagnose","query":q})
            continue

        if user.startswith(":optimize "):
            q = user.replace(":optimize","",1).strip()
            resp = _exec_mcp(mcp, "sql_optimize", {"query": q})
            typer.echo(render_tool_result(resp.get("result", resp)))
            logger.log({"event":"tools/call","name":"sql.optimize","query":q})
            continue

        if user.startswith(":apply "):
            ddl = user.replace(":apply","",1).strip()
            resp = _exec_mcp(mcp, "sql_apply", {"ddl": ddl})
            typer.echo(render_tool_result(resp.get("result", resp)))
            logger.log({"event":"tools/call","name":"sql.apply","ddl":ddl})
            continue
        # ====== Fin fallback ======

        # ====== Flujo natural con tool-calling ======
        messages: List[Dict[str, Any]] = memory.dump() + [{"role":"user","content":user}]
        # 1) Pedimos respuesta con tools disponibles
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
            # 2) Ejecutamos cada tool que el modelo pidió
            tool_results_msgs = []
            for tc in tool_calls:
                t_name = tc.function.name
                args = {}
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    pass
                mcp_resp = _exec_mcp(mcp, t_name, args)  # llama MCP real
                # Guardamos un “mensaje de tool” para reinyectarlo
                tool_results_msgs.append({
                    "role": "tool",
                    "tool_call_id": tc.id if hasattr(tc, "id") else str(uuid.uuid4()),
                    "content": render_tool_result(mcp_resp.get("result", mcp_resp))
                })

            # 3) Reinyectamos resultados y pedimos explicación/resumen final
            follow = client.chat.completions.create(
                model=model,
                messages=messages + [
                    {"role":"assistant","content":msg.content or "", "tool_calls": [tc.__dict__ for tc in tool_calls]}
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
            # Sin tools: respuesta directa
            text = msg.content
            typer.echo(f"assistant:\n{text}")
            memory.add("user", user)
            memory.add("assistant", text)
            logger.log({"event":"chat","user":user,"assistant":text})

    mcp.close()
    typer.echo("Chat finalizado.")
