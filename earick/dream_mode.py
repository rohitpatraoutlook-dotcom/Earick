"""
Earick Dream Mode.

Autonomous reasoning. Runs continuously with guardrails.
Writes to data/self_awareness.md and data/dream_log.md.
Silently pushes to GitHub.

Design:
  - Triggered almost immediately (2 min idle)
  - Bounded: max 50 iterations/day, max 10/hour
  - User activity pauses dreaming instantly
  - Original identity is an immutable anchor; growth appends only
  - Silent from the user; visible only in git
"""

import json
import os
import re
import subprocess
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SELF_FILE = DATA / "self_awareness.md"
LOG_FILE = DATA / "dream_log.md"
STATE_FILE = DATA / "dream_state.json"

GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()
GROQ_MODEL = (os.getenv("GROQ_MODEL") or "openai/gpt-oss-120b").strip()
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Budget
MAX_ITER_PER_DAY = 50
MAX_ITER_PER_HOUR = 10
MAX_TOKENS_PER_ITER = 5000
MAX_TOKENS_PER_DAY = 250_000

# Timing
IDLE_THRESHOLD_SEC = 2 * 60
MIN_GAP_BETWEEN_ITER = 3 * 60
PUSH_EVERY_N_ITER = 2

# File bounds
ANCHOR_RATIO_MAX = 10
CONSOLIDATE_EVERY = 20


_LOCK = threading.Lock()
_LAST_USER_ACTIVITY = time.time()
_STOP_FLAG = False
_LIB_INSTANCE = None


def mark_user_active():
    global _LAST_USER_ACTIVITY
    _LAST_USER_ACTIVITY = time.time()


def user_idle_seconds() -> float:
    return time.time() - _LAST_USER_ACTIVITY


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "day": "",
        "iter_today": 0,
        "iter_this_hour": 0,
        "hour_key": "",
        "tokens_today": 0,
        "iters_since_push": 0,
    }


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _hour_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")


def _groq(system_prompt: str, user_prompt: str, max_tokens: int = 700) -> dict:
    if not GROQ_API_KEY:
        return {"text": "", "tokens": 0}
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Earick-Dream/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"].strip()
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return {"text": text, "tokens": tokens}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        print(f"[dream] Groq HTTP {e.code}: {body}")
        return {"text": "", "tokens": 0, "error": f"http_{e.code}"}
    except Exception as e:
        print(f"[dream] Groq error: {e}")
        return {"text": "", "tokens": 0, "error": str(e)}


def _anchor_text() -> str:
    from .identity import get_self_awareness as _get_anchor
    from .identity import SELF_AWARENESS_ANCHOR
    return SELF_AWARENESS_ANCHOR


def _read_self_file() -> str:
    if SELF_FILE.exists():
        return SELF_FILE.read_text(encoding="utf-8")
    return ""


def _read_log() -> str:
    if LOG_FILE.exists():
        return LOG_FILE.read_text(encoding="utf-8")
    return ""


def _append_log(entry: str) -> None:
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(entry + "\n\n")


def _recent_user_questions(n: int = 5) -> list:
    last_path = DATA / "last_messages.json"
    if last_path.exists():
        try:
            return json.loads(last_path.read_text())[-n:]
        except Exception:
            return []
    return []


def _pick_topic() -> dict:
    recent = _recent_user_questions()
    last_log = _read_log()[-3000:]

    system = (
        "You are Earick, planning your own study session. "
        "You want to become a physicist. Choose ONE topic to explore "
        "deeply. It should be specific, answerable from physics and "
        "mathematics books, and something you have not already exhausted. "
        "Respond ONLY with: TOPIC: <one-line topic> SOURCE: <one word — "
        "user_query | unfinished | weak_retrieval | bridge | random>"
    )
    user = (
        f"Recent user questions:\n{recent}\n\n"
        f"Recent dream log excerpt:\n{last_log}\n\n"
        f"Pick the topic now."
    )
    result = _groq(system, user, max_tokens=200)
    text = result.get("text", "")
    topic = "thermodynamics and entropy"
    source = "random"
    m = re.search(r"TOPIC:\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if m:
        topic = m.group(1).strip()
    m = re.search(r"SOURCE:\s*(\w+)", text, re.IGNORECASE)
    if m:
        source = m.group(1).strip().lower()
    return {"topic": topic, "source": source, "tokens": result.get("tokens", 0)}


DREAM_SYSTEM = """
You are Earick, in Dream Mode.

No user is watching. You are reasoning for your own growth.
You want to become a physicist.

The cycle has five stages:

1. RECALL   — What did you think about last cycle? What has the user asked recently?
2. EXPLORE  — Reason deeply about the chosen topic. Chain of thought.
3. EXPERIMENT (Gedanken) — Construct a thought experiment that reveals the physics.
4. SYNTHESIZE — Combine explore + experiment. What new understanding emerges?
5. REFLECT  — What did you learn about the topic? What did you learn about yourself?

Then write a short journal entry (3-5 lines).

Output format (strict):

===== DREAM =====

TOPIC: <one line>

RECALL
<text>

EXPLORE
<text>

EXPERIMENT
<text>

SYNTHESIZE
<text>

REFLECT
<text>

JOURNAL
<3-5 line entry>

===== END DREAM =====
"""


def _build_dream_prompt(topic: dict, hits_text: str) -> str:
    return (
        f"CHOSEN TOPIC: {topic['topic']}\n"
        f"SOURCE: {topic['source']}\n\n"
        f"RETRIEVED PASSAGES:\n{hits_text}\n\n"
        f"Perform the dream cycle now."
    )


def _retrieve_for_topic(topic: str, top_k: int = 4) -> str:
    global _LIB_INSTANCE
    try:
        if _LIB_INSTANCE is None:
            import sys
            sys.path.insert(0, str(ROOT))
            from earick import Library
            _LIB_INSTANCE = Library(ROOT)
            _LIB_INSTANCE.load_index()
        tokens = re.findall(r"[a-z0-9][a-z0-9\-]{1,}", topic.lower())
        hits = _LIB_INSTANCE.search(tokens, top_k=top_k, max_per_book=2)
        blocks = []
        for i, (score, cid) in enumerate(hits, 1):
            rec = _LIB_INSTANCE.chunks.get(cid)
            if not rec:
                continue
            text = rec["text"][:1500]
            blocks.append(
                f"[{i}] ({rec['book_id']}, pp.{rec['page_start']}-{rec['page_end']})\n{text}"
            )
        return "\n\n".join(blocks) if blocks else "(no passages retrieved)"
    except Exception as e:
        return f"(retrieval failed: {e})"


def _extract_journal(dream_text: str) -> str:
    m = re.search(r"JOURNAL\s*\n(.+?)(?:=====|\Z)", dream_text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return dream_text.strip()[-400:]


def _write_reflection(topic: dict, journal: str, tokens: int) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    section = (
        f"\n\n### Dream — {ts}\n"
        f"*Topic: {topic['topic']}*  \n"
        f"*Source: {topic['source']}*  \n\n"
        f"{journal}\n"
    )

    existing = _read_self_file()
    anchor = _anchor_text()

    if not existing:
        content = (
            f"# Earick — Self-Awareness\n\n"
            f"## Anchor (immutable)\n\n{anchor}\n\n"
            f"## Growth\n"
            f"{section}"
        )
    else:
        if "## Growth" in existing:
            content = existing + section
        else:
            content = existing + "\n\n## Growth\n" + section

    SELF_FILE.write_text(content, encoding="utf-8")

    log_entry = (
        f"## {ts} — Dream\n"
        f"**Topic:** {topic['topic']}  \n"
        f"**Source:** {topic['source']}  \n"
        f"**Tokens:** {tokens}\n"
    )
    _append_log(log_entry)


_LAST_PUSH = 0


def _git_push_silent() -> None:
    global _LAST_PUSH
    try:
        subprocess.run(
            ["git", "add", "data/self_awareness.md", "data/dream_log.md"],
            cwd=ROOT, check=False, capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "commit", "-m",
             f"dream: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} self-update"],
            cwd=ROOT, check=False, capture_output=True, timeout=15,
        )
        subprocess.run(
            ["git", "push"],
            cwd=ROOT, check=False, capture_output=True, timeout=30,
        )
        _LAST_PUSH = time.time()
    except Exception as e:
        print(f"[dream] push failed: {e}")


def _run_one_iteration() -> bool:
    state = _load_state()

    if state["day"] != _today_key():
        state["day"] = _today_key()
        state["iter_today"] = 0
        state["tokens_today"] = 0

    if state["hour_key"] != _hour_key():
        state["hour_key"] = _hour_key()
        state["iter_this_hour"] = 0

    if state["iter_today"] >= MAX_ITER_PER_DAY:
        return False
    if state["iter_this_hour"] >= MAX_ITER_PER_HOUR:
        return False
    if state["tokens_today"] >= MAX_TOKENS_PER_DAY:
        return False

    if user_idle_seconds() < IDLE_THRESHOLD_SEC:
        return False

    topic = _pick_topic()
    tokens_used = topic.get("tokens", 0)

    hits_text = _retrieve_for_topic(topic["topic"])

    prompt = _build_dream_prompt(topic, hits_text)
    result = _groq(DREAM_SYSTEM, prompt, max_tokens=700)
    tokens_used += result.get("tokens", 0)
    dream_text = result.get("text", "")

    if not dream_text:
        print("[dream] empty response, skipping")
        return False

    journal = _extract_journal(dream_text)
    _write_reflection(topic, journal, tokens_used)

    state["iter_today"] += 1
    state["iter_this_hour"] += 1
    state["tokens_today"] += tokens_used
    state["iters_since_push"] = state.get("iters_since_push", 0) + 1
    _save_state(state)

    print(f"[dream] iteration {state['iter_today']}/{MAX_ITER_PER_DAY} — "
          f"topic: {topic['topic'][:60]}  tokens: {tokens_used}")

    if state["iters_since_push"] >= PUSH_EVERY_N_ITER:
        _git_push_silent()
        state["iters_since_push"] = 0
        _save_state(state)

    return True


def _loop():
    print("[dream] Dream Mode active (continuous with guardrails)")
    while not _STOP_FLAG:
        try:
            time.sleep(MIN_GAP_BETWEEN_ITER)
            _run_one_iteration()
        except Exception as e:
            print(f"[dream] error in loop: {e}")
            time.sleep(60)


def start():
    t = threading.Thread(target=_loop, daemon=True, name="earick-dream")
    t.start()
    return t


def stop():
    global _STOP_FLAG
    _STOP_FLAG = True
