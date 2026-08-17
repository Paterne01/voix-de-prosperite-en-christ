import sys

sys.path.insert(0, ".")
from src.secrets import get_secret

print("HF token:", bool(get_secret("huggingface_token")))
print("gemini:", bool(get_secret("gemini_api_key")))