"""Paper-trading log for the OVER flag.

src/model.py today  -> logs every game (flagged or not) with the line at the time;
                   runs every 2 hours 11 AM-9 PM ET so games whose line moves to 6/6.5 later get caught
python3 src/paper.py settle   -> fills in closing line + final score for finished games
python3 src/paper.py report   -> how the flagged overs are doing
"""
import json
import os
import sys
import urllib.request
from datetime import date

import numpy as np
import pandas as pd

import grade
from model import fetch
import odds
import paths

LOG = paths.data("paper_trades.csv")
COLS = ["date", "away", "home", "proj", "proj_away", "proj_home", "cutoff", "flag", "p7",
        "away_goalie", "home_goalie", "open_total", "open_over", "bet_total", "bet_over", "bet_under", "best_book", "best_total", "best_over", "best_under",
        "logged_at", "flagged_at",
        "close_total", "close_over", "close_under", "away_score", "home_score", "final_total",
        "result", "profit", "clv", "result_best", "profit_best",
        # context for the dashboard: back-to-backs, latest starters, projection breakdown
        "away_b2b", "home_b2b", "away_goalie_now", "home_goalie_now", "updated_at",
        "away_out", "home_out", "away_dtd", "home_dtd", "away_lineup", "home_lineup",
        # recent form + head-to-head context (not used in the projection)
        "away_l10_n", "away_l10_avg", "away_l10_7", "home_l10_n", "home_l10_avg", "home_l10_7",
        "h2h_n", "h2h_avg", "h2h_7", "h2h_last", "trend_lean",
        # goalie confirmation sources (confirm.py) and, after the game, who actually started (NHL box score)
        "game_id", "away_goalie_src", "home_goalie_src", "away_goalie_actual", "home_goalie_actual"] + [
        f"{s}_{c}" for s in ("away", "home") for c in ("ev", "pp", "oth", "gadj", "b2badj", "spd", "inj")]
BREAKDOWN = [f"{s}_{c}" for s in ("away", "home") for c in ("ev", "pp", "oth", "gadj", "b2badj", "spd", "inj")]
# latest run's numbers for games that haven't started (what the dashboard shows); the columns above
# stay as first logged, which is the paper bet
NOW_BASE = ["proj", "proj_away", "proj_home", "p7", "cutoff", "flag", "bet_total", "bet_over"] + BREAKDOWN
NOW = [f"{c}_now" for c in NOW_BASE]
COLS += NOW


def was_flagged_now(v):
    return str(v).strip().lower() in ("true", "1", "1.0")


def read_log():
    """Load the log with true/false columns as real booleans, however the CSV stored them
    ('True', 'False', '1.0', blank...). Everything that reads the log goes through here."""
    d = pd.read_csv(LOG) if os.path.exists(LOG) else pd.DataFrame(columns=COLS)
    for c in COLS:
        if c not in d:
            d[c] = None
    for c in ("flag", "away_b2b", "home_b2b"):
        d[c] = d[c].map(was_flagged_now).astype(bool)
    for c in ("result", "result_best", "best_book", "away_goalie_now", "home_goalie_now", "updated_at", "flagged_at",
              "away_goalie", "home_goalie", "away_out", "home_out", "away_dtd", "home_dtd", "away_lineup", "home_lineup",
              "h2h_last", "trend_lean", "away_goalie_src", "home_goalie_src", "away_goalie_actual", "home_goalie_actual"):
        d[c] = d[c].astype(object)
    return d


def log_games(rows):
    """Add today's games. A game already logged keeps its FIRST line, except that a game
    which wasn't flagged before but is flagged now gets flagged with the current line.
    Games that have already started are never logged or changed (no live lines)."""
    old = read_log()
    now = pd.Timestamp.now(tz="UTC")
    new = pd.DataFrame(rows)
    new = new.reindex(columns=list(dict.fromkeys(["start_utc"] + list(new.columns) + COLS)))  # any missing field -> empty
    new = new[pd.to_datetime(new.start_utc, utc=True) > now].drop(columns="start_utc")
    if new.empty:
        return 0, 0
    key = lambda d: d.date.astype(str) + d.away + d.home
    new["flag"] = new.flag.map(was_flagged_now).astype(bool)
    new["flagged_at"] = np.where(new.flag, new.logged_at, None)
    for c in NOW_BASE:
        new[f"{c}_now"] = new[c]
    added, upgraded = new, 0
    if len(old):
        old_keys = key(old)
        added = new[~key(new).isin(old_keys)]
        for c in ("away_b2b", "home_b2b", "flag") + tuple(NOW):
            old[c] = old[c].astype(object)  # allow assigning row values without pandas forcing a dtype
        for _, r in new[key(new).isin(old_keys)].iterrows():
            i = old.index[old_keys == key(pd.DataFrame([r])).iloc[0]][0]
            # always refresh: latest starters, back-to-backs (the bet itself never changes)
            for c in ("away_goalie_now", "home_goalie_now", "away_b2b", "home_b2b", "updated_at",
                      "away_out", "home_out", "away_dtd", "home_dtd", "away_lineup", "home_lineup",
                      "away_l10_n", "away_l10_avg", "away_l10_7", "home_l10_n", "home_l10_avg", "home_l10_7",
                      "h2h_n", "h2h_avg", "h2h_7", "h2h_last", "trend_lean", "game_id",
                      "away_goalie_src", "home_goalie_src") + tuple(NOW):
                old.loc[i, c] = r[c]
            if not was_flagged_now(old.at[i, "flag"]):  # best book is informational until a game is flagged
                for c in ("best_book", "best_total", "best_over", "best_under"):
                    old.loc[i, c] = r[c]
            if pd.isna(old.at[i, "away_ev"]):  # rows logged before breakdowns existed
                for c in BREAKDOWN:
                    old.loc[i, c] = r[c]
            if r.flag and not was_flagged_now(old.at[i, "flag"]):  # newly qualifies: flag it at today's current line
                for c in ("proj", "proj_away", "proj_home", "p7", "away_goalie", "home_goalie",
                          "bet_total", "bet_over", "bet_under", "best_book", "best_total", "best_over", "best_under",
                          "flag", "flagged_at") + tuple(BREAKDOWN):
                    old.loc[i, c] = r[c]
                upgraded += 1
    out = pd.concat([old, added], ignore_index=True) if len(old) else added
    out.reindex(columns=COLS).to_csv(LOG, index=False)
    return len(added), upgraded


STARTED = ("LIVE", "CRIT", "OFF", "FINAL")  # NHL game states once the puck has dropped


def record_actual_starters(d, days_back=7):
    """Fill {away,home}_goalie_actual (who really started, from the NHL box score) for games of the last week
    that have started and don't have it yet. The dashboard then shows the real starter from puck drop on,
    and it measures how often the predicted starter was right."""
    import confirm
    recent = (pd.Timestamp(date.today()) - pd.Timedelta(days=days_back)).strftime("%Y-%m-%d")
    need = d[(d.away_goalie_actual.isna() | d.home_goalie_actual.isna()) & (d.date >= recent)
             & (d.date <= date.today().isoformat())]
    for day in sorted(need.date.unique()):
        try:
            with urllib.request.urlopen(fetch(f"https://api-web.nhle.com/v1/score/{day}")) as f:
                ids = {(g["awayTeam"]["abbrev"], g["homeTeam"]["abbrev"]): g["id"] for g in json.load(f)["games"]
                       if g.get("gameState") in STARTED}
        except Exception as e:
            print(f"(couldn't read {day} games for actual starters: {e})")
            continue
        for i in need[need.date == day].index:
            gid = ids.get((d.at[i, "away"], d.at[i, "home"]))
            try:
                act = confirm.actual_starters(gid) if gid else {}
            except Exception as e:
                print(f"(couldn't read box score {gid}: {e})")
                continue
            for side in ("away", "home"):
                if side in act:
                    d.at[i, f"{side}_goalie_actual"] = act[side][0]


def update_actual_starters():
    """Record actual starters for games that have started (run after each projection run)."""
    d = read_log()
    before = d.away_goalie_actual.notna().sum() + d.home_goalie_actual.notna().sum()
    record_actual_starters(d, days_back=1)
    after = d.away_goalie_actual.notna().sum() + d.home_goalie_actual.notna().sum()
    if after != before:
        d.to_csv(LOG, index=False)
    print(f"(actual starters: {after - before} new)")


def settle():
    if not os.path.exists(LOG):
        print("no log yet")
        return
    d = read_log()
    todo = d[d.final_total.isna() & (pd.to_datetime(d.date) < pd.Timestamp(date.today()))]
    for day in sorted(todo.date.unique()):
        with urllib.request.urlopen(fetch(f"https://api-web.nhle.com/v1/score/{day}")) as f:
            scores = {(g["awayTeam"]["abbrev"], g["homeTeam"]["abbrev"]): g for g in json.load(f)["games"]}
        closing = {}
        for r in odds.day_games(date.fromisoformat(day), 15):
            closing[(grade.ABBR.get(r["away"], r["away"]), grade.ABBR.get(r["home"], r["home"]))] = r
        for i in todo[todo.date == day].index:
            k = (d.at[i, "away"], d.at[i, "home"])
            g = scores.get(k)
            if not g or g["gameState"] not in ("OFF", "FINAL"):
                continue
            a, h = g["awayTeam"]["score"], g["homeTeam"]["score"]  # NHL final score counts the shootout goal
            d.loc[i, ["away_score", "home_score", "final_total"]] = [a, h, a + h]
            if k in closing:
                c = closing[k]
                d.loc[i, ["close_total", "close_over", "close_under"]] = [c["total"], c["over"], c["under"]]
            if d.at[i, "flag"] and not pd.isna(d.at[i, "bet_total"]) and not pd.isna(d.at[i, "bet_over"]):
                bt, bo = d.at[i, "bet_total"], d.at[i, "bet_over"]
                res = "W" if a + h > bt else "P" if a + h == bt else "L"
                d.at[i, "result"] = res
                d.at[i, "profit"] = {"W": float(grade.payout(bo)), "P": 0.0, "L": -1.0}[res]
                if k in closing and not pd.isna(d.at[i, "bet_under"]):
                    d.at[i, "clv"] = clv(bt, bo, d.at[i, "bet_under"], c)
                if not pd.isna(d.at[i, "best_total"]):  # same bet at the best sportsbook price
                    bbt, bbo = d.at[i, "best_total"], d.at[i, "best_over"]
                    rb = "W" if a + h > bbt else "P" if a + h == bbt else "L"
                    d.at[i, "result_best"] = rb
                    d.at[i, "profit_best"] = {"W": float(grade.payout(bbo)), "P": 0.0, "L": -1.0}[rb]
    record_actual_starters(d)
    d.to_csv(LOG, index=False)
    import store  # mirror finals and paper results to Supabase (skipped when not configured)
    store.sync_log(read_log())
    print(f"settled through {todo.date.max() if len(todo) else 'n/a'}")


def clv(bet_total, bet_over, bet_under, c):
    """+1 if the market moved toward our OVER by close, -1 if away, 0 if unchanged."""
    if c["total"] != bet_total:
        return 1 if c["total"] > bet_total else -1
    fair = lambda o, u: grade.implied(o) / (grade.implied(o) + grade.implied(u))
    return int(np.sign(round(float(fair(c["over"], c["under"]) - fair(bet_over, bet_under)), 3)))


def report():
    if not os.path.exists(LOG):
        print("no log yet")
        return
    d = read_log()
    d = d[~d.logged_at.astype(str).str.contains("retroactively")]  # backfilled days don't count
    f = d[d.flag]
    s = f[f.result.notna()]
    print(f"games logged: {len(d)}   flagged overs: {len(f)}   settled: {len(s)}")
    if len(s):
        dec = s[s.result != "P"]
        print(f"record {(s.result == 'W').sum()}-{(s.result == 'L').sum()}-{(s.result == 'P').sum()}"
              f"   win {(dec.result == 'W').mean():.1%}   profit {s.profit.sum():+.2f}u   ROI {s.profit.mean():+.1%}")
        sb = s[s.profit_best.notna()]
        if len(sb):
            print(f"at the best sportsbook price: profit {sb.profit_best.sum():+.2f}u   ROI {sb.profit_best.mean():+.1%}"
                  f"   (consensus on the same bets: {sb.profit.mean():+.1%})")
        c = s.clv.dropna()
        if len(c):
            print(f"line moved toward our over by close: {(c > 0).mean():.0%} of {len(c)} (backtest: ~75%+ is good)")
        print("\nbacktest expectation (2020+ data): 53-55% wins, about break-even to +2% ROI, ~+2 pts more at the best book. Judge after ~50-75 flagged picks, not before.")
        print(s[["date", "away", "home", "bet_total", "bet_over", "best_book", "best_total", "best_over", "close_total",
                 "final_total", "result", "profit", "profit_best", "clv"]]
              .tail(15).to_string(index=False))


if __name__ == "__main__":
    {"settle": settle, "report": report}[sys.argv[1] if len(sys.argv) > 1 else "report"]()
