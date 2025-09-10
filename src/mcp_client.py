import json, subprocess, uuid, os
from typing import Any, Dict

class MCPConfigError(Exception): ...

class MCPClient:
    def __init__(self, config_path: str = "mcp_config.json", server_name: str = "SQLScout"):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        servers = cfg.get("servers", [])
        match = next((s for s in servers if s.get("name") == server_name), None)
        if not match:
            raise MCPConfigError(f"Server '{server_name}' no encontrado en {config_path}")

        if match.get("transport") != "stdio":
            raise MCPConfigError("Solo stdio implementado en este MVP")

        cmd = [match["command"]] + match.get("args", [])
        cwd = match.get("cwd", ".")
        env = os.environ.copy()
        env.update(match.get("env", {}))

        self.proc = subprocess.Popen(
            cmd, cwd=cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1
        )

        # Handshake
        self._send({
            "jsonrpc":"2.0", "id": self._id(),
            "method":"initialize",
            "params":{
                "protocolVersion":"2024-11-05",
                "clientInfo":{"name":"host-cli","version":"0.1"},
                "capabilities": {}
            }
        })
        self._read()  # resp initialize

        self._send({"jsonrpc":"2.0","method":"notifications/initialized","params":{}})

    def _id(self) -> str:
        return str(uuid.uuid4())

    def _send(self, obj: Dict[str, Any]):
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _read(self) -> Dict[str, Any]:
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read() if self.proc.stderr else ""
            raise RuntimeError(f"Sin respuesta del servidor.\nSTDERR:\n{err}")
        return json.loads(line)

    def list_tools(self) -> Dict[str, Any]:
        self._send({"jsonrpc":"2.0","id": self._id(),"method":"tools/list","params":{}})
        return self._read()

    def call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self._send({"jsonrpc":"2.0","id": self._id(),"method":"tools/call","params":{"name":name,"arguments":arguments}})
        return self._read()

    def close(self):
        try:
            self.proc.terminate()
        except Exception:
            pass
