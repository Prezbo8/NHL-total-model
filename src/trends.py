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


FORM_WINDOWS = (("season", None), ("30", 30), ("14", 14), ("7", 7))  # calendar days before the day, like the MLB model


def team_form(proj, games, day, season, rk=None):
    """Over / under performance per team and window (dashboard 'Form' view, context only - not in the projection).
    Per game: goals scored / allowed vs the model's pre-game projection (walk-forward, so no hindsight) and vs
    expected goals (xG: finishing and goaltending). Tested Oct 13 2026 (research/studies/recent_form.py): goal
    over/underperformance doesn't carry over; xG form carries over only ~7%.
    rk (split_model.team_rankings with games): also the schedule in each window, judged by today's Total ranks like
    the rankings' Sched column: opp_d_rank / opp_d = the defenses faced (average Total Defense rank, 1 = best; how many
    more (+) / fewer (-) goals they allow than average), opp_o_rank / opp_o = the offenses faced; top10_d / top10_o =
    games against a top-10 defense / offense; opps = each opponent, newest first, as 'TEAM:D rank:O rank;...'."""
    x = proj[(proj.season == season) & (proj.gameDate < int(day.replace("-", "")))].merge(games[["gameId", "hg", "ag", "hxg", "axg"]], on="gameId")
    rows = pd.concat([
        pd.DataFrame({"team": x.home, "opp": x.away, "gameDate": x.gameDate, "gf": x.hg, "pgf": x.lam_h, "xgf": x.hxg, "ga": x.ag, "pga": x.lam_a, "xga": x.axg}),
        pd.DataFrame({"team": x.away, "opp": x.home, "gameDate": x.gameDate, "gf": x.ag, "pgf": x.lam_a, "xgf": x.axg, "ga": x.hg, "pga": x.lam_h, "xga": x.hxg})])
    sched = {}
    if rk is not None and len(rk):
        def pct(score, goals):  # Total score -> goals more (+) / fewer (-) than average (as split_model.team_rankings)
            slope, icpt = np.polyfit(score.values, goals.values, 1)
            return (icpt + slope * score.values) / goals.mean() - 1
        sched = {"opp_d": dict(zip(rk.team, pct(rk.score_def, rk.goalsA))), "opp_o": dict(zip(rk.team, pct(rk.score_off, rk.goalsF))),
                 "opp_d_rank": dict(zip(rk.team, rk.score_def.rank(method="min"))),
                 "opp_o_rank": dict(zip(rk.team, rk.score_off.rank(ascending=False, method="min")))}
        for c, v in sched.items():
            rows[c] = rows.opp.map(v)
    rows["date"] = pd.to_datetime(rows.gameDate.astype(str))
    rows = rows.sort_values("gameDate", kind="stable")
    out = []
    for win, days in FORM_WINDOWS:
        w = rows if days is None else rows[rows.date >= pd.Timestamp(day) - pd.Timedelta(days=days)]
        for t, g in w.groupby("team"):
            out.append({"window": win, "team": t, "gp": len(g),
                        "scoring": round((g.gf - g.pgf).mean(), 3), "allowing": round((g.pga - g.ga).mean(), 3),
                        "finishing": round((g.gf - g.xgf).mean(), 3), "goaltending": round((g.xga - g.ga).mean(), 3),
                        **{c: round(g[c].mean(), 4 if c in ("opp_d", "opp_o") else 1) for c in sched},
                        **({"top10_d": int((g.opp_d_rank <= 10).sum()), "top10_o": int((g.opp_o_rank <= 10).sum()),
                            "opps": ";".join(f"{o}:{d:.0f}:{f:.0f}" for o, d, f in   # newest first: team:D rank:O rank
                                             zip(g.opp[::-1], g.opp_d_rank[::-1], g.opp_o_rank[::-1]))} if sched else {})})
    f = pd.DataFrame(out)
    if len(f):
        f["net"] = (f.scoring + f.allowing).round(3)
    return f
