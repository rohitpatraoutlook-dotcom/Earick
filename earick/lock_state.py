"""
Global lock state for Earick.

When a rate limit hit occurs (chat or dream), the whole app locks
for the exact duration Groq specifies, then auto-resumes.
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK_FILE = ROOT / "data" / "lock_state.json"


def _load() -> dict:
    if LOCK_FILE.exists():
        try:
            return json.loads(LOCK_FILE.read_text())
        except Exception:
            pass
    return {"locked": False}


def _save(state: dict) -> None:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(json.dumps(state, indent=2))


def is_locked() -> dict:
    """Return current lock status. Auto-clears if expired."""
    state = _load()
    if not state.get("locked"):
        return {"locked": False}

    unlock_at = state.get("unlock_at", 0)
    now = time.time()

    if now >= unlock_at:
        _save({"locked": False})
        return {"locked": False, "just_unlocked": True}

    return {
        "locked": True,
        "unlock_at": unlock_at,
        "seconds_remaining": int(unlock_at - now),
        "seconds_total": state.get("seconds_total", 0),
        "reason": state.get("reason", "rate_limit"),
        "source": state.get("source", "unknown"),
        "message": state.get("message", ""),
    }


def lock(seconds: int, source: str = "unknown", reason: str = "rate_limit",
         message: str = "") -> dict:
    now = time.time()
    state = {
        "locked": True,
        "unlock_at": now + seconds,
        "locked_at": now,
        "seconds_total": seconds,
        "reason": reason,
        "source": source,
        "message": message,
        "locked_at_iso": datetime.now(timezone.utc).isoformat(),
    }
    _save(state)
    print(f"[lock] locked for {seconds}s (source={source})")
    return state


def unlock() -> None:
    _save({"locked": False})
    print("[lock] manually unlocked")


def extract_wait_seconds(error_body: str) -> int:
    """Parse Groq's 'try again in Xm Ys' / 'Xs' / 'Xh Ym' into seconds."""
    if not error_body:
        return 60

    m = re.search(r"try again in\s+(\d+)m(\d+(?:\.\d+)?)s", error_body, re.I)
    if m:
        return int(m.group(1)) * 60 + int(float(m.group(2))) + 5

    m = re.search(r"try again in\s+(\d+(?:\.\d+)?)s", error_body, re.I)
    if m:
        return int(float(m.group(1))) + 5

    m = re.search(r"try again in\s+(\d+)h\s*(\d+)m", error_body, re.I)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + 5

    m = re.search(r"try again in\s+(\d+)h", error_body, re.I)
    if m:
        return int(m.group(1)) * 3600 + 5

    m = re.search(r"try again in\s+(\d+)m\b", error_body, re.I)
    if m:
        return int(m.group(1)) * 60 + 5

    return 60
