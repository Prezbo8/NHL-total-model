"""Run history in Supabase (same project as the MLB model; tables nhl_* from supabase/schema.sql).

Every model run saves one nhl_runs row plus one nhl_projections row per game that hasn't started,
so every hourly / pre-game projection is kept (the CSV log only keeps the first-logged bet and the
latest run). Games (finals, closing lines) and the paper bets are mirrored from the CSV log.

Needs SUPABASE_URL and SUPABASE_KEY (service key) in the environment (GitHub secrets). Without them
it does nothing, and a Supabase failure never stops a run: it prints a warning and the CSV still works.

  python3 src/store.py backfill     # copy the existing CSV log's games + paper bets (one-time)
"""
import json
import math
import os
import sys
import time
import urllib.request
import uuid
from types import SimpleNamespace

import pandas as pd

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")
BREAKDOWN = [f"{s}_{c}" for s in ("away", "home") for c in ("ev", "pp", "oth", "gadj", "b2badj", "spd", "inj")]
INT_COLS = {"open_over", "line_over", "line_under", "best_over", "best_under", "bet_over", "bet_under",
            "close_over", "close_under", "away_score", "home_score", "final_total", "game_id", "n_games", "n_flags"}


def enabled():
    return bool(URL and KEY)


def clean(row):
    """JSON-safe values: NaN/None -> null, numpy -> python, whole-number ints where the column is int."""
    out = {}
    for k, v in row.items():
        if v is None or (isinstance(v, float) and math.isnan(v)) or (not isinstance(v, (str, bool, dict)) and pd.isna(v)):
            out[k] = None
        elif hasattr(v, "item"):  # numpy scalar
            out[k] = v.item()
        else:
            out[k] = v
        if k in INT_COLS and isinstance(out[k], float):
            out[k] = int(round(out[k]))
    return out


def _send(table, rows, on_conflict=None, tries=3):
    """POST rows to a table (upsert when on_conflict is given). Raises after the last failed try."""
    if not rows:
        return
    q = f"?on_conflict={on_conflict}" if on_conflict else ""
    body = json.dumps([clean(r) for r in rows]).encode()
    req = urllib.request.Request(f"{URL}/rest/v1/{table}{q}", data=body, method="POST", headers={
        "apikey": KEY, **({"Authorization": f"Bearer {KEY}"} if KEY.startswith("eyJ") else {}),  # new sb_secret_ keys: apikey only
        "Content-Type": "application/json",
        "Prefer": ("resolution=merge-duplicates," if on_conflict else "") + "return=minimal"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30):
                return
        except Exception as e:
            err = e.read().decode()[:300] if hasattr(e, "read") else str(e)
            if i == tries - 1:
                raise RuntimeError(f"{table}: {err}")
            time.sleep(2 * (i + 1))


def safe(fn):
    """Never let Supabase break a run."""
    def wrap(*a, **k):
        if not enabled():
            print(f"(supabase not configured: {fn.__name__} skipped)")
            return None
        import health
        try:
            out = fn(*a, **k)
            health._results.setdefault("Supabase", None)
            return out
        except Exception as e:
            print(f"::warning::supabase {fn.__name__} failed (the CSV log is unaffected): {e}")
            health._results["Supabase"] = f"{type(e).__name__}: {str(e)[:150]}"
            return None
    return wrap


def projection_rows(run_id, rows, now=None):
    """nhl_projections rows for the games in a run that haven't started yet."""
    import dashboard  # the same SLAM / 1U / PASS / AVOID rule the page shows
    now = now or pd.Timestamp.now(tz="UTC")
    out = []
    for r in rows:
        if r.get("start_utc") and pd.Timestamp(r["start_utc"]) <= now:
            continue
        ns = SimpleNamespace(**r)
        out.append({"run_id": run_id, "game_date": r["date"], "away": r["away"], "home": r["home"],
                    "game_id": r.get("game_id"), "start_utc": r.get("start_utc"),
                    **{k: r.get(k) for k in ("proj", "proj_away", "proj_home", "p7", "cutoff", "open_total", "open_over",
                                             "best_book", "best_total", "best_over", "best_under", "away_goalie",
                                             "home_goalie", "away_b2b", "home_b2b", "away_out", "home_out",
                                             "away_dtd", "home_dtd")},
                    "flag": bool(r.get("flag")), "call": dashboard.call(ns, bool(r.get("flag"))),
                    "line_total": r.get("bet_total"), "line_over": r.get("bet_over"), "line_under": r.get("bet_under"),
                    **{k: r.get(k) for k in BREAKDOWN}})
    return out


@safe
def record_run(day, rows, sources=None, trigger=None):
    """Save one model run: nhl_runs + nhl_projections (not-started games) + nhl_games schedule rows."""
    run_id = str(uuid.uuid4())
    proj = projection_rows(run_id, rows)
    sha, repo, rid = (os.environ.get(k, "") for k in ("GITHUB_SHA", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    _send("nhl_runs", [{"run_id": run_id, "run_at": pd.Timestamp.now(tz="UTC").isoformat(), "game_date": day,
                        "trigger": trigger or os.environ.get("NHL_TRIGGER") or os.environ.get("GITHUB_EVENT_NAME") or "local",
                        "commit_sha": sha[:12] or None,
                        "gh_run_url": f"https://github.com/{repo}/actions/runs/{rid}" if rid else None,
                        "n_games": len(proj), "n_flags": sum(p["flag"] for p in proj), "sources": sources or {}}])
    _send("nhl_projections", proj)
    _send("nhl_games", [{"game_date": r["date"], "away": r["away"], "home": r["home"], "game_id": r.get("game_id"),
                         "start_utc": r.get("start_utc")} for r in rows], on_conflict="game_date,away,home")
    print(f"(supabase: run saved, {len(proj)} projections)")
    return run_id


@safe
def sync_log(d):
    """Mirror the CSV log's finals / closing lines (nhl_games) and paper bets (nhl_paper_bets)."""
    done = d[d.final_total.notna()]
    _send("nhl_games", [{"game_date": r.date, "away": r.away, "home": r.home, "away_score": r.away_score,
                         "home_score": r.home_score, "final_total": r.final_total, "close_total": r.close_total,
                         "close_over": r.close_over, "close_under": r.close_under,
                         "updated_at": pd.Timestamp.now(tz="UTC").isoformat()} for r in done.itertuples()],
          on_conflict="game_date,away,home")
    bets = d[d.flag.astype(bool)]
    _send("nhl_paper_bets", [{"game_date": r.date, "away": r.away, "home": r.home, "flagged_at": r.flagged_at,
                              "proj": r.proj, "p7": r.p7, "bet_total": r.bet_total, "bet_over": r.bet_over,
                              "bet_under": r.bet_under, "best_book": r.best_book, "best_total": r.best_total,
                              "best_over": r.best_over, "best_under": r.best_under, "result": r.result,
                              "profit": r.profit, "clv": r.clv, "result_best": r.result_best,
                              "profit_best": r.profit_best, "updated_at": pd.Timestamp.now(tz="UTC").isoformat()}
                             for r in bets.itertuples()], on_conflict="game_date,away,home")
    print(f"(supabase: {len(done)} finished games, {len(bets)} paper bets synced)")


if __name__ == "__main__":
    if sys.argv[1:] == ["backfill"]:
        import paper
        sync_log(paper.read_log())
        d = paper.read_log()
        record_games = [{"game_date": r.date, "away": r.away, "home": r.home} for r in d.itertuples()]
        if enabled():
            _send("nhl_games", record_games, on_conflict="game_date,away,home")
            print(f"(supabase: {len(record_games)} games backfilled)")
    else:
        print(__doc__)
