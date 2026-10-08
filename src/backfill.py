"""One-off: add a past day's games to the paper log using ONLY pre-game information
(ratings from games before that day, that day's DailyFaceoff starters, opening lines).
Rows are marked as retroactive. Settled afterwards by paper.settle().

  python3 src/backfill.py 2026-10-01
"""
import json
import sys
import urllib.request
from datetime import date, timedelta

import numpy as np
import pandas as pd

import books
import goalies
import grade
import model as m
import odds
import paper
import speed
import split_model as sm
import trends


def backfill(day):
    d0 = date.fromisoformat(day)
    J = lambda u: json.load(urllib.request.urlopen(m.fetch(u)))
    games = sm.load_split()
    games = games[games.gameDate < int(day.replace("-", ""))]          # nothing from that day or later
    season = sm.season_of(d0)
    speed.refresh(season - 1)
    proj, project = sm.walk_split(games, known_starters=False, with_projector=True, live_season=season)
    cal = m.fit_calibration(proj[proj.season.between(2022, season - 1)])
    prev = proj[proj.season == season - 1]
    cutoff = np.quantile(np.r_[prev.lam_h, prev.lam_a], m.HIGH_Q)
    sched = [g for g in J(f"https://api-web.nhle.com/v1/score/{day}")["games"] if g["gameType"] == 2]
    tired = {g[s]["abbrev"] for g in J(f"https://api-web.nhle.com/v1/score/{d0 - timedelta(days=1)}")["games"]
             if g["gameType"] in (2, 3) and g.get("gameScheduleState", "OK") == "OK" for s in ("homeTeam", "awayTeam")}
    dfo = m.dailyfaceoff(day)
    st = pd.read_csv(goalies.STARTS)
    ids = {n.lower(): p for n, p in zip(st.name, st.playerId)}
    opens = {(grade.ABBR.get(r["home"], r["home"]), grade.ABBR.get(r["away"], r["away"])): r
             for r in odds.day_games(d0, 30)}
    names = books.book_names()
    shop = {}
    for r in books.day_all_books(d0):
        if r["book"] not in books.NOT_BOOKS:
            shop.setdefault((grade.ABBR.get(r["home"], r["home"]), grade.ABBR.get(r["away"], r["away"])), []).append(
                (names.get(r["book"], str(r["book"])), r["total"], int(r["over"]), int(r["under"])))
    rows = []
    for g in sched:
        h, a = g["homeTeam"]["abbrev"], g["awayTeam"]["abbrev"]
        cn = lambda t: (t.get("commonName") or t.get("name") or {}).get("default", "~~")
        def starter(team):
            k = next((k for k in dfo if k.endswith(m.norm_name(cn(team)))), None)
            name, status = dfo.get(k, (None, None))
            return (f"{name} ({status})", ids.get(str(name).lower())) if name else ("unknown", None)
        hg, hp = starter(g["homeTeam"])
        ag, ap = starter(g["awayTeam"])
        lh, la, det = project(h, a, hp, ap, h in tired, a in tired, detail=True, season=season)
        x, gap = lh + la, abs(lh - la)
        o = opens.get((h, a))
        flag = bool(lh >= cutoff and la >= cutoff and o is not None and o["total"] in (6.0, 6.5))
        best = None
        for bk, t, ov, un in shop.get((h, a), []):  # NOTE: per-book lines here are closing lines
            if t in (6.0, 6.5):
                p_win = m.p_from(cal, int(np.floor(t)) + 1, x, gap)
                p_push = m.p_from(cal, 6, x, gap) - m.p_from(cal, 7, x, gap) if t == 6 else 0.0
                ev = p_win * float(grade.payout(ov)) - (1 - p_win - p_push)
                if best is None or ev > best[0]:
                    best = (ev, bk, t, ov, un)
        rows.append({"date": day, "away": a, "home": h, "proj": round(x, 3), "proj_away": round(la, 3),
                     "proj_home": round(lh, 3), "cutoff": round(cutoff, 3), "flag": flag, "p7": round(m.p_from(cal, 7, x, gap), 4),
                     "away_goalie": ag, "home_goalie": hg,
                     "open_total": o["total"] if o else None, "open_over": o["over"] if o else None,
                     "bet_total": o["total"] if o else None, "bet_over": o["over"] if o else None,
                     "bet_under": o["under"] if o else None,
                     "best_book": best[1] if flag and best else None, "best_total": best[2] if flag and best else None,
                     "best_over": best[3] if flag and best else None, "best_under": best[4] if flag and best else None,
                     "logged_at": f"{day} (added retroactively Oct 2 from pre-game data; line = opening line)",
                     "flagged_at": None, "away_b2b": a in tired, "home_b2b": h in tired,
                     **trends.compute(sm.load_split(), day, h, a),
                     "away_goalie_now": ag, "home_goalie_now": hg, "updated_at": None,
                     **{f"{s}_{c}": round(v, 4) for s in ("away", "home") for c, v in det[s].items()}})
    log = pd.read_csv(paper.LOG)
    log = log[log.date != day]
    pd.concat([log, pd.DataFrame(rows)], ignore_index=True).reindex(columns=paper.COLS).to_csv(paper.LOG, index=False)
    print(f"backfilled {len(rows)} games for {day} ({sum(r['flag'] for r in rows)} flagged)")


if __name__ == "__main__":
    backfill(sys.argv[1])
