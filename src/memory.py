from typing import List, Dict

class Memory:
    def __init__(self):
        self.messages: List[Dict] = []

    def add(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})

    def dump(self) -> List[Dict]:
        return list(self.messages)
