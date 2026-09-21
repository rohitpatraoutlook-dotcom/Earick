"""
Earick - Physics RAG chatbot (multi-book, merged reasoning, self-aware)
Single merged reasoning mode + background dream mode.
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from earick import Library
from earick.modes import SYSTEM_PROMPT_REASONED

load_dotenv(ROOT / ".env")
load_dotenv("/etc/secrets/.env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

TOP_K = 6
MAX_PER_BOOK = 3
ENSURE_MIN_BOOKS = 2
MAX_PER_CHAPTER = 2
MAX_CONTEXT_CHARS = 7000
MAX_PER_CHUNK = 1800
MAX_STEPS = 3

app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))

print("Loading Earick library...")
LIBRARY = Library(ROOT)
n_chunks, n_vocab = LIBRARY.load_index()
print(f"   -> {len(LIBRARY.books)} books registered")
for bid, b in LIBRARY.books.items():
    print(f"      - {bid:24s} {b.chunk_count():5d} chunks  {b.meta.get('title','')}")
print(f"   -> {n_chunks} total chunks, {n_vocab} vocab")

if not GROQ_API_KEY or GROQ_API_KEY.startswith("gsk_PASTE"):
    print("WARNING: GROQ_API_KEY missing/invalid")

try:
    from earick import dream_mode
    dream_mode.start()
    print("Dream Mode: started (background)")
except Exception as e:
    print(f"Dream Mode: failed to start ({e})")
    dream_mode = None


SYNONYMS = {
    "speed of light": ["relativity", "electromagnetic"],
    "gravity": ["gravitation", "newton", "weight"],
    "f=ma": ["force", "newton", "second"],
    "e=mc2": ["mass", "energy", "relativity"],
    "schrodinger": ["wave", "function", "quantum", "hamiltonian"],
    "uncertainty": ["heisenberg", "quantum", "momentum"],
    "entropy": ["second", "thermodynamics", "heat"],
    "photon": ["light", "quantum", "photoelectric"],
    "electron": ["charge", "quantum", "fermion"],
    "refraction": ["snell", "optics", "light"],
    "momentum": ["impulse", "collision"],
    "maxwell": ["electromagnetic", "faraday"],
    "schwarzschild": ["black", "hole", "radius", "relativity", "metric"],
    "black hole": ["event", "horizon", "schwarzschild", "singularity"],
    "einstein field": ["relativity", "tensor", "metric", "curvature"],
    "spacetime": ["metric", "curvature", "relativity"],
    "cosmology": ["universe", "expansion", "friedmann"],
    "string theory": ["string", "brane", "extra", "dimension"],
    "quantum gravity": ["planck", "loop", "string", "graviton"],
    "fission": ["nuclear", "uranium"],
    "fusion": ["nuclear", "hydrogen", "helium"],
    "quark": ["particle", "standard", "model"],
    "dark matter": ["halo", "rotation", "curve"],
    "dark energy": ["cosmological", "constant", "acceleration"],
    "fluid": ["navier", "stokes", "viscosity", "flow"],
}

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]{1,}")

def tokenize(t): return TOKEN_RE.findall(t.lower())

def expand_query_tokens(q):
    tokens = tokenize(q)
    ql = q.lower()
    for phrase, syns in SYNONYMS.items():
        if phrase in ql: tokens.extend(syns)
    return tokens

def retrieve(query):
    tokens = expand_query_tokens(query)
    if not tokens: return []
    hits = LIBRARY.search(tokens, top_k=TOP_K, max_per_book=MAX_PER_BOOK,
                          ensure_min_books=ENSURE_MIN_BOOKS, max_per_chapter=MAX_PER_CHAPTER)
    results = []
    for score, cid in hits:
        rec = LIBRARY.chunks.get(cid)
        if not rec: continue
        book = LIBRARY.books.get(rec["book_id"])
        results.append({
            "id": rec["id"], "text": rec["text"],
            "pages": f"{rec['page_start']}-{rec['page_end']}",
            "chapter": rec.get("chapter", ""),
            "book_id": rec["book_id"],
            "book_title": book.meta.get("title", rec["book_id"]) if book else rec["book_id"],
            "book_author": book.meta.get("author", "") if book else "",
            "score": round(score, 3),
        })
    return results

def build_context(hits, max_per_chunk=MAX_PER_CHUNK):
    if not hits: return "(no relevant passages found)"
    blocks, total = [], 0
    for i, h in enumerate(hits, 1):
        text = (h.get("text") or "").strip()
        if not text: continue
        if len(text) > max_per_chunk:
            text = text[:max_per_chunk].rsplit(" ", 1)[0] + " [...]"
        header = f"[{i}] ({h.get('book_title','?')}, pp.{h.get('pages','?')}, {h.get('chapter','?')})"
        block = f"{header}\n{text}"
        if total + len(block) > MAX_CONTEXT_CHARS and blocks: break
        blocks.append(block); total += len(block)
    return "\n\n".join(blocks) if blocks else "(no relevant passages found)"

STEP_HEADER_RE = re.compile(r"^\s*=====\s*STEP\s+(\d+)\s*=====\s*$", re.MULTILINE)

def enforce_step_cap(text):
    matches = list(STEP_HEADER_RE.finditer(text))
    if len(matches) <= MAX_STEPS: return text
    cut_at = matches[MAX_STEPS].start()
    return text[:cut_at].rstrip() + "\n\n===== DIRECT ANSWER =====\n\nReasoning stopped: cycle cap.\n"

def build_history_block(history):
    if not history: return ""
    lines = ["CONVERSATION SO FAR:"]
    for h in history:
        tag = "User" if h["role"] == "user" else "Earick"
        lines.append(f"{tag}: {h['content']}")
    return "\n".join(lines) + "\n\n"

def call_groq(user_query, hits, history=None):
    if not GROQ_API_KEY or GROQ_API_KEY.startswith("gsk_PASTE"):
        return "Groq API key missing."

    context = build_context(hits)
    history_block = build_history_block(history or [])

    user_prompt = (
        history_block
        + "PHYSICS/MATH CONTEXT:\n-----\n" + context + "\n-----\n\n"
        + "QUESTION: " + user_query + "\n\n"
        + "Produce the reasoned answer now."
    )

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_REASONED},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.5,
        "max_tokens": 2000,
    }
    req = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {GROQ_API_KEY}",
                 "Content-Type": "application/json",
                 "User-Agent": "Earick/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        reply = data["choices"][0]["message"]["content"].strip()
        return enforce_step_cap(reply)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        return f"Groq HTTP {e.code}: {body}"
    except urllib.error.URLError as e:
        return f"Groq network error: {e.reason}"
    except Exception as e:
        return f"Groq request failed: {e}"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    if dream_mode:
        try: dream_mode.mark_user_active()
        except Exception: pass
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    history = data.get("history") or []
    if not message:
        return jsonify({"reply": "Please type a question."}), 400
    hits = retrieve(message)
    reply = call_groq(message, hits, history=history)
    return jsonify({
        "reply": reply, "mode": "reasoned",
        "sources": [{"topic": h["chapter"], "pages": h["pages"],
                     "book_title": h["book_title"], "book_author": h["book_author"],
                     "book_id": h["book_id"], "score": h["score"]} for h in hits],
    })

@app.route("/health")
def health():
    return jsonify({
        "status": "ok", "books": len(LIBRARY.books),
        "chunks": len(LIBRARY.chunks), "vocab": len(LIBRARY.idf),
        "model": GROQ_MODEL, "modes": ["reasoned", "dream"],
        "groq_configured": bool(GROQ_API_KEY) and not GROQ_API_KEY.startswith("gsk_PASTE"),
    })

@app.route("/books")
def books_list():
    return jsonify([{"book_id": bid, "title": b.meta.get("title", ""),
                     "author": b.meta.get("author", ""), "level": b.meta.get("level", ""),
                     "subjects": b.meta.get("subjects", []), "chunks": b.chunk_count()}
                    for bid, b in LIBRARY.books.items()])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 7860)), debug=False)
