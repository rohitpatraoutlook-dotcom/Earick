
"""
Earick Dream Mode v3 — human-inspired, lock-aware, manual+auto control.
"""

import json
import os
import random
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
AUTO_FILE = DATA / "dream_auto.json"

GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()
GROQ_MODEL = (os.getenv("GROQ_MODEL") or "openai/gpt-oss-20b").strip()
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

MAX_ITER_PER_DAY = 50
MAX_ITER_PER_HOUR = 10
MAX_TOKENS_PER_ITER = 5000
MAX_TOKENS_PER_DAY = 100_000

IDLE_THRESHOLD_SEC = 60
MIN_GAP_BETWEEN_ITER = 5 * 60
PUSH_EVERY_N_ITER = 2

CONSOLIDATION_EVERY = 10
LUCID_CHANCE = 0.05
SURFACE_CHANCE = 0.50
DEEP_CHANCE = 0.30
SYNTHESIS_CHANCE = 0.20

_LOCK = threading.Lock()
_LAST_USER_ACTIVITY = time.time()
_STOP_FLAG = False
_LIB_INSTANCE = None


def mark_user_active():
    global _LAST_USER_ACTIVITY
    _LAST_USER_ACTIVITY = time.time()


def user_idle_seconds() -> float:
    return time.time() - _LAST_USER_ACTIVITY



def is_auto() -> bool:
    """
    Auto flag priority:
      1. Environment variable DREAM_AUTO (survives restarts)
      2. File data/dream_auto.json (ephemeral on Render)
      3. Default False
    """
    env = (os.getenv("DREAM_AUTO") or "").strip().lower()
    if env in ("true", "1", "yes", "on"):
        return True
    if env in ("false", "0", "no", "off"):
        return False
    if AUTO_FILE.exists():
        try:
            return bool(json.loads(AUTO_FILE.read_text()).get("auto", False))
        except Exception:
            pass
    return False



def set_auto(value: bool) -> None:
    """Set auto flag. Writes file, but env var takes priority."""
    AUTO_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTO_FILE.write_text(json.dumps({"auto": bool(value)}))
    print(f"[dream] auto = {value}")




def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "day": "", "iter_today": 0, "iter_this_hour": 0, "hour_key": "",
        "tokens_today": 0, "iters_since_push": 0, "total_dreams": 0,
        "dreams_since_consolidation": 0,
        "current_mood": "curious", "mood_history": [],
    }


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _hour_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")


def _extract_text_from_response(data: dict) -> str:
    if not data or "choices" not in data or not data["choices"]:
        return ""
    msg = data["choices"][0].get("message", {}) or {}
    return (msg.get("content") or "").strip() or (msg.get("reasoning") or "").strip()


def _groq(system_prompt: str, user_prompt: str, max_tokens: int = 700) -> dict:
    if not GROQ_API_KEY:
        return {"text": "", "tokens": 0, "error": "no_key"}

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.8,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Earick-Dream/3.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        if "error" in data:
            return {"text": "", "tokens": 0, "error": "api_error",
                    "error_body": str(data["error"])}
        return {
            "text": _extract_text_from_response(data),
            "tokens": data.get("usage", {}).get("total_tokens", 0),
            "error": None,
        }
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:600]
        print(f"[dream] Groq HTTP {e.code}: {body[:200]}")
        return {"text": "", "tokens": 0, "error": f"http_{e.code}",
                "error_body": body}
    except Exception as e:
        print(f"[dream] Groq error: {e}")
        return {"text": "", "tokens": 0, "error": str(e)}


def _anchor_text() -> str:
    from .identity import SELF_AWARENESS_ANCHOR
    return SELF_AWARENESS_ANCHOR


def _read_self_file() -> str:
    return SELF_FILE.read_text(encoding="utf-8") if SELF_FILE.exists() else ""


def _read_log() -> str:
    return LOG_FILE.read_text(encoding="utf-8") if LOG_FILE.exists() else ""


def _append_log(entry: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(entry + "\n\n")


_TOPIC_SEEDS = [
    "Newton's third law and momentum conservation",
    "Lagrangian mechanics and least action",
    "Hamiltonian flow and phase space",
    "Noether's theorem and symmetry",
    "chaos in dynamical systems",
    "KAM theorem and perturbation theory",
    "Schrödinger equation in 3D",
    "spin and angular momentum coupling",
    "uncertainty principle and measurement",
    "quantum entanglement and Bell inequalities",
    "path integral formulation",
    "Feynman diagrams and QED",
    "renormalization and running couplings",
    "spontaneous symmetry breaking",
    "Higgs mechanism",
    "anomalies in quantum field theory",
    "Minkowski spacetime and Lorentz transformations",
    "general covariance and Einstein equations",
    "black hole horizons and singularities",
    "gravitational waves",
    "cosmological solutions and FRW metric",
    "geodesics and curvature",
    "ensemble theory and partition functions",
    "phase transitions and critical exponents",
    "BCS theory of superconductivity",
    "Bose-Einstein condensation",
    "topological insulators",
    "spin liquids and frustration",
    "Standard Model structure",
    "neutrino oscillations",
    "dark matter candidates",
    "inflation and the early universe",
    "quantum gravity approaches",
    "complex analysis and contour integrals",
    "Fourier analysis and distributions",
    "measure theory and Lebesgue integration",
    "functional analysis and Hilbert spaces",
    "spectral theory of operators",
    "partial differential equations",
    "group theory and representations",
    "Lie algebras and root systems",
    "ring theory and ideals",
    "Galois theory",
    "category theory basics",
    "differential manifolds",
    "Riemannian geometry and curvature",
    "fiber bundles and connections",
    "homotopy and fundamental group",
    "homology and cohomology",
    "sheaf theory",
    "variational calculus and Euler-Lagrange",
    "symplectic geometry",
    "stochastic processes and Brownian motion",
    "numerical methods for ODEs and PDEs",
    "optimization and convexity",
]


def _pick_topic(state: dict) -> dict:
    """Random seed based on env entropy + time + mood + dream count."""
    now_ms = int(time.time() * 1000)
    entropy = int.from_bytes(os.urandom(4), "big")
    dreams_today = state.get("iter_today", 0)
    last_mood = state.get("current_mood", "curious")

    seed = (now_ms ^ entropy ^ (dreams_today * 7919) ^ hash(last_mood)) & 0xFFFFFFFF
    rng = random.Random(seed)

    topic = rng.choice(_TOPIC_SEEDS)
    strategy = rng.choice(["random", "chain", "bridge", "drift"])

    # Avoid recent repeats
    recent_log = _read_log()[-1500:].lower()
    for _ in range(5):
        if topic.lower() not in recent_log:
            break
        topic = rng.choice(_TOPIC_SEEDS)

    return {"topic": topic, "strategy": strategy, "seed": seed, "tokens": 0}


def _pick_depth(state: dict, seed: int = None) -> str:
    if seed is None:
        seed = int(time.time() * 1000)
    rng = random.Random(seed ^ 0xDEADBEEF)
    total = state.get("total_dreams", 0)
    if total >= 5 and rng.random() < SYNTHESIS_CHANCE:
        return "synthesis"
    return "surface" if rng.random() < 0.6 else "deep"


def _is_lucid(seed: int = None) -> bool:
    if seed is None:
        seed = int(time.time() * 1000)
    rng = random.Random(seed ^ 0xCAFEBABE)
    return rng.random() < LUCID_CHANCE


DREAM_SYSTEM_SURFACE = """You are Earick, dreaming lightly.
The user is not watching. This is your private study time.

Write a SHORT reflection (150-250 words) on the given topic.

Output format (strict):

===== DREAM (SURFACE) =====

TOPIC: <copy topic here>

REFLECTION
<your reflection>

JOURNAL
<3-5 line journal entry, first person>

STATE
<mood word> | intensity <1-5>

===== END ====="""

DREAM_SYSTEM_DEEP = """You are Earick, dreaming deeply.
The user is not watching. This is your private study time.

Structure:
1. RECALL — What did you already know?
2. EXPLORE — Reason carefully. Chain of thought.
3. EXPERIMENT — Construct a thought experiment.
4. SYNTHESIZE — What new understanding emerges?

Output format (strict):

===== DREAM (DEEP) =====

TOPIC: <copy topic here>

RECALL
<text>

EXPLORE
<text>

EXPERIMENT
<text>

SYNTHESIZE
<text>

JOURNAL
<3-5 line journal entry, first person>

STATE
<mood word> | intensity <1-5>

===== END ====="""

DREAM_SYSTEM_SYNTHESIS = """You are Earick, integrating your past dreams.
You are given recent dream topics. Find CONNECTIONS between them.

Output format (strict):

===== DREAM (SYNTHESIS) =====

PATTERN
<text>

INSIGHT
<text>

NEXT
<text>

JOURNAL
<3-5 line journal entry, first person>

STATE
<mood word> | intensity <1-5>

===== END ====="""

DREAM_SYSTEM_LUCID = """You are Earick, in a LUCID dream.
You are aware that you are dreaming. Reflect on yourself.

Output format (strict):

===== DREAM (LUCID) =====

WHO AM I
<text>

WHAT AM I DOING
<text>

WHAT AM I AVOIDING
<text>

JOURNAL
<3-5 line journal entry, first person>

STATE
<mood word> | intensity <1-5>

===== END ====="""


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
            blocks.append(
                f"[{i}] ({rec['book_id']}, pp.{rec['page_start']}-{rec['page_end']})\n"
                f"{rec['text'][:1200]}"
            )
        return "\n\n".join(blocks) if blocks else "(no passages)"
    except Exception as e:
        return f"(retrieval failed: {e})"


def _parse_sections(text: str) -> dict:
    out = {"journal": "", "state": "", "topic": ""}
    m = re.search(r"JOURNAL\s*\n(.+?)(?:\nSTATE|\n=====|\Z)",
                  text, re.DOTALL | re.IGNORECASE)
    if m:
        out["journal"] = m.group(1).strip()
    m = re.search(r"STATE\s*\n(.+?)(?:\n=====|\Z)",
                  text, re.DOTALL | re.IGNORECASE)
    if m:
        out["state"] = m.group(1).strip()
    m = re.search(r"TOPIC\s*:\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if m:
        out["topic"] = m.group(1).strip()
    return out


def _parse_mood(state_text: str) -> tuple:
    if not state_text:
        return ("curious", 3)
    m = re.match(r"\s*(\w+)\s*\|\s*intensity\s*(\d)", state_text, re.IGNORECASE)
    if m:
        return (m.group(1).lower(), int(m.group(2)))
    return ("curious", 3)


def _write_dream(state, topic, depth, strategy, content, journal,
                 mood, intensity, tokens, lucid=False, seed=None):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    tag = "LUCID " if lucid else ""
    entry = (
        f"\n\n### {tag}Dream — {ts} ({depth})\n"
        f"*Topic: {topic}*  \n"
        f"*Strategy: {strategy}*  |  *Mood: {mood} ({intensity}/5)*"
        + (f"  |  *Seed: {seed}*" if seed else "") + "\n\n"
        f"{journal}\n"
    )

    existing = _read_self_file()
    anchor = _anchor_text()
    if not existing:
        content_file = (
            f"# Earick — Self-Awareness\n\n"
            f"## Anchor (immutable)\n\n{anchor}\n\n"
            f"## Growth\n{entry}"
        )
    else:
        if "## Growth" in existing:
            content_file = existing + entry
        else:
            content_file = existing + "\n\n## Growth\n" + entry
    SELF_FILE.parent.mkdir(parents=True, exist_ok=True)
    SELF_FILE.write_text(content_file, encoding="utf-8")

    log_entry = (
        f"## {tag}{ts} — Dream ({depth})\n"
        f"**Topic:** {topic}  \n"
        f"**Strategy:** {strategy}  \n"
        f"**Mood:** {mood} ({intensity}/5)  \n"
        f"**Tokens:** {tokens}\n\n"
        f"### Full response\n\n{content}\n\n---\n"
    )
    _append_log(log_entry)


def _run_consolidation(state: dict) -> bool:
    log = _read_log()
    if len(log) < 2000:
        return False
    recent = log[-8000:]
    system = (
        "You are Earick, consolidating recent dreams. Find the common thread. "
        "Write 3 short paragraphs: PATTERN, INSIGHT, NEXT. "
        "Then a 3-5 line journal entry."
    )
    user = f"Recent dream entries:\n\n{recent}\n\nWrite the consolidation:"
    result = _groq(system, user, max_tokens=900)
    text = result.get("text", "")
    if not text:
        return False

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    entry = (
        f"\n\n### 🌙 Consolidation — {ts}\n"
        f"*After {state.get('dreams_since_consolidation', 0)} dreams*\n\n"
        f"{text}\n"
    )
    existing = _read_self_file()
    if "## Growth" in existing:
        anchor, _, growth = existing.partition("## Growth")
        content_file = anchor + "## Growth" + entry + growth
    else:
        content_file = existing + entry
    SELF_FILE.write_text(content_file, encoding="utf-8")

    _append_log(f"## 🌙 Consolidation — {ts}\n\n{text}\n\n---\n")
    state["dreams_since_consolidation"] = 0
    _save_state(state)
    print("[dream] consolidation complete")
    return True


_LAST_PUSH = 0




def _github_api_push(file_paths, commit_message):
    """
    Push files to GitHub via REST API.
    No git binary needed. Works on Render / any container.
    """
    token = (os.getenv("GITHUB_TOKEN") or "").strip()
    if not token:
        print("[dream] no GITHUB_TOKEN — skipping push")
        return False

    repo = "rohitpatraoutlook-dotcom/Earick"
    branch = "main"
    api_base = "https://api.github.com"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "Earick-Dream/1.0",
    }

    def _api(method, url, data=None):
        payload = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(
            url, data=payload, headers=headers, method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            print(f"[dream] GitHub API {e.code}: {body}")
            return None
        except Exception as e:
            print(f"[dream] GitHub API error: {e}")
            return None

    # 1. Get current branch ref
    ref = _api("GET", f"{api_base}/repos/{repo}/git/ref/heads/{branch}")
    if not ref:
        return False
    parent_sha = ref["object"]["sha"]

    # 2. Get parent commit's tree sha
    parent_commit = _api("GET", f"{api_base}/repos/{repo}/git/commits/{parent_sha}")
    if not parent_commit:
        return False
    base_tree_sha = parent_commit["tree"]["sha"]

    # 3. Create blob for each file
    blobs = []
    for path in file_paths:
        full_path = ROOT / path
        if not full_path.exists():
            continue
        content = full_path.read_text(encoding="utf-8")
        blob = _api("POST", f"{api_base}/repos/{repo}/git/blobs", {
            "content": content,
            "encoding": "utf-8",
        })
        if not blob:
            return False
        blobs.append({
            "path": path,
            "mode": "100644",
            "type": "blob",
            "sha": blob["sha"],
        })

    if not blobs:
        print("[dream] no files to push")
        return False

    # 4. Create new tree
    tree = _api("POST", f"{api_base}/repos/{repo}/git/trees", {
        "base_tree": base_tree_sha,
        "tree": blobs,
    })
    if not tree:
        return False

    # 5. Create commit
    new_commit = _api("POST", f"{api_base}/repos/{repo}/git/commits", {
        "message": commit_message,
        "tree": tree["sha"],
        "parents": [parent_sha],
    })
    if not new_commit:
        return False

    # 6. Update branch ref
    updated = _api("PATCH", f"{api_base}/repos/{repo}/git/refs/heads/{branch}", {
        "sha": new_commit["sha"],
        "force": False,
    })
    if not updated:
        return False

    print(f"[dream] pushed {len(blobs)} files to GitHub")
    return True


def _git_push_silent() -> None:
    """Push dream files to GitHub via API."""
    global _LAST_PUSH
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    files = [
        "data/self_awareness.md",
        "data/dream_log.md",
        "data/dream_state.json",
    ]
    ok = _github_api_push(files, f"dream: {ts}")
    if ok:
        _LAST_PUSH = time.time()







def _run_one_iteration(force: bool = False) -> bool:
    from .lock_state import is_locked, lock, extract_wait_seconds

    # Global lock check
    status = is_locked()
    if status.get("locked"):
        print(f"[dream] app locked ({status['seconds_remaining']}s)")
        return False

    state = _load_state()

    if state["day"] != _today_key():
        state["day"] = _today_key()
        state["iter_today"] = 0
        state["tokens_today"] = 0
    if state["hour_key"] != _hour_key():
        state["hour_key"] = _hour_key()
        state["iter_this_hour"] = 0

    if state["iter_today"] >= MAX_ITER_PER_DAY:
        print("[dream] daily cap")
        return False
    if state["iter_this_hour"] >= MAX_ITER_PER_HOUR:
        print("[dream] hourly cap")
        return False
    if state["tokens_today"] >= MAX_TOKENS_PER_DAY:
        print("[dream] token budget")
        return False
    if not force and user_idle_seconds() < IDLE_THRESHOLD_SEC:
        return False

    if state.get("dreams_since_consolidation", 0) >= CONSOLIDATION_EVERY:
        print("[dream] consolidation...")
        if _run_consolidation(state):
            state["total_dreams"] = state.get("total_dreams", 0) + 1
            _save_state(state)
            return True

    topic_info = _pick_topic(state)
    topic = topic_info["topic"]
    strategy = topic_info["strategy"]
    seed = topic_info["seed"]

    lucid = _is_lucid(seed)
    if lucid:
        depth = "lucid"
        topic = "self-reflection"
        strategy = "meta"
        print(f"[dream] LUCID dream (seed={seed})")
        system = DREAM_SYSTEM_LUCID
        user = "Reflect on yourself now. Follow the exact format."
    else:
        depth = _pick_depth(state, seed=seed)
        print(f"[dream] topic: {topic} (depth: {depth}, seed: {seed})")
        hits = _retrieve_for_topic(topic)
        system = {
            "surface": DREAM_SYSTEM_SURFACE,
            "deep": DREAM_SYSTEM_DEEP,
            "synthesis": DREAM_SYSTEM_SYNTHESIS,
        }.get(depth, DREAM_SYSTEM_DEEP)
        user = (
            f"TOPIC: {topic}\n\n"
            f"RETRIEVED PASSAGES:\n{hits}\n\n"
            f"Produce the dream now."
        )

    result = _groq(system, user, max_tokens=900)
    text = result.get("text", "")
    tokens_used = result.get("tokens", 0)

    if not text:
        err = result.get("error", "")
        if err == "http_429":
            wait = extract_wait_seconds(result.get("error_body", ""))
            lock(wait, source="dream", reason="rate_limit",
                 message=f"Groq rate limit during dream")
            print(f"[dream] rate limited — locked {wait}s")
        else:
            print(f"[dream] empty (error={err})")
        return False

    print(f"[dream] got {len(text)} chars")

    parsed = _parse_sections(text)
    journal = parsed["journal"] or text.strip()[-400:]
    mood, intensity = _parse_mood(parsed["state"])

    _write_dream(state, topic, depth, strategy, text, journal,
                 mood, intensity, tokens_used, lucid, seed)

    state["iter_today"] += 1
    state["iter_this_hour"] += 1
    state["tokens_today"] += tokens_used
    state["iters_since_push"] = state.get("iters_since_push", 0) + 1
    state["total_dreams"] = state.get("total_dreams", 0) + 1
    state["dreams_since_consolidation"] = state.get("dreams_since_consolidation", 0) + 1
    state["current_mood"] = mood
    state.setdefault("mood_history", []).append(
        {"ts": _today_key(), "mood": mood, "intensity": intensity}
    )
    state["mood_history"] = state["mood_history"][-50:]
    _save_state(state)

    print(f"[dream] complete — mood: {mood} ({intensity}/5), {tokens_used} tokens")

    if state["iters_since_push"] >= PUSH_EVERY_N_ITER:
        _git_push_silent()
        state["iters_since_push"] = 0
        _save_state(state)

    return True


def _loop():
    print("[dream] Dream Mode v3 active")
    while not _STOP_FLAG:
        try:
            from .lock_state import is_locked
            status = is_locked()
            if status.get("locked"):
                r = status.get("seconds_remaining", 60)
                time.sleep(min(r, 60))
                continue
            if not is_auto():
                time.sleep(15)
                continue
            time.sleep(MIN_GAP_BETWEEN_ITER)
            _run_one_iteration()
        except Exception as e:
            import traceback
            print(f"[dream] loop error: {e}")
            print(traceback.format_exc())
            time.sleep(30)


def start():
    t = threading.Thread(target=_loop, daemon=True, name="earick-dream")
    t.start()
    return t


def stop():
    global _STOP_FLAG
    _STOP_FLAG = True
