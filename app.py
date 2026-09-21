"""
Earick - Physics RAG chatbot (multi-book, synthesis-aware)
Retrieval: multi-book TF-IDF with diversity constraints
Generation: Groq API (openai/gpt-oss-120b)
"""

import json
import math
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


# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
load_dotenv(ROOT / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

TOP_K = 6                 # chunks sent to the LLM
MAX_PER_BOOK = 3          # at most this many chunks per book in the context
ENSURE_MIN_BOOKS = 2      # try to include at least this many books
MAX_PER_CHAPTER = 2       # at most this many chunks from any one section
MAX_CONTEXT_CHARS = 7000  # room for cross-book synthesis


app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(ROOT / "static"),
)


# ------------------------------------------------------------------
# Load multi-book library at startup
# ------------------------------------------------------------------
print("📚 Loading Earick library...")
LIBRARY = Library(ROOT)
n_chunks, n_vocab = LIBRARY.load_index()
print(f"   → {len(LIBRARY.books)} books registered")
for bid, b in LIBRARY.books.items():
    print(f"      · {bid:24s} {b.chunk_count():5d} chunks  {b.meta.get('title','')}")
print(f"   → {n_chunks} total chunks, {n_vocab} vocab")

if not GROQ_API_KEY or GROQ_API_KEY.startswith("gsk_PASTE"):
    print("⚠️  GROQ_API_KEY missing/invalid in .env")


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
    "schwarzschild": ["black", "hole", "radius", "relativity", "metric"],
    "black hole": ["event", "horizon", "schwarzschild", "singularity"],
    "einstein field": ["relativity", "tensor", "metric", "curvature"],
    "spacetime": ["metric", "curvature", "relativity", "manifold"],
    "geodesic": ["curvature", "spacetime", "metric"],
    "cosmology": ["universe", "expansion", "friedmann", "robertson"],
    "string theory": ["string", "brane", "extra", "dimension", "supersymmetry"],
    "quantum gravity": ["planck", "loop", "string", "graviton"],
}


TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]{1,}")


def tokenize(text):
    return TOKEN_RE.findall(text.lower())


def expand_query_tokens(query):
    tokens = tokenize(query)
    q_lower = query.lower()
    for phrase, syns in SYNONYMS.items():
        if phrase in q_lower:
            tokens.extend(syns)
    return tokens


# ------------------------------------------------------------------
# Retrieval (via Library, with diversity constraints)
# ------------------------------------------------------------------
def retrieve(query):
    tokens = expand_query_tokens(query)
    if not tokens:
        return []

    hits = LIBRARY.search(
        tokens,
        top_k=TOP_K,
        max_per_book=MAX_PER_BOOK,
        ensure_min_books=ENSURE_MIN_BOOKS,
        max_per_chapter=MAX_PER_CHAPTER,
    )

    results = []
    for score, cid in hits:
        rec = LIBRARY.chunks.get(cid)
        if not rec:
            continue
        book = LIBRARY.books.get(rec["book_id"])
        book_title = book.meta.get("title", rec["book_id"]) if book else rec["book_id"]
        book_author = book.meta.get("author", "") if book else ""
        results.append({
            "id": rec["id"],
            "text": rec["text"],
            "pages": f"{rec['page_start']}-{rec['page_end']}",
            "chapter": rec.get("chapter", ""),
            "book_id": rec["book_id"],
            "book_title": book_title,
            "book_author": book_author,
            "score": round(score, 3),
        })
    return results


# ------------------------------------------------------------------
# Prompt + Groq
# ------------------------------------------------------------------
SYSTEM_PROMPT = """You are Earick, a physics tutor with access to multiple textbooks:
- University Physics (Young & Freedman) — introductory level
- General Relativity (Hobson, Efstathiou & Lasenby) — advanced
- String Theory notes — graduate level

Your goal is to help students UNDERSTAND, not just look things up.

Rules:
1. Use the provided context as your PRIMARY source. Do not invent facts not present.
2. DO combine information across multiple passages and books. If one chunk gives a formula and another explains its meaning, merge them into one coherent answer.
3. DO reason: compare approaches, contrast intro vs. advanced perspectives, connect related concepts.
4. If the context covers only part of the question, answer that part confidently, then note what's missing.
5. If the question is off-topic (not physics), reply in one short sentence and stop.
6. Show the key formula(s) FIRST, then explain in 3-6 sentences.
7. Equations may be garbled in the source (PDF artifacts). Reconstruct them into clean LaTeX: \\( ... \\) inline, \\[ ... \\] display.
8. NEVER cite pages inline. Page citations are added separately.
9. Never invent numerical constants — use only values from context, or omit them.
10. Aim for clarity over completeness. A short precise answer beats a long vague one.
"""


def build_context(hits):
    if not hits:
        return "(no relevant passages found)"
    blocks = []
    total = 0
    for i, h in enumerate(hits, 1):
        block = (f"[{i}] ({h['book_title']}, pages {h['pages']}, {h['chapter']})\n"
                 f"{h['text']}")
        if total + len(block) > MAX_CONTEXT_CHARS:
            break
        blocks.append(block)
        total += len(block)
    return "\n\n".join(blocks)


def call_groq(user_query, hits):
    if not GROQ_API_KEY or GROQ_API_KEY.startswith("gsk_PASTE"):
        return "⚠️ Groq API key missing. Add GROQ_API_KEY to .env and restart."

    context = build_context(hits)
    user_prompt = (
        "Physics context from the textbooks:\n"
        "-----\n"
        f"{context}\n"
        "-----\n\n"
        f"Student question: {user_query}\n\n"
        "Answer as Earick (combine ideas across passages where useful):"
    )

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.4,
        "max_tokens": 800,
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

    hits = retrieve(message)
    reply = call_groq(message, hits)

    return jsonify({
        "reply": reply,
        "sources": [
            {
                "topic": h["chapter"],
                "pages": h["pages"],
                "book_title": h["book_title"],
                "book_author": h["book_author"],
                "book_id": h["book_id"],
                "score": h["score"],
            }
            for h in hits
        ],
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "books": len(LIBRARY.books),
        "chunks": len(LIBRARY.chunks),
        "vocab": len(LIBRARY.idf),
        "model": GROQ_MODEL,
        "groq_configured": bool(GROQ_API_KEY) and not GROQ_API_KEY.startswith("gsk_PASTE"),
    })


@app.route("/books")
def books_list():
    """Return the book catalog as JSON (used by the UI header)."""
    return jsonify([
        {
            "book_id": bid,
            "title": b.meta.get("title", ""),
            "author": b.meta.get("author", ""),
            "edition": b.meta.get("edition", ""),
            "year": b.meta.get("year", 0),
            "level": b.meta.get("level", ""),
            "subjects": b.meta.get("subjects", []),
            "chunks": b.chunk_count(),
        }
        for bid, b in LIBRARY.books.items()
    ])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
