# src/host.py
import os, json, typer, uuid, re
from typing import Any, Dict, List
from dotenv import load_dotenv
from openai import OpenAI

from .mcp_client import MCPClient
from .memory import Memory
from .logging_middleware import JSONLLogger

app = typer.Typer(help="Chat Host (OpenAI) + Tool Calling hacia MCP (SQLScout/FS/Git)")
def _settings():
    load_dotenv()
    ws = os.getenv("WORKSPACE_ROOT")
    rp = os.getenv("REPO_ROOT")
    if not ws or not rp:
        raise RuntimeError("Faltan WORKSPACE_ROOT y/o REPO_ROOT en .env")
    return ws.rstrip("/\\"), rp.rstrip("/\\")

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
def _exec_fs_read_text(clients, relative_path: str) -> Dict[str, Any]:
    WS, _ = _settings()
    abs_path = os.path.normpath(os.path.join(WS, relative_path))
    return clients["FS"].call("read_text_file", {"path": abs_path})

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
# === Wrappers de alto nivel (sin paths) ===
OPENAI_TOOLS += [
    {"type": "function", "function": {
        "name": "fs_write_text",
        "description": "Crea o sobrescribe un archivo de texto DENTRO del workspace. El path puede ser relativo (p.ej. 'README.md' o 'docs/plan.md').",
        "parameters": {"type":"object","properties":{
            "relative_path":{"type":"string","description":"Ruta relativa dentro del workspace"},
            "content":{"type":"string"}
        },"required":["relative_path","content"]}
    }},
    {"type": "function", "function": {
        "name": "fs_list",
        "description": "Lista un directorio del workspace (ruta relativa).",
        "parameters": {"type":"object","properties":{
            "relative_path":{"type":"string","description":"Ruta relativa dentro del workspace","default":"."}
        },"required":["relative_path"]}
    }},
    {"type": "function", "function": {
        "name": "git_init_here",
        "description": "Inicializa un repositorio git en REPO_ROOT si aún no existe.",
        "parameters": {"type":"object","properties":{},"required":[]}
    }},
    {"type": "function", "function": {
        "name": "git_add_files",
        "description": "Añade SOLO los archivos indicados al staging (paths relativos al REPO_ROOT). Nunca uses 'add all'.",
        "parameters": {"type":"object","properties":{
            "files":{"type":"array","items":{"type":"string"},"description":"Lista de rutas relativas a la raíz del repo"}
        },"required":["files"]}
    }},

    {"type": "function", "function": {
        "name": "git_commit_msg",
        "description": "git commit -m en REPO_ROOT.",
        "parameters": {"type":"object","properties":{
            "message":{"type":"string"}
        },"required":["message"]}
    }},
    {"type": "function", "function": {
        "name": "git_status_here",
        "description": "git status en REPO_ROOT.",
        "parameters": {"type":"object","properties":{},"required":[]}
    }},
    {"type": "function", "function": {
        "name": "git_log_here",
        "description": "git log en REPO_ROOT.",
        "parameters": {"type":"object","properties":{
            "max_count":{"type":"integer","default":5}
        },"required":[]}
    }},
        {"type": "function", "function": {
        "name": "fs_read_text",
        "description": "Lee un archivo de texto del workspace (ruta relativa).",
        "parameters": {"type":"object","properties":{
            "relative_path":{"type":"string"}
        },"required":["relative_path"]}
    }},
]

# Añadir después de tus tools existentes:
OPENAI_TOOLS += [
    {"type": "function", "function": {
        "name": "supabase_create_user",
        "description": "Crea un nuevo usuario en Supabase",
        "parameters": {"type": "object", "properties": {
            "email": {"type": "string"},
            "password": {"type": "string"},
            "metadata": {"type": "object", "default": {}}
        }, "required": ["email", "password"]}
    }},
    {"type": "function", "function": {
        "name": "supabase_send_magic_link",
        "description": "Envía un magic link de autenticación",
        "parameters": {"type": "object", "properties": {
            "email": {"type": "string"},
            "redirect_to": {"type": "string", "default": "http://localhost:3000"}
        }, "required": ["email"]}
    }},
    {"type": "function", "function": {
        "name": "supabase_list_policies",
        "description": "Lista políticas RLS de un schema",
        "parameters": {"type": "object", "properties": {
            "schema_name": {"type": "string", "default": "public"},
            "table_name": {"type": "string"}
        }, "required": ["schema_name"]}
    }},
    {"type": "function", "function": {
        "name": "supabase_set_role",
        "description": "Asigna rol a un usuario",
        "parameters": {"type": "object", "properties": {
            "user_id": {"type": "string"},
            "role": {"type": "string"},
            "expires_at": {"type": "string"}
        }, "required": ["user_id", "role"]}
    }},
    {"type": "function", "function": {
        "name": "supabase_user_stats",
        "description": "Obtiene estadísticas de usuarios",
        "parameters": {"type": "object", "properties": {
            "period": {"type": "string", "enum": ["today", "week", "month", "all"], "default": "week"}
        }, "required": []}
    }},
    {"type": "function", "function": {
        "name": "supabase_bulk_invite",
        "description": "Invita múltiples usuarios en lote",
        "parameters": {"type": "object", "properties": {
            "emails": {"type": "array", "items": {"type": "string"}},
            "default_role": {"type": "string", "default": "user"}
        }, "required": ["emails"]}
    }}
]

# Mapeo OpenAI -> tools del server SQLScouts
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
def _exec_fs_write_text(clients, relative_path: str, content: str) -> Dict[str, Any]:
    WS, _ = _settings()
    abs_path = os.path.normpath(os.path.join(WS, relative_path))
    return clients["FS"].call("write_file", {"path": abs_path, "content": content})

def _exec_fs_list(clients, relative_path: str = ".") -> Dict[str, Any]:
    WS, _ = _settings()
    abs_path = os.path.normpath(os.path.join(WS, relative_path))
    return clients["FS"].call("list_directory", {"path": abs_path})

def _exec_git_init_here(clients) -> Dict[str, Any]:
    _, REPO = _settings()
    return clients["Git"].call("git_init", {"repo_path": REPO})

def _exec_git_add_files(clients, files: List[str]) -> Dict[str, Any]:
    _, REPO = _settings()
    # Filtro defensivo para evitar `.git`, `__pycache__`, binarios, etc.
    BLOCKLIST_PREFIXES = (".git", "_git", "__pycache__")
    BLOCKLIST_EXT = (".pyc", ".pyo", ".pyd", ".log")

    safe: List[str] = []
    for f in files:
        rp = (f or "").replace("\\", "/").lstrip("/")
        if (not rp) or any(rp.startswith(p) for p in BLOCKLIST_PREFIXES) or rp.endswith(BLOCKLIST_EXT):
            continue
        safe.append(rp)

    if not safe:
        return {"content":[{"type":"text","text":"No hay archivos válidos para agregar (se filtraron por reglas de seguridad)."}],"isError":True}

    # Llama al server Git con lista explícita
    return clients["Git"].call("git_add", {"repo_path": REPO, "files": safe})


def _exec_git_add_all(clients) -> Dict[str, Any]:
    _, REPO = _settings()
    # usa git_add con files=["."] (el server git lo soporta)
    return clients["Git"].call("git_add", {"repo_path": REPO, "files": ["."]})

def _exec_git_commit_msg(clients, message: str) -> Dict[str, Any]:
    _, REPO = _settings()
    return clients["Git"].call("git_commit", {"repo_path": REPO, "message": message})

def _exec_git_status_here(clients) -> Dict[str, Any]:
    _, REPO = _settings()
    return clients["Git"].call("git_status", {"repo_path": REPO})

def _exec_git_log_here(clients, max_count: int = 5) -> Dict[str, Any]:
    _, REPO = _settings()
    return clients["Git"].call("git_log", {"repo_path": REPO, "max_count": max_count})

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
    SERVERS = ["SQLScout", "FS", "Git", "Supabase"]
    clients: Dict[str, MCPClient] = {}
    for name in SERVERS:
        try:
            clients[name] = MCPClient(server_name=name)
        except Exception as e:
            # No pasa nada si alguno no existe; solo avisa en pantalla
            typer.echo(f"(nota) servidor '{name}' no disponible: {e}")

        # === Importar tools remotas del server "Supabase" al catálogo de OpenAI ===
    REMOTE_SUPABASE_TOOL_NAMES = set()
    if "Supabase" in clients:
        try:
            res = clients["Supabase"].list_tools()
            supabase_tools = res.get("result", {}).get("tools", [])
            for t in supabase_tools:
                # Agrega cada tool remota tal cual (nombre real: create_user, list_users, etc.)
                OPENAI_TOOLS.append({"type": "function", "function": t})
            REMOTE_SUPABASE_TOOL_NAMES = {t.get("name") for t in supabase_tools if isinstance(t, dict)}
            typer.echo(f"✅ Tools de Supabase añadidas: {sorted(REMOTE_SUPABASE_TOOL_NAMES)}")
        except Exception as e:
            typer.echo(f"⚠️ No se pudieron cargar las tools de Supabase: {e}")


    system_prompt = (
        "Eres un asistente que puede operar sobre archivos (FS) y Git sin que el usuario dé rutas absolutas. "
        "Reglas:\n"
        "1) El WORKSPACE_ROOT y REPO_ROOT están configurados en variables de entorno; NUNCA preguntes al usuario la ruta absoluta.\n"
        "2) Para crear/editar archivos usa fs_write_text(relative_path, content). Para listar usa fs_list(relative_path).\n"
        "3) Para Git en REPO_ROOT: usa git_init_here(), git_add_files(files=[...]), git_commit_msg(message), git_status_here(), git_log_here(max_count). NUNCA uses “add all”. Siempre especifica la lista de archivos exactos a stagear. NO incluyas rutas a .git, _git, __pycache__, *.pyc, *.pyo, *.pyd, *.log, ni nada ignorado por .gitignore.\n"
        "4) Para SQL usa sql_load/sql_explain/sql_diagnose/sql_optimize como antes.\n"
        "5) Encadena tools: p.ej., si el usuario dice 'crea README y haz commit', primero fs_write_text('README.md', ...), luego git_add_files(files=['README.md']), y por último git_commit_msg('mensaje descriptivo').\n"
        "6) Siempre que el usuario pida una acción concreta que requiera herramientas, LLÁMALAS antes de responder.\n\n"
        "Extensión para Supabase:\n"
        "- Si el usuario pide crear, listar, actualizar, eliminar o recuperar usuarios, DEBES usar las tools de Supabase: "
        "create_user, list_users, get_user_by_id, update_user_metadata, delete_user.\n"
        "- Si pide enlaces de acceso o autenticación, usa send_magic_link o reset_user_password.\n"
        "- Si pide estadísticas de usuarios, usa get_user_stats.\n"
        "- Si pide invitar varios correos, usa bulk_invite_users.\n"
        "- Nunca respondas 'no tengo acceso a la base de datos'. Debes llamar a la tool.\n"
        "- Interpreta español natural: 'contraseña' => password, 'correo' => email.\n"
    )


    memory.add("system", system_prompt)

    typer.echo("Chat iniciado. (Comandos: ':tools [FS|Git|SQLScout]', ':load <ruta.sql>', ':explain <SQL>', ':diagnose <SQL>', ':optimize <SQL>', ':apply <DDL>', ':quit')")

    while True:
        user = typer.prompt("you").strip()
        if not user:
            continue
        if user == ":quit":
            break
        
                # ====== Invocación genérica: :call <SERVER> <TOOL> <JSON> ======
        if user.startswith(":call "):
            try:
                _, rest = user.split(" ", 1)
                parts = rest.strip().split(" ", 2)
                if len(parts) < 3:
                    typer.echo("Uso: :call <SERVER> <TOOL> <JSON-ARGS>")
                    continue
                server_name, tool_name, json_args = parts[0], parts[1], parts[2]
                import json as _json
                args = _json.loads(json_args)
            except Exception as e:
                typer.echo(f"Error parseando comando :call: {e}")
                continue

            target_client = clients.get(server_name)
            if not target_client:
                typer.echo(f"Servidor '{server_name}' no está configurado.")
                continue

            try:
                resp = target_client.call(tool_name, args)
                pretty = render_tool_result(resp.get("result", resp))
                typer.echo(pretty)
                logger.log({"event":"tools/call","server":server_name,"tool":tool_name,"args":args})
            except Exception as e:
                typer.echo(f"Error llamando {server_name}:{tool_name} -> {e}")
            continue

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
                t_name = tc.function.name
                args = {}
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    pass

                # === Router de wrappers amigables ===
                # === Router de wrappers amigables ===
                if t_name == "fs_write_text":
                    mcp_resp = _exec_fs_write_text(clients, args["relative_path"], args["content"])
                elif t_name == "fs_list":
                    mcp_resp = _exec_fs_list(clients, args.get("relative_path","."))
                elif t_name == "git_init_here":
                    mcp_resp = _exec_git_init_here(clients)
                elif t_name == "git_add_all":
                    mcp_resp = _exec_git_add_all(clients)
                elif t_name == "git_commit_msg":
                    mcp_resp = _exec_git_commit_msg(clients, args["message"])
                elif t_name == "git_status_here":
                    mcp_resp = _exec_git_status_here(clients)
                elif t_name == "git_log_here":
                    mcp_resp = _exec_git_log_here(clients, args.get("max_count",5))
                elif t_name == "fs_read_text":
                    mcp_resp = _exec_fs_read_text(clients, args["relative_path"])
                elif t_name == "git_add_files":
                    mcp_resp = _exec_git_add_files(clients, args.get("files", []))


                # === Tools remotas reales del server "Supabase" ===
                elif t_name in REMOTE_SUPABASE_TOOL_NAMES:
                    mcp_resp = exec_mcp_generic(clients, "Supabase", t_name, args)


                # Supabase
                elif t_name == "supabase_create_user":
                    mcp_resp = exec_mcp_generic(clients, "Supabase", "create_user", args)
                elif t_name == "supabase_send_magic_link":
                    mcp_resp = exec_mcp_generic(clients, "Supabase", "send_magic_link", args)
                elif t_name == "supabase_list_policies":
                    mcp_resp = exec_mcp_generic(clients, "Supabase", "list_policies", args)
                elif t_name == "supabase_set_role":
                    mcp_resp = exec_mcp_generic(clients, "Supabase", "set_user_role", args)
                elif t_name == "supabase_user_stats":
                    mcp_resp = exec_mcp_generic(clients, "Supabase", "get_user_stats", args)
                elif t_name == "supabase_bulk_invite":
                    mcp_resp = exec_mcp_generic(clients, "Supabase", "bulk_invite_users", args)

                # Genérica (cualquier servidor/tool): mcp_run
                elif t_name == "mcp_run":
                    mcp_resp = exec_mcp_generic(
                        clients,
                        args["server"],
                        args["name"],
                        args.get("arguments", {})
                    )

                # SQL (usa el mapeo OPENAI_TO_MCP / cliente SQLScout)
                else:
                    mcp_resp = _exec_mcp_sql(clients, t_name, args)

                tool_results_msgs.append({
                    "role": "tool",
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
