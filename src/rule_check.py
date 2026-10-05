"""One-time SLAM rule check, run by the daily job: once the paper log has 75 settled flagged picks, re-run the
backtest for the current call rule (SLAM both teams good/great at 5v5, 1U one team great, else PASS) vs
SLAM = combined 5v5 above 4.20 (no PASS), plus this season's live games, and save it to data/rule_check.json. The dashboard shows that section only once the file exists.
Report only: the call rule doesn't change by itself.

  python3 src/rule_check.py          # does nothing until 75 settled picks, or if it already ran
  python3 src/rule_check.py --force  # run now regardless (for a manual re-check)
"""
import json
import os
import sys
from datetime import date

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
import dashboard
import grade
import paper
import paths

PICKS = 75
ALT_EV_SUM = 4.20
OUT = paths.data("rule_check.json")
RULES = ("current", "combined")


def rule_call(rule, r, flagged):
    """SLAM / 1U / PASS / AVOID under either rule. Both share the flag and the both-goalies-strong AVOID;
    the combined rule has no PASS (every other flagged game is SLAM or 1U by combined 5v5)."""
    c = dashboard.call(r, flagged)
    if rule == "current" or c == "AVOID":
        return c
    return "SLAM" if r.away_ev + r.home_ev > ALT_EV_SUM else "1U"


def settled_picks(d):
    d = d[~dashboard.retro(d)]
    return int((d.flag & d.result.notna()).sum())


def summary(res, prof):
    """{'n', 'w', 'l', 'p', 'over', 'units', 'roi'} for over bets (res: +1 over, -1 under, 0 push)."""
    res, prof = np.asarray(res), np.asarray(prof, float)
    w, l = int((res > 0).sum()), int((res < 0).sum())
    return {"n": len(res), "w": w, "l": l, "p": int((res == 0).sum()), "over": w / (w + l) if w + l else None,
            "units": round(float(prof.sum()), 2), "roi": float(prof.mean()) if len(res) else None}


def backtest():
    """2021-26 seasons with odds files (open + close), split in two halves, for each rule's SLAM and 1U."""
    import history as h
    import split_model as sm
    p = sm.walk_split(sm.load_split(), known_starters=False, record_detail=True)
    d = h.flagged(p).merge(h.lines(), on=["gameDate", "home", "away"])
    d = d[(d.season >= 2021) & d.both]
    out = {}
    for rule in RULES:
        calls = np.array([rule_call(rule, r, True) for r in d.itertuples()])
        for c in ("SLAM", "1U", "PASS"):
            x = d[calls == c]
            for when in ("open", "close"):
                b = h.bet_results(x, when)
                out[f"{rule}|{c}|{when}|all"] = summary(b.res, b.prof)
                for half, ss in (("2021-23", (2021, 2022)), ("2023-26", (2023, 2024, 2025))):
                    bb = b[b.season.isin(ss)]
                    out[f"{rule}|{c}|{when}|{half}"] = summary(bb.res, bb.prof)
    return out


def live(d):
    """This season's finished games: last pre-game call at its line (what the dashboard grades)."""
    g = dashboard.current(d[~dashboard.retro(d) & d.final_total.notna() & d.bet_total.notna()])
    g = g[g.away_ev.notna() & g.home_ev.notna()]
    out = {}
    for rule in RULES:
        calls = np.array([rule_call(rule, r, bool(r.flag)) for r in g.itertuples()])
        for c in ("SLAM", "1U", "PASS"):
            x = g[calls == c]
            res = np.sign(x.final_total - x.bet_total)
            prof = np.where(res == 0, 0.0, np.where(res > 0, grade.payout(x.bet_over), -1.0))
            out[f"{rule}|{c}"] = summary(res, prof)
    return out


def main(force=False):
    if os.path.exists(OUT) and not force:
        print(f"rule check already done ({OUT})")
        return
    d = paper.read_log()
    n = settled_picks(d)
    if n < PICKS and not force:
        print(f"rule check waits for {PICKS} settled picks ({n} so far)")
        return
    result = {"date": date.today().isoformat(), "picks": n, "alt_ev_sum": ALT_EV_SUM,
              "backtest": backtest(), "live": live(d)}
    with open(OUT, "w") as f:
        json.dump(result, f, indent=1)
    print(f"rule check saved to {OUT} at {n} settled picks")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
