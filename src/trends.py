"""Recent-form and head-to-head context for a game (2020-21 onward, games before the game date only).

Tested on 2023-26 (3,947 games): these add almost nothing beyond the model's projection (last-10 7+
rate vs what the model missed: +0.003 correlation; head-to-head: +0.018). They're shown as context
on the dashboard, not used in the projection or the OVER flag.
"""
import numpy as np
import pandas as pd

BASE_7PLUS = 0.45   # league-typical share of games with 7+ goals
LEAN_EDGE = 0.08    # trend lean shown only when recent/H2H 7+ rates differ from typical by this much


def compute(games, day, home, away):
    """games: model.load_games()/split_model.load_split() frame; day: 'YYYY-MM-DD' (only earlier games used)."""
    before = games[games.gameDate < int(day.replace("-", ""))]
    out = {}
    for side, t in (("away", away), ("home", home)):
        tg = before[(before.home == t) | (before.away == t)].tail(10)
        out[f"{side}_l10_n"] = len(tg)
        out[f"{side}_l10_avg"] = round(float(tg.total.mean()), 2) if len(tg) else None
        out[f"{side}_l10_7"] = int((tg.total >= 7).sum()) if len(tg) else None
    h = before[((before.home == home) & (before.away == away)) | ((before.home == away) & (before.away == home))]
    out["h2h_n"] = len(h)
    out["h2h_avg"] = round(float(h.total.mean()), 2) if len(h) else None
    out["h2h_7"] = int((h.total >= 7).sum()) if len(h) else None
    out["h2h_last"] = "; ".join(
        f"{pd.Timestamp(str(r.gameDate)):%-m/%-d/%y} {r.away} {int(r.ag)}-{int(r.hg)} {r.home}"
        for r in h.sort_values("gameDate", ascending=False).head(3).itertuples()) or None
    out["trend_lean"] = lean(out)
    return out


def lean(t):
    """'OVER' / 'UNDER' / '' from the 7+ rates of both teams' last 10 games and the head-to-head history."""
    rates, weights = [], []
    for side in ("away", "home"):
        if t.get(f"{side}_l10_n"):
            rates.append(t[f"{side}_l10_7"] / t[f"{side}_l10_n"]); weights.append(t[f"{side}_l10_n"])
    if t.get("h2h_n", 0) >= 4:
        rates.append(t["h2h_7"] / t["h2h_n"]); weights.append(min(t["h2h_n"], 20))
    if not rates:
        return ""
    r = float(np.average(rates, weights=weights))
    return "OVER" if r >= BASE_7PLUS + LEAN_EDGE else "UNDER" if r <= BASE_7PLUS - LEAN_EDGE else ""
