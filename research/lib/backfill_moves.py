"""Rebuild data/moves/<day>.json (the dashboard's 'How the projection moved') from the git history of
data/paper_trades.csv: every daily-run commit holds each game's latest values (*_now columns), so replaying the
commits in order gives each run's snapshot. Games are frozen at puck drop (start_utc), as in the live run.

  python3 research/lib/backfill_moves.py 2026-10-13 2026-10-16      # first and last day (default: today)
"""
import io
import os as _os
import subprocess
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
from datetime import date

import pandas as pd

import moves
import paths

LOG = "data/paper_trades.csv"


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=paths.ROOT,
                          check=True).stdout


def main(first, last):
    days = [d.date().isoformat() for d in pd.date_range(first, last)]
    for day in days:
        if _os.path.exists(moves.path(day)):
            _os.remove(moves.path(day))
    since = (pd.Timestamp(first) - pd.Timedelta(days=1)).isoformat()
    commits = git("log", "--reverse", f"--since={since}", "--format=%H %cI", "--", LOG).split("\n")
    n = 0
    for line in filter(None, commits):
        sha, when = line.split()
        t = pd.Timestamp(when).tz_convert("America/New_York")
        try:
            log = pd.read_csv(io.StringIO(git("show", f"{sha}:{LOG}")))
        except Exception:
            continue
        if "away_gadj_now" not in log or "proj_now" not in log:
            continue
        for day in days:
            x = log[log.date == day]
            if x.empty:
                continue
            rows, started = [], set()
            for r in x.itertuples():
                key = f"{r.away}@{r.home}"
                if pd.notna(getattr(r, "start_utc", None)) and pd.Timestamp(r.start_utc) <= t.tz_convert("UTC"):
                    started.add(key)
                if pd.isna(r.proj_now):
                    continue
                rows.append({"away": r.away, "home": r.home, "proj": r.proj_now, "proj_away": r.proj_away_now, "proj_home": r.proj_home_now,
                             "away_goalie_now": r.away_goalie_now, "home_goalie_now": r.home_goalie_now,
                             "away_out": r.away_out if pd.notna(r.away_out) else None, "home_out": r.home_out if pd.notna(r.home_out) else None,
                             "away_gadj": r.away_gadj_now, "home_gadj": r.home_gadj_now,
                             "away_inj": r.away_inj_now if pd.notna(r.away_inj_now) else 0, "home_inj": r.home_inj_now if pd.notna(r.home_inj_now) else 0})
            if rows:
                at = pd.Timestamp(str(x.updated_at.dropna().max())) if x.updated_at.notna().any() else t
                moves.record(day, rows, started, at=at.strftime("%-I:%M %p"))
                n += 1
    print(f"{n} snapshots replayed; days: " + ", ".join(f"{d} ({len(moves.load(d))} games)" for d in days if _os.path.exists(moves.path(d))))


if __name__ == "__main__":
    a = _sys.argv[1:] or [date.today().isoformat()]
    main(a[0], a[-1])
