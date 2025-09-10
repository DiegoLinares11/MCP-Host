import json, os, time
from typing import Any, Dict

class JSONLLogger:
    def __init__(self, path: str = "logs/client.jsonl"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path

    def log(self, event: Dict[str, Any]):
        event = {"ts": time.time(), **event}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
