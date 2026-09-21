"""
Earick - Physics RAG chatbot (multi-book, merged reasoning, self-aware)
Single merged reasoning mode + background dream mode + global lock.
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
from earick.lock_state import is_locked, lock, unlock, extract_wait_seconds

load_dotenv(ROOT / ".env")
load_dotenv("/etc/secrets/.env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()
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
print(f"   -> {n_chunks} total chunks, {n_vocab} vocab")

if not GROQ_API_KEY or GROQ_API_KEY.startswith("gsk_PASTE"):
    print("WARNING: GROQ_API_KEY missing")

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
                          ensure_min_books=ENSURE_MIN_BOOKS,
                          max_per_chapter=MAX_PER_CHAPTER)
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
        + "QUESTION: " + user_query
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
        body = e.read().decode("utf-8", errors="replace")[:600]
        if e.code == 429:
            wait = extract_wait_seconds(body)
            lock(wait, source="chat", reason="rate_limit",
                 message="Groq rate limit hit")
            return f"__LOCKED__:{wait}"
        return f"Groq HTTP {e.code}: {body[:200]}"
    except urllib.error.URLError as e:
        return f"Groq network error: {e.reason}"
    except Exception as e:
        return f"Groq request failed: {e}"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    # Global lock check
    status = is_locked()
    if status.get("locked"):
        return jsonify({
            "locked": True,
            "seconds_remaining": status.get("seconds_remaining", 0),
            "message": status.get("message", "Rate limited"),
        }), 429

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

    # Check for lock signal
    if reply.startswith("__LOCKED__:"):
        wait = int(reply.split(":", 1)[1])
        return jsonify({
            "locked": True,
            "seconds_remaining": wait,
            "message": "Rate limited by Groq",
        }), 429

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
        "model": GROQ_MODEL,
        "groq_configured": bool(GROQ_API_KEY) and not GROQ_API_KEY.startswith("gsk_PASTE"),
    })


@app.route("/lock-status")
def lock_status():
    return jsonify(is_locked())


@app.route("/unlock", methods=["POST"])
def unlock_now():
    unlock()
    return jsonify({"ok": True})


@app.route("/dream-status")
def dream_status():
    data_dir = ROOT / "data"
    state = {}
    if (data_dir / "dream_state.json").exists():
        try:
            state = json.loads((data_dir / "dream_state.json").read_text())
        except Exception:
            pass

    auto = False
    if dream_mode:
        try: auto = dream_mode.is_auto()
        except Exception: pass

    recent = []
    log_file = data_dir / "dream_log.md"
    if log_file.exists():
        text = log_file.read_text()
        for m in re.finditer(r"\*\*Topic:\*\*\s*(.+?)\s*\n", text):
            recent.append(m.group(1).strip())
        recent = recent[-10:]

    return jsonify({
        "auto": auto,
        "total_dreams": state.get("total_dreams", 0),
        "iter_today": state.get("iter_today", 0),
        "tokens_today": state.get("tokens_today", 0),
        "current_mood": state.get("current_mood", "unknown"),
        "dreams_since_consolidation": state.get("dreams_since_consolidation", 0),
        "recent_topics": recent,
        "files": {
            "self_awareness": (data_dir / "self_awareness.md").exists(),
            "dream_log": (data_dir / "dream_log.md").exists(),
        },
    })


@app.route("/dream-auto", methods=["POST"])
def dream_auto():
    if not dream_mode:
        return jsonify({"error": "dream mode not available"}), 500
    data = request.get_json(silent=True) or {}
    dream_mode.set_auto(bool(data.get("auto", False)))
    return jsonify({"auto": dream_mode.is_auto()})


@app.route("/dream-one", methods=["POST"])
def dream_one():
    if not dream_mode:
        return jsonify({"error": "dream mode not available"}), 500
    status = is_locked()
    if status.get("locked"):
        return jsonify({
            "error": "locked",
            "seconds_remaining": status.get("seconds_remaining", 0),
        }), 429
    try:
        ok = dream_mode._run_one_iteration(force=True)
        return jsonify({"ran": ok})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/books")
def books_list():
    return jsonify([{"book_id": bid, "title": b.meta.get("title", ""),
                     "author": b.meta.get("author", ""), "level": b.meta.get("level", ""),
                     "chunks": b.chunk_count()}
                    for bid, b in LIBRARY.books.items()])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 7860)), debug=False)
