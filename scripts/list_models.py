"""
List Groq models available to the current API key.
Reads .env directly (no python-dotenv) to avoid loader quirks.
"""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"

if not ENV.exists():
    sys.exit(f".env not found at {ENV}")

key = None
for line in ENV.read_text().splitlines():
    line = line.strip()
    if line.startswith("GROQ_API_KEY="):
        key = line.split("=", 1)[1].strip().strip('"').strip("'")
        break

if not key:
    sys.exit("GROQ_API_KEY not found in .env")

print(f"Key length: {len(key)}, starts with gsk_: {key.startswith('gsk_')}")
print()

req = urllib.request.Request(
    "https://api.groq.com/openai/v1/models",
    headers={
        "Authorization": f"Bearer {key}",
        "User-Agent": "Earick/1.0",
    },
)

try:
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", errors="replace")[:300]
    sys.exit(f"HTTP {e.code}: {body}")
except Exception as e:
    sys.exit(f"Request failed: {e}")

models = data.get("data", [])
print(f"Models available ({len(models)}):\n")
for m in sorted(models, key=lambda x: x["id"]):
    print(f"  {m['id']}")
