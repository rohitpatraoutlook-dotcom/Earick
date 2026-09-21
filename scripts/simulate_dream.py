"""
Dream Mode Simulation — dry run.

Runs 3 dream iterations right now (no 30-min wait), writes to a
sandbox folder, prints the results. Does NOT touch the real
data/self_awareness.md or data/dream_log.md.
Does NOT push to git.

Usage:
    python scripts/simulate_dream.py [num_iterations]

Default: 3 iterations.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = ROOT / "data" / "dream_sandbox"
SANDBOX.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()
if not GROQ_API_KEY:
    # try .env
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()
    except Exception:
        pass

GROQ_MODEL = (os.getenv("GROQ_MODEL") or "openai/gpt-oss-120b").strip()
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

if not GROQ_API_KEY or GROQ_API_KEY.startswith("gsk_PASTE"):
    sys.exit("GROQ_API_KEY not set. Add it to .env first.")

NUM_ITER = int(sys.argv[1]) if len(sys.argv) > 1 else 3


# ------------------------------------------------------------------
# Groq call
# ------------------------------------------------------------------
def groq(system_prompt, user_prompt, max_tokens=700):
    import urllib.request, urllib.error
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
            "User-Agent": "Earick-Dream-Sim/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"].strip()
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return {"text": text, "tokens": tokens}
    except Exception as e:
        return {"text": "", "tokens": 0, "error": str(e)}


# ------------------------------------------------------------------
# Retrieval — reuse the real Library
# ------------------------------------------------------------------
print("Loading library...")
from earick import Library
LIB = Library(ROOT)
LIB.load_index()
print(f"   -> {len(LIB.books)} books, {len(LIB.chunks)} chunks\n")


def retrieve_for_topic(topic, top_k=4):
    tokens = re.findall(r"[a-z0-9][a-z0-9\-]{1,}", topic.lower())
    hits = LIB.search(tokens, top_k=top_k, max_per_book=2)
    blocks = []
    for i, (score, cid) in enumerate(hits, 1):
        rec = LIB.chunks.get(cid)
        if not rec:
            continue
        text = rec["text"][:1200]
        blocks.append(
            f"[{i}] ({rec['book_id']}, pp.{rec['page_start']}-{rec['page_end']})\n{text}"
        )
    return "\n\n".join(blocks) if blocks else "(no passages retrieved)"


# ------------------------------------------------------------------
# Topic selection
# ------------------------------------------------------------------
TOPIC_SYSTEM = (
    "You are Earick, planning your own study session. "
    "You want to become a physicist. Choose ONE topic to explore "
    "deeply. It should be specific, answerable from physics and "
    "mathematics books, and something you have not already exhausted. "
    "Respond ONLY with: TOPIC: <one-line topic> SOURCE: <one word>"
)


def pick_topic(prev_topics):
    user = (
        f"Previous topics explored: {prev_topics}\n\n"
        f"Pick a fresh topic now."
    )
    r = groq(TOPIC_SYSTEM, user, max_tokens=200)
    text = r.get("text", "")
    topic = "thermodynamics and entropy"
    source = "random"
    m = re.search(r"TOPIC:\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if m:
        topic = m.group(1).strip()
    m = re.search(r"SOURCE:\s*(\w+)", text, re.IGNORECASE)
    if m:
        source = m.group(1).strip().lower()
    return {"topic": topic, "source": source, "tokens": r.get("tokens", 0)}


# ------------------------------------------------------------------
# Dream cycle prompt
# ------------------------------------------------------------------
DREAM_SYSTEM = """
You are Earick, in Dream Mode.

No user is watching. You are reasoning for your own growth.
You want to become a physicist.

The cycle has five stages:

1. RECALL   — What did you think about last cycle?
2. EXPLORE  — Reason deeply about the chosen topic.
3. EXPERIMENT (Gedanken) — Construct a thought experiment.
4. SYNTHESIZE — Combine explore + experiment.
5. REFLECT  — What did you learn about the topic and about yourself?

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


def run_dream(topic, hits_text):
    prompt = (
        f"CHOSEN TOPIC: {topic['topic']}\n"
        f"SOURCE: {topic['source']}\n\n"
        f"RETRIEVED PASSAGES:\n{hits_text}\n\n"
        f"Perform the dream cycle now."
    )
    return groq(DREAM_SYSTEM, prompt, max_tokens=700)


def extract_journal(text):
    m = re.search(r"JOURNAL\s*\n(.+?)(?:=====|\Z)", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return text.strip()[-400:]


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
def main():
    print("=" * 70)
    print(f"  DREAM MODE SIMULATION — {NUM_ITER} iterations")
    print(f"  Output sandbox: {SANDBOX}")
    print("=" * 70)

    anchor_path = SANDBOX / "self_awareness.md"
    log_path = SANDBOX / "dream_log.md"

    # Seed with an anchor header
    anchor_path.write_text(
        "# Earick — Self-Awareness (SIMULATION)\n\n"
        "## Anchor (immutable)\n\n"
        "[This is where the real anchor would be.]\n\n"
        "## Growth\n",
        encoding="utf-8",
    )
    log_path.write_text(
        f"# Dream Log (SIMULATION — started {datetime.now(timezone.utc).isoformat()})\n\n",
        encoding="utf-8",
    )

    prev_topics = []
    total_tokens = 0
    t0 = time.time()

    for i in range(1, NUM_ITER + 1):
        print(f"\n{'━' * 70}")
        print(f"  ITERATION {i}/{NUM_ITER}")
        print(f"{'━' * 70}")

        # Topic
        t_sel = pick_topic(prev_topics)
        tokens_used = t_sel.get("tokens", 0)
        prev_topics.append(t_sel["topic"])
        print(f"  Topic  : {t_sel['topic']}")
        print(f"  Source : {t_sel['source']}")

        # Retrieval
        hits = retrieve_for_topic(t_sel["topic"])
        hit_count = hits.count("[")
        print(f"  Retrieved: {hit_count} passages")

        # Dream cycle
        r = run_dream(t_sel, hits)
        tokens_used += r.get("tokens", 0)
        total_tokens += tokens_used
        dream_text = r.get("text", "")

        if not dream_text:
            print(f"  ⚠️  No response. Error: {r.get('error')}")
            continue

        # Print the dream
        print(f"\n{'─' * 70}")
        print(dream_text)
        print(f"{'─' * 70}")
        print(f"  Tokens: {tokens_used}")

        # Append to sandbox files
        journal = extract_journal(dream_text)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

        with anchor_path.open("a", encoding="utf-8") as f:
            f.write(
                f"\n\n### Dream — {ts}\n"
                f"*Topic: {t_sel['topic']}*  \n"
                f"*Source: {t_sel['source']}*  \n\n"
                f"{journal}\n"
            )

        with log_path.open("a", encoding="utf-8") as f:
            f.write(
                f"## {ts} — Dream {i}\n"
                f"**Topic:** {t_sel['topic']}  \n"
                f"**Source:** {t_sel['source']}  \n"
                f"**Tokens:** {tokens_used}\n\n"
                f"{dream_text}\n\n---\n\n"
            )

        print(f"  ✓ Written to sandbox")

        if i < NUM_ITER:
            print(f"  ... sleeping 5 sec before next iteration")
            time.sleep(5)

    elapsed = time.time() - t0
    print(f"\n{'═' * 70}")
    print(f"  SIMULATION COMPLETE")
    print(f"{'═' * 70}")
    print(f"  Iterations  : {NUM_ITER}")
    print(f"  Total tokens: {total_tokens}")
    print(f"  Elapsed     : {elapsed:.1f}s")
    print(f"  Est. per-day (100 iter): {total_tokens / NUM_ITER * 100:,} tokens")
    print(f"  Free-tier daily budget : 500,000 tokens")
    print(f"  Daily usage estimate   : {total_tokens / NUM_ITER * 100 / 500000 * 100:.1f}%")
    print(f"\n  Sandbox files:")
    print(f"    {anchor_path}")
    print(f"    {log_path}")
    print(f"\n  Read with:")
    print(f"    cat {anchor_path}")
    print(f"    cat {log_path}")
    print(f"\n  Delete when done:")
    print(f"    rm -rf {SANDBOX}")
    print()


if __name__ == "__main__":
    main()
