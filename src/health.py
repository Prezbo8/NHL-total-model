"""Data-source health: retry a failing source until it works, remember failures across runs, alert.

attempt() retries a source with growing waits (15 s, 45 s, 1.5 min, 3 min) inside a 15-minute budget per
run, so one dead site can't stall the run. If a source still fails, finish() writes data/.retry and the
workflow starts another run 5 minutes later, again and again until every source works (not after 11 PM
Eastern, when there are no games left to project). A source that fails 2 runs in a row opens a GitHub
issue (you get GitHub's email / app notification); the issue closes itself when the source recovers.

  python3 src/health.py alert    # open / close the GitHub issues from data/source_health.json
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import paths

STATE = paths.data("source_health.json")
RETRY_FLAG = paths.data(".retry")
WAITS = [15, 45, 90, 180]
BUDGET = 15 * 60          # total seconds of retry waiting per run
ALERT_AFTER = 2           # consecutive failed runs before an alert
ET = ZoneInfo("America/New_York")
_spent, _results = 0.0, {}


def attempt(name, fn, default=None, must=False, waits=None):
    """Run fn() until it works (or retries run out); record the outcome. must=True: an empty result is a failure."""
    global _spent
    err = None
    for i, wait in enumerate([0] + list(WAITS if waits is None else waits)):
        if wait:
            if _spent + wait > BUDGET:
                break
            print(f"  ({name}: retry {i} in {wait}s)", flush=True)
            time.sleep(wait); _spent += wait
        try:
            out = fn()
            if must and not out:
                raise ValueError("returned no data")
            _results[name] = None
            if i:
                print(f"  ({name}: worked on retry {i})")
            return out
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:150]}"
    _results[name] = err or "retry budget used up"
    print(f"::warning::{name} failed after retries: {_results[name]}")
    return default


def failed():
    return [k for k, v in _results.items() if v]


def finish():
    """Save this run's outcomes into data/source_health.json; set the retry flag if anything failed."""
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M %Z")
    for name, err in _results.items():
        s = state.setdefault(name, {"consecutive_failures": 0})
        if err:
            s.update(consecutive_failures=s["consecutive_failures"] + 1, last_error=err, last_failed=now)
        else:
            s.update(consecutive_failures=0, last_ok=now)
    with open(STATE, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    bad = failed()
    if bad and datetime.now(ET).hour < 23:
        open(RETRY_FLAG, "w").write(", ".join(bad) + "\n")
        print(f"(sources still failing: {', '.join(bad)} -> another run in 5 minutes)")
    elif os.path.exists(RETRY_FLAG):
        os.remove(RETRY_FLAG)
    return bad


def _gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def alert():
    """Open a GitHub issue per source failing ALERT_AFTER+ runs in a row; close it once the source works again."""
    if not os.path.exists(STATE):
        return
    state = json.load(open(STATE))
    r = _gh("issue", "list", "--label", "source-alert", "--state", "open", "--json", "number,title")
    open_issues = {i["title"]: i["number"] for i in json.loads(r.stdout or "[]")} if r.returncode == 0 else {}
    _gh("label", "create", "source-alert", "--color", "d93f0b", "--description", "A data source keeps failing")
    for name, s in state.items():
        title = f"Data source failing: {name}"
        if s.get("consecutive_failures", 0) >= ALERT_AFTER and title not in open_issues:
            body = (f"**{name}** has failed {s['consecutive_failures']} runs in a row (last at {s.get('last_failed')}).\n\n"
                    f"Last error: `{s.get('last_error')}`\n\nThe model keeps retrying every 5 minutes and uses its other "
                    f"sources meanwhile. This issue closes itself when {name} works again.")
            _gh("issue", "create", "--title", title, "--label", "source-alert", "--body", body)
            print(f"(alert opened: {title})")
        elif s.get("consecutive_failures", 0) == 0 and title in open_issues:
            _gh("issue", "close", str(open_issues[title]), "--comment", f"{name} is working again (since {s.get('last_ok')}).")
            print(f"(alert closed: {title})")


if __name__ == "__main__":
    alert() if sys.argv[1:] == ["alert"] else print(__doc__)
