"""
Earick - Physics RAG chatbot
Retrieval: local TF-IDF over chunks.jsonl
Generation: Groq API via urllib (no external LLM SDK needed)
"""

import json
import math
import os
import re
import urllib.request
import urllib.error
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv


# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

CHUNKS_PATH = ROOT / "data" / "chunks" / "chunks.jsonl"
INDEX_PATH = ROOT / "data" / "chunks" / "index.json"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

TOP_K = 5
MAX_CONTEXT_CHARS = 6000


app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(ROOT / "static"),
)


# ------------------------------------------------------------------
# Load chunks + index at startup
# ------------------------------------------------------------------
print("📖 Loading chunks...")
CHUNKS_BY_ID = {}
with CHUNKS_PATH.open(encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        CHUNKS_BY_ID[rec["id"]] = rec
print(f"   → {len(CHUNKS_BY_ID)} chunks loaded")

print("📊 Loading TF-IDF index...")
INDEX = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
IDF = INDEX["idf"]
DOCS = INDEX["docs"]
N = INDEX["N"]
print(f"   → {N} docs, {len(IDF)} vocab")

if not GROQ_API_KEY or GROQ_API_KEY.startswith("gsk_PASTE"):
    print("⚠️  GROQ_API_KEY missing/invalid in .env — chat will fail")


# ------------------------------------------------------------------
# Query expansion — physics synonyms
# ------------------------------------------------------------------
SYNONYMS = {
    "speed of light": ["relativity", "electromagnetic"],
    "gravity": ["gravitation", "newton", "weight"],
    "f=ma": ["force", "newton", "second"],
    "e=mc2": ["mass", "energy", "relativity"],
    "e=mc^2": ["mass", "energy", "relativity"],
    "schrodinger": ["wave", "function", "quantum", "hamiltonian"],
    "uncertainty": ["heisenberg", "quantum", "momentum"],
    "entropy": ["second", "thermodynamics", "heat"],
    "photon": ["light", "quantum", "photoelectric"],
    "electron": ["charge", "quantum", "fermion"],
    "capacitor": ["capacitance", "charge", "electric"],
    "inductor": ["inductance", "magnetic", "current"],
    "refraction": ["snell", "optics", "light"],
    "momentum": ["impulse", "collision"],
    "wave": ["frequency", "wavelength", "optics"],
    "maxwell": ["electromagnetic", "faraday"],
    "carnot": ["thermodynamics", "entropy", "efficiency"],
}


TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]{1,}")


def tokenize(text: str) -> list:
    return TOKEN_RE.findall(text.lower())


def expand_query_tokens(query: str) -> list:
    tokens = tokenize(query)
    q_lower = query.lower()
    for phrase, syns in SYNONYMS.items():
        if phrase in q_lower:
            tokens.extend(syns)
    return tokens


# ------------------------------------------------------------------
# Retrieval
# ------------------------------------------------------------------
def score_doc(doc_entry, query_tokens_set):
    tf = doc_entry["tf"]
    score = 0.0
    matched = 0
    for tok in query_tokens_set:
        c = tf.get(tok, 0)
        if c:
            score += (1.0 + math.log(c)) * IDF.get(tok, 1.0)
            matched += 1
    if matched > 0:
        score *= (1.0 + 0.1 * matched)
    return score


def retrieve(query: str, top_k: int = TOP_K):
    tokens = expand_query_tokens(query)
    if not tokens:
        return []
    qset = set(tokens)
    scored = []
    for d in DOCS:
        s = score_doc(d, qset)
        if s > 0:
            scored.append((s, d["id"]))
    scored.sort(reverse=True)

    results = []
    for s, cid in scored[:top_k]:
        rec = CHUNKS_BY_ID.get(cid)
        if rec:
            results.append({
                "id": rec["id"],
                "text": rec["text"],
                "pages": f"{rec['page_start']}-{rec['page_end']}",
                "chapter": rec.get("chapter", ""),
                "score": round(s, 3),
            })
    return results


# ------------------------------------------------------------------
# Prompt + Groq call
# ------------------------------------------------------------------
SYSTEM_PROMPT = """You are Earick, a concise physics tutor.

Rules:
- Answer ONLY using the provided physics context from the textbook.
- If the context is insufficient or the question is not physics-related, reply in one short sentence ("That's outside my physics scope." or "I couldn't find that in the textbook.") and stop.
- Show the key formula(s) FIRST, then explain in 3-5 sentences.
- Equations may appear garbled in the context (PDF extraction artifacts). Reconstruct them into clean LaTeX when possible: use \\( ... \\) for inline math and \\[ ... \\] for display math.
- NEVER cite pages inline. Do NOT write "Source:", "[pages X]", or anything similar in the body.
- Page citations are added separately by the app. Just answer.
- Never invent numerical constants.
- Keep answers under 150 words unless the user asks for depth.
"""


def build_context(hits):
    if not hits:
        return "(no relevant passages found)"
    blocks = []
    total = 0
    for i, h in enumerate(hits, 1):
        block = f"[{i}] (pages {h['pages']}, {h['chapter']})\n{h['text']}"
        if total + len(block) > MAX_CONTEXT_CHARS:
            break
        blocks.append(block)
        total += len(block)
    return "\n\n".join(blocks)


def call_groq(user_query: str, hits):
    if not GROQ_API_KEY or GROQ_API_KEY.startswith("gsk_PASTE"):
        return "⚠️ Groq API key missing. Add GROQ_API_KEY to .env and restart."

    context = build_context(hits)
    user_prompt = (
        "Physics context from the textbook:\n"
        "-----\n"
        f"{context}\n"
        "-----\n\n"
        f"Student question: {user_query}\n\n"
        "Answer as Earick:"
    )

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 700,
    }

    req = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Earick/1.0 (Termux)",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        return f"⚠️ Groq HTTP {e.code}: {body}"
    except urllib.error.URLError as e:
        return f"⚠️ Groq network error: {e.reason}"
    except Exception as e:
        return f"⚠️ Groq request failed: {e}"


# ------------------------------------------------------------------
# Flask routes
# ------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"reply": "Please type a physics question."}), 400

    hits = retrieve(message, top_k=TOP_K)
    reply = call_groq(message, hits)
    return jsonify({
        "reply": reply,
        "sources": [
            {"topic": h["chapter"], "pages": h["pages"], "score": h["score"]}
            for h in hits
        ],
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "chunks": len(CHUNKS_BY_ID),
        "vocab": len(IDF),
        "model": GROQ_MODEL,
        "groq_configured": bool(GROQ_API_KEY) and not GROQ_API_KEY.startswith("gsk_PASTE"),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
