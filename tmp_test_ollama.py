import sys

sys.path.insert(0, ".")
from src.config import load_config
from src.llm import check_provider, chat_json, to_provider

cfg = load_config()
ok, msg = check_provider(cfg, "ollama")
print("check ollama:", msg)
if ok:
    p = to_provider("ollama", cfg)
    data = chat_json(p, "Réponds en JSON", "Donne un objet JSON avec cle ok=true et une phrase.")
    print("chat_json:", data)