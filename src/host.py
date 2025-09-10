import os, json, typer
from openai import OpenAI
from dotenv import load_dotenv
from .mcp_client import MCPClient
from .memory import Memory
from .logging_middleware import JSONLLogger

app = typer.Typer(help="MCP Host + Chat con OpenAI", no_args_is_help=True)


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
def ping():
    """Prueba rápida de Typer."""
    typer.echo("pong")

app.command("ping")(ping)

@app.command("chat")
def chat(
    server: str = typer.Option("SQLScout", help="Nombre del server MCP en mcp_config.json")
):
    """
    Chat CLI con OpenAI + comandos MCP inline:
      :tools
      :load <ruta.sql>
      :explain <SQL>
      :diagnose <SQL>
      :optimize <SQL>
      :quit
    """
    client, model = _openai_client()
    memory = Memory()
    logger = JSONLLogger()
    mcp = MCPClient(server_name=server)

    system_prompt = (
        "Eres un asistente técnico. Si el usuario ingresa comandos que empiezan con ':', "
        "no respondas tú: el host ejecutará herramientas MCP y luego te pasará los resultados. "
        "Cuando recibas resultados de herramientas, explícalos brevemente y da recomendaciones."
    )
    # Guardamos el system en la memoria para que persista entre turnos
    memory.add("system", system_prompt)

    typer.echo("Chat iniciado. Escribe texto o usa comandos (:tools, :load, :explain, :diagnose, :optimize, :quit)")

    while True:
        user = typer.prompt("you")

        # Comandos MCP
        if user.strip() == ":quit":
            break

        if user.strip() == ":tools":
            resp = mcp.list_tools()
            typer.echo(_pretty(resp))
            logger.log({"event":"tools/list","resp":resp})
            # también lo pasamos al LLM si quieres que lo recuerde
            memory.add("assistant", f"Tools disponibles: {_pretty(resp)}")
            continue

        if user.startswith(":load "):
            path = user.replace(":load","",1).strip()
            try:
                schema = open(path, "r", encoding="utf-8").read()
            except Exception as e:
                typer.echo(f"Error leyendo {path}: {e}")
                continue
            resp = mcp.call("sql.load", {"schema": schema})
            typer.echo(_pretty(resp))
            logger.log({"event":"tools/call","name":"sql.load","ok":True})
            memory.add("assistant", f"Carga de esquema: {_pretty(resp)}")
            continue

        if user.startswith(":explain "):
            q = user.replace(":explain","",1).strip()
            resp = mcp.call("sql.explain", {"query": q})
            typer.echo(_pretty(resp))
            logger.log({"event":"tools/call","name":"sql.explain","query":q})
            memory.add("assistant", f"Explain: {_pretty(resp)}")
            continue

        if user.startswith(":diagnose "):
            q = user.replace(":diagnose","",1).strip()
            resp = mcp.call("sql.diagnose", {"query": q})
            typer.echo(_pretty(resp))
            logger.log({"event":"tools/call","name":"sql.diagnose","query":q})
            memory.add("assistant", f"Diagnóstico: {_pretty(resp)}")
            continue

        if user.startswith(":optimize "):
            q = user.replace(":optimize","",1).strip()
            resp = mcp.call("sql.optimize", {"query": q})
            typer.echo(_pretty(resp))
            logger.log({"event":"tools/call","name":"sql.optimize","query":q})
            memory.add("assistant", f"Optimización: {_pretty(resp)}")
            continue

        if user.startswith(":apply "):
            ddl = user.replace(":apply","",1).strip()
            resp = mcp.call("sql.apply", {"ddl": ddl})
            typer.echo(_pretty(resp))
            logger.log({"event":"tools/call","name":"sql.apply","ddl":ddl})
            memory.add("assistant", f"DDL aplicado: {_pretty(resp)}")
            continue

        # opcional: :optapply <QUERY> || <DDL>
        if user.startswith(":optapply "):
            payload = user.replace(":optapply","",1).strip()
            try:
                q, ddl = [p.strip() for p in payload.split("||", 1)]
            except ValueError:
                typer.echo("Uso: :optapply <QUERY> || <DDL>")
                continue
            resp = mcp.call("sql.optimize_apply", {"query": q, "ddl": ddl})
            typer.echo(_pretty(resp))
            logger.log({"event":"tools/call","name":"sql.optimize_apply","query":q,"ddl":ddl})
            continue

        # --- Chat con OpenAI ---
        memory.add("user", user)

        reply = client.chat.completions.create(
            model=model,
            messages=memory.dump(),   # ya incluye system + historial + último user
            max_tokens=500,
            temperature=0.3
        )

        # SDK >=1.x: el texto viene en .choices[0].message.content (string)
        text = reply.choices[0].message.content
        typer.echo(f"assistant: {text}")

        memory.add("assistant", text)
        logger.log({"event":"chat","user":user,"assistant":text})

    mcp.close()
    typer.echo("Chat finalizado.")

if __name__ == "__main__":
    app()
