"""
Dream Loop — run dream mode as a simple timed loop.

Usage:
    python scripts/dream_loop.py                    # default: 5 min gap
    python scripts/dream_loop.py --gap 180          # 3 min gap
    python scripts/dream_loop.py --max 20           # max 20 iterations
    python scripts/dream_loop.py --no-push          # don't push to git

Runs in foreground. Use tmux to keep it alive.
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from earick import dream_mode


def git_push():
    """Commit + push dream files."""
    try:
        subprocess.run(
            ["git", "add", "data/self_awareness.md", "data/dream_log.md",
             "data/dream_state.json"],
            cwd=ROOT, check=False, capture_output=True, timeout=10,
        )
        r = subprocess.run(
            ["git", "commit", "-m",
             f"dream: {datetime.now().strftime('%Y-%m-%d %H:%M')} self-update"],
            cwd=ROOT, check=False, capture_output=True, timeout=15,
        )
        # Check if there was anything to commit
        if b"nothing to commit" in r.stdout or r.returncode != 0:
            print("  (nothing to commit)")
            return
        subprocess.run(
            ["git", "push"],
            cwd=ROOT, check=False, capture_output=True, timeout=30,
        )
        print("  ✓ pushed to GitHub")
    except Exception as e:
        print(f"  git push error: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap", type=int, default=300,
                    help="Seconds between iterations (default 300)")
    ap.add_argument("--max", type=int, default=0,
                    help="Max iterations (0 = unlimited)")
    ap.add_argument("--no-push", action="store_true",
                    help="Skip git push")
    args = ap.parse_args()

    print("=" * 60)
    print("  DREAM LOOP")
    print("=" * 60)
    print(f"  Gap between iterations : {args.gap}s")
    print(f"  Max iterations         : {args.max or 'unlimited'}")
    print(f"  Auto-push to GitHub    : {not args.no_push}")
    print("=" * 60)
    print()

    # Force idle bypass
    dream_mode.IDLE_THRESHOLD_SEC = 0

    count = 0
    while True:
        count += 1
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{ts}] Iteration {count}")

        # Force huge idle
        dream_mode._LAST_USER_ACTIVITY = 0

        try:
            ok = dream_mode._run_one_iteration()
            print(f"  iteration_ran: {ok}")
        except Exception as e:
            print(f"  error: {e}")
            ok = False

        # Check file sizes
        for f in ["self_awareness.md", "dream_log.md"]:
            p = ROOT / "data" / f
            if p.exists():
                print(f"  {f}: {p.stat().st_size} bytes")
            else:
                print(f"  {f}: missing")

        # Push if we did something
        if ok and not args.no_push:
            git_push()

        if args.max and count >= args.max:
            print(f"\nReached max iterations ({args.max}). Stopping.")
            break

        print(f"  sleeping {args.gap}s...")
        time.sleep(args.gap)


if __name__ == "__main__":
    main()
