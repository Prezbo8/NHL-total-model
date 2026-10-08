"""Build docs/index.html (GitHub Pages dashboard) from data/paper_trades.csv.

  python3 src/dashboard.py
"""
import html
import os
from datetime import date

import numpy as np
import pandas as pd

import grade
import paper
import paths
import split_model
from teams import TEAMS

OUT = os.path.join(paths.DOCS_DIR, "index.html")

# backtest numbers (strict 2020-21+ data, frozen rule) from history.py / compare.py, Oct 2 2026
BACKTEST = [  # season, open bets, open ROI, close bets, close ROI  (calibrated goalies + team speed; Oct 3 2026)
    ("2021-22", 428, -1.8, 434, 0.2), ("2022-23", None, None, 229, 2.0), ("2023-24", 4, -50.0, 9, -25.0),
    ("2024-25", 44, 16.5, 44, 22.5), ("2025-26", 109, 9.1, 124, 5.7),
]

SCALE = 4.5  # projected-goal bars run 0 -> 4.5 goals


TIPS = {
    "Proj total": "Projected total goals for the game (away + home), from the model.",
    "P(7+)": "Model's chance of 7 or more total goals. 7+ wins an over 6.5 and an over 6 (exactly 6 pushes an over 6). NHL average ≈ 45%.",
    "Line": "Consensus total: opening line → line when logged (on results: logged line → closing line). ↑/↓ = which way it moved.",
    "Over price": "Consensus price for the over at the logged line (American odds: −120 = risk 120 to win 100; +110 = risk 100 to win 110).",
    "Best over": "Best-value over at 6 or 6.5 across DraftKings, FanDuel, BetRivers, BetMGM and Caesars, chosen with the model's probabilities (an over 6 can push).",
    "Total goals": "Final total goals (a shootout winner counts as one goal, as sportsbooks settle it).",
    "vs line": "Did the game go over or under the line that was logged before it started?",
    "Pick": "The call (SLAM / 1U / PASS / AVOID) and how it did at the logged consensus line. SLAM / 1U: W = went over (units at 1 unit risked). PASS / AVOID: ✓ = stayed under, ✗ = went over.",
    "Best book": "Same pick at the best sportsbook price (the 'Best over' book), in units.",
    "Team": "Team, away first then home.",
    "5v5": "Goals this team should score at full strength (5 skaters vs 5). Most of a team's goals come from here.",
    "PP": "Goals this team should score on the power play: how good its power play is, how bad the other team's penalty kill is, and how many penalties are expected.",
    "Oth": "Goals from everything else (4-on-4, overtime, empty nets, shorthanded goals, the shootout winner's goal). Same league-average number for every team, so it has no colors.",
    "Gl": "How the other team's goalie changes this team's scoring. + = weak goalie, more goals. − = strong goalie, fewer goals.",
    "B2B": "Tired legs: a team that played yesterday scores 8% less. A team whose opponent played yesterday scores 6.5% more.",
    "Spd": "How fast this team skates compared with the opponent (20+ mph bursts last season). Fast teams score a bit more and allow a bit less.",
    "Inj": "Injuries and scratches: this team's missing scorers (fewer goals) plus the other team's missing defenders (more goals).",
    "Rank tag": "Team rankings as of this game day, against a league-average opponent: OFF = goals scored (1 = most), DEF = goals its skaters allow (1 = fewest). Goalies and back-to-backs not included. Full tables under Team rankings.",
    "Rank OFF composite": "Total Offense score: the nine stats combined (z-scores weighted by how well each predicts future goals). 0 = league average, + = better. Rank 1 = best offense.",
    "Rank DEF composite": "Total Defense score: the nine stats allowed combined (weighted by how well each predicts future goals allowed). 0 = league average, + = better (allows less). Rank 1 = best defense.",
    "Rank OFF total": "Goals this team would score against a league-average opponent: 5v5 + power play + other situations, with team speed. Rank 1 = most.",
    "Rank OFF 5v5": "Its 5-on-5 goals against an average defense (xG/goals blend). Rank 1 = most.",
    "Rank OFF PP": "Its power-play goals against an average penalty kill: PP strength × how many penalties it draws. Rank 1 = most.",
    "Rank DEF total": "Goals its skaters would allow to a league-average offense (goalie rated separately). Rank 1 = fewest.",
    "Rank DEF 5v5": "5-on-5 goals it allows to an average offense. Rank 1 = fewest.",
    "Rank OFF sched": "Strength of schedule this season: the defenses this team has faced, judged by their Total Defense scores. #1 = toughest. % = how many more (+) or fewer (−) goals those defenses allow than average, so − means it has scored against good defenses.",
    "Rank DEF sched": "Strength of schedule this season: the offenses this team has faced, judged by their Total Offense scores. #1 = toughest. % = how many more (+) or fewer (−) goals those offenses score than average, so + means it has defended against good offenses.",
    "Rank adj": "Total rank after correcting every stat for the schedule behind it (last season's opponents count as ~10 games, this season's games 1 each). ↑/↓ = places gained/lost vs the raw rank. Display only: projections use the raw ratings.",
    "Rank DEF PK": "Power-play goals it allows: penalty-kill quality × how many penalties it takes. Rank 1 = fewest.",
    "Proj": "Projected goals = (5v5 + PP + Oth) × goalie × back-to-back × team speed × injury adjustments.",
    "HIGH": "Projected 3.09+ goals (top 40% of last season's team projections). An OVER FLAG needs both teams HIGH.",
    "Confirmed": "Starter confirmed (DailyFaceoff). Refreshed every run.",
    "Likely": "Starter expected but not confirmed yet (DailyFaceoff).",
    "Projected": "Starter not announced yet: DailyFaceoff's guess, or this team's usual recent starter.",
    "OVER FLAG": "The model's pick: both teams projected high-scoring and the line is 6 or 6.5. Bet the OVER at the 'Best over' book. These are the picks that count in the record.",
    "Lineups": "Projected lineup source (DailyFaceoff line combinations, checked against the official NHL roster). A reporter name = tonight's lineup; 'last game's lineup' = not updated for tonight yet. Regulars missing from the lineup are treated as out (scratch).",
    "Trends": "Each team's last 10 games: average total goals and how many went 7+ (over 6.5). Context only: tested on 2023-26, recent form adds almost nothing beyond the projection (the model already uses it).",
    "H2H": "Head-to-head since 2020-21: meetings, average total, how many went 7+, and the last 3 scores. Context only: tested on 2023-26, it adds very little beyond the projection.",
    "Lean": "Trend lean: OVER/UNDER when both teams' last-10 7+ rates and the head-to-head 7+ rate run clearly above/below the league's ~45%. Weak signal: it supports or questions the model's pick, it doesn't make one.",
    "SLAM": "Flagged over where both teams are good or great at 5-on-5. Went over 54% (opening line) / 57% (closing line) in 2021-26.",
    "1U": "Flagged over where one team is great at 5-on-5 (above 2.19) but the other isn't good. Went over 58% (opening and closing line) in 2021-26.",
    "PASS": "Flagged over, but neither team is great at 5-on-5 and they aren't both good. No bet: these went over only 45% in 2021-26.",
    "AVOID": "Not flagged, or flagged but both teams face strong goalies. These went over only 45-49% in 2021-26.",
    "Paper bet": "The paper-trading record's pick: flagged at the last model run before puck drop, graded at the closing consensus total and over price.",
    "B2B tag": "Played yesterday: the model cuts this team's scoring ~8% and raises its opponent's ~6.5%.",
}


# Breakdown tiers (scoring side; higher = better for an over): trash/bad/mid/good/great cutoffs.
# 5v5, PP, Gl, Spd = quintiles of 2024-26 team-games; B2B is discrete; Inj is a judgment call (live log only).
TIERS = {"ev": (1.83, 1.94, 2.05, 2.19), "pp": (0.46, 0.53, 0.59, 0.65), "gadj": (-0.052, -0.030, -0.014, 0.004),
         "spd": (-0.019, -0.006, 0.005, 0.018), "inj": (-0.02, -0.005, 0.005, 0.015)}
TIER_NAMES = ("trash", "bad", "mid", "good", "great")


def _tier_lines(stat, pct):
    f = (lambda v: f"{v * 100:+.1f}%") if pct else (lambda v: f"{v:.2f}")
    c = TIERS[stat]
    return (f"\n\nGreat: above {f(c[3])}\nGood: {f(c[2])} to {f(c[3])}\nMid: {f(c[1])} to {f(c[2])}"
            f"\nBad: {f(c[0])} to {f(c[1])}\nTrash: below {f(c[0])}")


for _col, _stat, _pct in (("5v5", "ev", False), ("PP", "pp", False), ("Gl", "gadj", True), ("Spd", "spd", True), ("Inj", "inj", True)):
    TIPS[_col] += _tier_lines(_stat, _pct)
TIPS["B2B"] += "\n\nGreat: +6.5% (opponent tired)\nMid: no back-to-back\nBad: −2% (both tired)\nTrash: −8% (this team tired)"


def tier(stat, v):
    """'great'/'good'/'mid'/'bad'/'trash' for a breakdown value, '' when not tiered or missing."""
    if pd.isna(v):
        return ""
    if stat == "b2badj":
        return "great" if v > 0.01 else "trash" if v < -0.05 else "bad" if v < -0.005 else "mid"
    if stat not in TIERS:
        return ""
    return TIER_NAMES[sum(v > c for c in TIERS[stat])]


def call(r, flagged):
    """'SLAM' / '1U' / 'PASS' / 'AVOID' for a game. Tested 2021-26 at 6/6.5 lines (over %, open / close):
    flagged + both teams good/great at 5v5 54% / 57%; flagged + one team great at 5v5 58% / 58.5%;
    other flagged (PASS) 45% / 45%; flagged but both teams facing strong goalies (Gl bad/trash) 46% / 45%;
    not flagged 47% / 49%."""
    if not flagged:
        return "AVOID"
    both = lambda stat, ts: all(tier(stat, getattr(r, f"{s}_{stat}", float("nan"))) in ts for s in ("away", "home"))
    if both("gadj", ("bad", "trash")):
        return "AVOID"
    if both("ev", ("good", "great")):
        return "SLAM"
    great = any(tier("ev", getattr(r, f"{s}_ev", float("nan"))) == "great" for s in ("away", "home"))
    return "1U" if great else "PASS"


def current(g):
    """The day's games as of the LATEST run: projection, P(7+), cutoff, flag, line, breakdown and the goalie
    they were built with (from the *_now columns; rows logged before those existed keep their logged values).
    The first-logged paper bet stays available as paper_flag / paper_line / first_call."""
    g = g.copy()
    g["paper_flag"], g["paper_line"] = g.flag.map(_is), g.bet_total
    g["first_call"] = [call(r, _is(r.flag)) for r in g.itertuples()]
    has = g.proj_now.notna() if "proj_now" in g else pd.Series(False, index=g.index)
    for c in paper.NOW_BASE:
        g[c] = g[c].astype(object)
        g.loc[has, c] = g.loc[has, f"{c}_now"]
    for s_ in ("away", "home"):
        g[f"{s_}_goalie"] = g[f"{s_}_goalie"].astype(object)
        g.loc[has, f"{s_}_goalie"] = g.loc[has, f"{s_}_goalie_now"]
    g["flag"] = g.flag.map(_is)
    for c in [c for c in paper.NOW_BASE if c != "flag"]:
        g[c] = pd.to_numeric(g[c], errors="coerce")
    return g


def call_result(r, flagged):
    """(call, outcome) for a finished game vs the logged line: SLAM/1U -> 'W'/'L'/'P' (over won / lost / push);
    PASS/AVOID -> 'W' when it stayed under (avoiding was right), 'L' when it went over, 'P' on a push; None without a line."""
    c = call(r, flagged)
    if pd.isna(r.bet_total) or pd.isna(r.final_total):
        return c, None
    over = r.final_total > r.bet_total
    if r.final_total == r.bet_total:
        return c, "P"
    return c, ("L" if over else "W") if c in ("PASS", "AVOID") else ("W" if over else "L")


GL_WORDS = {"great": "a weak goalie", "good": "a beatable goalie", "mid": "an average goalie",
            "bad": "a strong goalie", "trash": "a top goalie"}
CALL_HISTORY = {"SLAM": "Games like this went over 54% of the time at the opening line and 57% at the closing line in 2021-26.",
                "1U": "Games like this went over 58% of the time at both the opening and closing line in 2021-26.",
                "PASS": "Flagged games like this went over only 45% of the time in 2021-26.",
                "AVOID": "Games like this went over only 45-49% of the time in 2021-26."}


_RANKS = {}


def rank_lookup(day):
    """{team: rankings row} as of that game day (cached); {} when there are none."""
    if day not in _RANKS:
        rk = load_rankings(day)
        if rk is None and day == date.today().isoformat():
            rk = load_rankings()
        _RANKS[day] = {} if rk is None else {"_lg": rk[["gf", "gf_ev", "gf_pp"]].mean().to_dict(),
                                              **{x["team"]: x for _, x in rk.iterrows()}}
    return _RANKS[day]


def team_story(r, s_, x, o_, opp, rk, v):
    """Plain-English reasons behind one team's projected goals: how far from an average team, then what
    pushes it up and what holds it back (matchups and adjustments, in goals), biggest first."""
    proj = r.proj_away if s_ == "away" else r.proj_home
    ev, pp, oth = v(s_, "ev"), v(s_, "pp"), v(s_, "oth")
    have = x in rk and opp in rk and "r_gf_ev" in rk[x]
    reasons = []  # (goals effect, label, why)
    if have:
        t, o, lg = rk[x], rk[opp], rk["_lg"]
        reasons.append((ev - lg["gf_ev"], "5-on-5 matchup", f"its attack ranks #{t['r_gf_ev']} of 32, {opp}'s defense #{o['r_ga_ev']}"))
        reasons.append((pp - lg["gf_pp"], "power play", f"its power play ranks #{t['r_gf_pp']}, {opp}'s penalty kill and penalty habits #{o['r_ga_pp']}"))
    run = ev + pp + oth
    opp_goalie = e(goalie_parts(getattr(r, f"{o_}_goalie", ""))[0])
    for k in ("gadj", "b2badj", "spd", "inj"):
        pct = v(s_, k)
        if pd.isna(pct) or abs(pct) < 0.0005:
            continue
        eff, run = run * pct, run * (1 + pct)
        if k == "gadj":
            label, why = f"{opp_goalie} in goal", GL_WORDS.get(tier("gadj", pct), "a goalie")
        elif k == "b2badj":
            label = "back-to-back"
            why = "it played yesterday" if pct < -0.05 else f"{opp} played yesterday" if pct > 0.01 else "both teams played yesterday"
        elif k == "spd":
            label, why = "team speed", f"it skates {'faster' if pct > 0 else 'slower'} than {opp}"
        else:
            label, why = "injuries", "missing players on both teams, net"
        reasons.append((eff, label, f"{why}, {pct * 100:+.1f}%"))
    fmt = lambda z: f"{z[1]} <b>{z[0]:+.2f}</b> ({z[2]})"
    up = sorted([z for z in reasons if z[0] >= 0.01], key=lambda z: -z[0])
    down = sorted([z for z in reasons if z[0] <= -0.01], key=lambda z: z[0])
    if have:
        diff = proj - rk["_lg"]["gf"]
        head = (f"<b>{x} {proj:.2f}</b>: {abs(diff):.2f} goals {'above' if diff >= 0 else 'below'} what an average team "
                f"would score ({rk['_lg']['gf']:.2f}).")
    else:
        head = f"<b>{x} {proj:.2f}</b>."
    parts = [head]
    if up:
        parts.append("Pushing it up: " + "; ".join(fmt(z) for z in up) + ".")
    if down:
        parts.append("Holding it back: " + "; ".join(fmt(z) for z in down) + ".")
    if not up and not down:
        parts.append("Nothing moves it more than a few hundredths of a goal: an average matchup.")
    return " ".join(parts)


def reasoning(r, flagged):
    """6-9 plain-English sentences behind the game's call, built from its logged numbers."""
    c = call(r, flagged)
    a, h = r.away, r.home
    v = lambda s_, k: getattr(r, f"{s_}_{k}", float("nan"))
    if pd.isna(v("away", "ev")):
        return f"{c}: breakdown not available for this game."
    S = (("away", a), ("home", h))
    proj = {"away": r.proj_away, "home": r.proj_home}
    if pd.isna(r.cutoff):
        return f"{c}: this game was logged without a high-scoring cutoff, so there's no full reasoning for it."
    hot = {s_: proj[s_] >= r.cutoff for s_ in proj}
    t, final = r.bet_total, not pd.isna(r.final_total)
    ev_t = {s_: tier("ev", v(s_, "ev")) for s_, _ in S}
    gl_t = {s_: tier("gadj", v(s_, "gadj")) for s_, _ in S}
    strong = [x for s_, x in S if gl_t[s_] in ("bad", "trash")]
    both_proj = f"{a} {proj['away']:.2f}, {h} {proj['home']:.2f}; cutoff {r.cutoff:.2f}"
    out = []
    # 1. the call and the rule behind it
    if c == "SLAM":
        out.append(f"<b>🔨 SLAM:</b> both teams project as high-scoring ({both_proj}), the line is {line(t)}, "
                   "and both are good or better at 5-on-5, the strongest over spot the model has.")
    elif c == "1U":
        big = [x for s_, x in S if ev_t[s_] == "great"][0]
        (s1, other), = [(s_, x) for s_, x in S if x != big]
        out.append(f"<b>1U:</b> both teams project as high-scoring ({both_proj}) and the line is {line(t)}; "
                   f"{big} is great at 5-on-5 and can carry the over, but {other} is only {ev_t[s1]}, so it's an over but not a slam.")
    elif c == "PASS":
        out.append(f"<b>PASS:</b> both teams project as high-scoring ({both_proj}) and the line is {line(t)}, "
                   f"but neither is great at 5-on-5 ({a} {ev_t['away']}, {h} {ev_t['home']}) and they aren't both good, "
                   "so there's no team to carry the over.")
    elif flagged:
        out.append(f"<b>AVOID:</b> both teams project as high-scoring ({both_proj}), but both face a strong goalie, "
                   "and overs in that spot went only 45-46% in 2021-26.")
    else:
        why = []
        low = [(s_, x) for s_, x in S if not hot[s_]]
        if low:
            why.append(f"{' and '.join(x for _, x in low)} project{'s' if len(low) == 1 else ''} under the {r.cutoff:.2f}-goal "
                       f"high-scoring cutoff ({', '.join(f'{x} {proj[s_]:.2f}' for s_, x in low)})")
        if pd.isna(t):
            why.append("no line was posted")
        elif t not in (6.0, 6.5):
            why.append(f"the line is {line(t)}, and only 6 and 6.5 qualify")
        out.append(f"<b>AVOID:</b> {'; '.join(why) or 'it does not meet the over rule'}.")
        if len(low) == 1 and r.proj >= 6.0:
            (s0, x0), carry = low[0], [x for s_, x in S if hot[s_]][0]
            gap = r.cutoff - proj[s0]
            out.append(f"{x0} just misses the cutoff (by {gap:.2f}), and the rule needs both teams over it, so the "
                       f"{r.proj:.2f} total isn't enough on its own." if gap < 0.1 else
                       f"The {r.proj:.2f} total looks high, but most of it comes from {carry}; the over rule needs both teams scoring.")
    # 2. 5-on-5 and power play
    ev = [f"{x} is {ev_t[s_]} ({v(s_, 'ev'):.2f})" for s_, x in S]
    pp = [f"{x} is {tier('pp', v(s_, 'pp'))} ({v(s_, 'pp'):.2f})" for s_, x in S]
    out.append(f"At 5-on-5, {ev[0]} and {ev[1]}; on the power play, {pp[0]} and {pp[1]}.")
    # 3. goalies faced (the goalie the projection was built with)
    gl = []
    for s_, x in S:
        opp = "home" if s_ == "away" else "away"
        nm, _ = goalie_parts(getattr(r, f"{opp}_goalie", ""))
        now = getattr(r, f"{opp}_goalie_now", None)
        now_nm = goalie_parts(now)[0] if isinstance(now, str) else nm
        who = e(nm) if nm != "unknown" else "an unknown starter"
        gl.append((f"{x} faces {who} (no goalie rating)" if pd.isna(v(s_, "gadj")) else
                   f"{x} faces {who}, {GL_WORDS.get(gl_t[s_], 'a goalie')} ({v(s_, 'gadj') * 100:+.1f}%)")
                  + (f", but the expected starter later changed to {e(now_nm)}, so this part is out of date"
                     if now_nm not in (nm, "unknown") and nm != "unknown" else ""))
    sent = "; ".join(gl) + "."
    if c in ("SLAM", "1U") and len(strong) == 1:
        sent += f" Only {strong[0]} faces a strong goalie, so the two-strong-goalies avoid rule doesn't apply."
    unconf = sum("confirmed" not in str(getattr(r, f"{s_}_goalie_now", "")).lower().replace("unconfirmed", "") for s_, _ in S)
    if unconf and not final:
        sent += " Starters aren't confirmed yet, so this can change."
    out.append(sent)
    # 4. the other adjustments, only when they matter
    extra = []
    both_tired = all(-0.05 < v(s_, "b2badj") < -0.005 for s_, _ in S)
    if both_tired:
        extra.append(f"both teams played yesterday ({v('away', 'b2badj') * 100:+.0f}% each)")
    for s_, x in S:
        b = v(s_, "b2badj")
        if both_tired:
            pass
        elif b < -0.05:
            extra.append(f"{x} played yesterday ({b * 100:+.0f}%)")
        elif b > 0.01:
            extra.append(f"{x}'s opponent played yesterday ({b * 100:+.1f}%)")
        elif b < -0.005:
            extra.append(f"both teams played yesterday ({x} {b * 100:+.0f}%)")
        if not pd.isna(v(s_, "spd")) and abs(v(s_, "spd")) >= 0.02:
            extra.append(f"{x}'s team speed {'adds' if v(s_, 'spd') > 0 else 'costs'} {abs(v(s_, 'spd')) * 100:.1f}%")
        if not pd.isna(v(s_, "inj")) and abs(v(s_, "inj")) >= 0.015:
            extra.append(f"injuries {'help' if v(s_, 'inj') > 0 else 'cost'} {x} {abs(v(s_, 'inj')) * 100:.1f}%")
    if extra:
        out.append("Other factors: " + "; ".join(extra) + ".")
    # 5. why each team projects where it does (vs an average team), biggest reasons first
    rk = rank_lookup(r.date)
    for (s_, x), (o_, opp) in ((S[0], S[1]), (S[1], S[0])):
        out.append(f"<span class='tt'>{team_story(r, s_, x, o_, opp, rk, v)}</span>")
    # 6. projection and line
    mv = ""
    if not pd.isna(t) and not pd.isna(r.open_total) and r.open_total != t:
        mv = f" The line moved from {line(r.open_total)} to {line(t)}" + (", toward the over." if t > r.open_total else ", toward the under.")
    out.append(f"The model projects {r.proj:.2f} total goals" + ("" if pd.isna(t) else f" against a {line(t)} line")
               + f", with a {r.p7:.0%} chance of 7 or more (a typical game is about 45%)." + mv)
    # parts that don't multiply out to the projection (games logged before breakdowns were recorded)
    def parts(s_):
        z = lambda k: 0.0 if pd.isna(v(s_, k)) else v(s_, k)
        return (z("ev") + z("pp") + z("oth")) * (1 + z("gadj")) * (1 + z("b2badj")) * (1 + z("spd")) * (1 + z("inj"))
    if any(abs(parts(s_) - proj[s_]) > 0.02 for s_, _ in S):
        out.append("Note: this game's breakdown was recorded on a later run than its projection, so the parts don't add up exactly.")
    # 7. track record and result
    out.append(CALL_HISTORY[c])
    if final and not pd.isna(t):
        went = "went over" if r.final_total > t else "stayed under" if r.final_total < t else "pushed"
        right = (r.final_total > t) if c not in ("PASS", "AVOID") else (r.final_total < t)
        score = "" if pd.isna(r.away_score) or pd.isna(r.home_score) else f" ({a} {int(r.away_score)}, {h} {int(r.home_score)})"
        out.append(f"Final: {int(r.final_total)} goals{score}, so it {went} {line(t)}"
                   + ("" if r.final_total == t else f" and the call was {'right' if right else 'wrong'}") + ".")
    return " ".join(out)


def tip(label, text=None, cls=""):
    """Label with an explanation that pops up on hover (or tap on a phone)."""
    t = text or TIPS.get(label, "")
    return f"<span class='tip {cls}' tabindex='0' data-tip='{e(t)}'>{label}</span>" if t else label


def e(x):
    return html.escape("" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x))


def price(x):
    return "" if pd.isna(x) else f"{int(x):+d}"


def start_time(v):
    """'7:00 PM' (Eastern) from the log's start_utc; '' when it's missing."""
    if pd.isna(v) or not str(v).strip():
        return ""
    return f"{pd.Timestamp(v).tz_convert('America/New_York'):%-I:%M %p}"


def line(t):
    return "" if pd.isna(t) else f"{t:g}"


def pct(x, d=1):
    return "–" if x is None or pd.isna(x) else f"{x:+.{d}f}%"


def book(b):
    return e(str(b).replace(" NJ", "").replace("FanDuel", "FD").replace("BetRivers", "BetRiv"))


def logo(abbr, size=36):
    a = e(abbr)
    return (f"<picture class='logo' style='width:{size}px;height:{size}px'>"
            f"<source srcset='https://assets.nhle.com/logos/nhl/svg/{a}_dark.svg' media='(prefers-color-scheme: dark)'>"
            f"<img src='https://assets.nhle.com/logos/nhl/svg/{a}_light.svg' alt='{a}' width='{size}' height='{size}' loading='lazy'>"
            f"</picture>")


def name(abbr):
    return e(TEAMS.get(abbr, abbr))


def retro(d):
    return d.logged_at.astype(str).str.contains("retroactively")


def goal_bar(value, cutoff, team):
    """Projected goals on a shared 0-4.5 scale, with a tick at the high-scoring cutoff."""
    w = max(0.0, min(value / SCALE, 1.0)) * 100
    c = cutoff / SCALE * 100
    hot = value >= cutoff
    tip = f"{TEAMS.get(team, team)}: {value:.2f} projected goals ({'high-scoring' if hot else 'below'} the {cutoff:.2f} cutoff)"
    return (f"<div class='bar' title='{e(tip)}'><div class='fill{' hot' if hot else ''}' style='width:{w:.1f}%'></div>"
            f"<div class='cut' style='left:{c:.1f}%'></div></div>")


GOALIE_RE = __import__("re").compile(r"^(.*) \((.*)\)$")


def goalie_parts(g):
    m = GOALIE_RE.match(str(g)) if isinstance(g, str) else None
    return (m.group(1), m.group(2)) if m else (str(g) if isinstance(g, str) else "unknown", "")


def goalie_html(logged, now):
    """Starter with a status badge; red tag if the starter changed after the game was logged."""
    now = now if isinstance(now, str) else logged
    nm, status = goalie_parts(now)
    st = status.lower()
    badge = (f"<span class='gb ok'>{tip('✓ Confirmed', TIPS['Confirmed'])}</span>" if "confirmed" in st and "un" not in st else
             f"<span class='gb likely'>{tip('Likely')}</span>" if "likely" in st else f"<span class='gb proj'>{tip('Projected')}</span>")
    old_nm, _ = goalie_parts(logged)
    changed = (f"<span class='gb chg'>{tip('Changed from ' + e(old_nm), f'The starter changed after this game was logged: the projection was made with {old_nm} in net. A better goalie now = projection too high; a worse one = too low.')}</span>"
               if old_nm != nm and old_nm != "unknown" else "")
    return f"<div class='goalie'>{e(nm)} {badge}{changed}</div>"


def injury_full(out, dtd):
    """Table Out column: EVERY missing player with his effect (wraps), then day-to-day names."""
    lines = []
    if isinstance(out, str) and out:
        ps = []
        for it in out.split("; "):
            name, d_off, d_def = (it.split("|") + ["0", "0"])[:3]
            ps.append((name, float(d_off or 0), float(d_def or 0)))
        ps.sort(key=lambda p: -max(abs(p[1]), abs(p[2])))  # biggest impact first
        for name, d_off, d_def in ps:
            tag = ""
            if name.endswith(")") and " (" in name:
                name, tag = name.rsplit(" (", 1)
                tag = f" <span class='itag'>{e(tag[:-1])}</span>"
            effect = f"{-d_off * 100:+.1f}% GF" if abs(d_off) >= abs(d_def) else f"{d_def * 100:+.1f}% GA"
            tipt = f"{name}: team scoring {-d_off * 100:+.1f}%, opponent scoring {d_def * 100:+.1f}%"
            lines.append(f"<span class='ip' title='{e(tipt)}'>{e(short_name(name))}{tag} <b>{effect}</b></span>")
    if isinstance(dtd, str) and dtd:
        lines.append(f"<span class='ip dtd' title='Day-to-day: usually plays, not adjusted'>DTD: {e(', '.join(short_name(n) for n in dtd.split(', ')))}</span>")
    return f"<div class='outlist'>{''.join(lines)}</div>" if lines else "<span class='muted'>–</span>"


def injury_html(out, dtd):
    """'Out: Hyman −3.0%, Nugent-Hopkins −2.0%' (impact on the team's scoring) and day-to-day names."""
    parts, players_out = [], []
    if isinstance(out, str) and out:
        for it in out.split("; "):
            name, d_off, d_def = (it.split("|") + ["0", "0"])[:3]
            players_out.append((name, float(d_off or 0), float(d_def or 0)))
        players_out.sort(key=lambda p: -max(abs(p[1]), abs(p[2])))  # biggest impact first
        items = []
        for name, d_off, d_def in players_out[:3]:
            last = e(short_name(name))
            effect = f"{-d_off * 100:+.1f}% GF" if abs(d_off) >= abs(d_def) else f"{d_def * 100:+.1f}% GA"
            items.append(f"<span>{last} {effect}</span>")
        more = players_out[3:]
        if more:
            items.append(f"<span>+{len(more)} more</span>")
        parts.append(f"<span class='inj out'>Out: {', '.join(items)}</span>")
    if isinstance(dtd, str) and dtd and len(players_out) < 3:
        parts.append("<span class='inj dtd'>DTD: "
                     f"{', '.join(e(short_name(n)) for n in dtd.split(', ')[:2])}</span>")
    if not parts:
        return "<div class='injuries'></div>"
    full = []
    for name, d_off, d_def in players_out:
        full.append(f"{name}: team scoring {-d_off * 100:+.1f}%, opponent scoring {d_def * 100:+.1f}%")
    if isinstance(dtd, str) and dtd:
        full.append(f"Day-to-day (usually plays, not adjusted): {dtd}")
    text = ("Out = injured, suspended or not in tonight's projected lineup (scratch), already taken out of the projection. GF = his team's goals, GA = goals against. "
            + " | ".join(full))
    return f"<div class='tip injwrap' tabindex='0' data-tip='{e(text)}'><div class='injuries'>{' '.join(parts)}</div></div>"


def short_name(full):
    """'Igor Shesterkin' -> 'I. Shesterkin', 'Ukko-Pekka Luukkonen' -> 'U. Luukkonen'."""
    full = str(full).strip()
    if " " not in full:
        return full
    first, last = full.split(" ", 1)
    return f"{first[0]}. {last}"


def goalie_compact(logged, now, src=None, actual=None):
    """Table version: last name + short badge; full details in the hover text.
    src = which sources confirmed him (confirm.py); actual = who really started (after the game)."""
    import confirm
    now = now if isinstance(now, str) else logged
    nm, status = goalie_parts(now)
    st = status.lower()
    srcs = f" Sources: {src}." if isinstance(src, str) and src else ""
    if isinstance(actual, str) and actual:
        # finished game: show who really started, and whether the projection had the right goalie
        used, _ = goalie_parts(logged)  # the goalie the shown projection was built with
        right = used != "unknown" and confirm.same(actual, used)
        badge = (f"<span class='gb ok'>{tip('✓', f'{actual} started, as projected.')}</span>" if right else
                 f"<span class='gb chg'>{tip('⇄ ' + e(used.split(' ', 1)[-1]), f'{actual} started, but the projection used {used}.')}</span>")
        return f"<span class='gc'>{e(short_name(actual) if '.' not in actual else actual)} {badge}</span>"
    last = short_name(nm) if nm != "unknown" else "?"
    if "conflict" in st:
        badge = f"<span class='gb conflict'>{tip('⚠', f'{nm}: sources disagree on the starter; the projection uses the one most sources back.{srcs}')}</span>"
    elif "confirmed" in st and "un" not in st:
        badge = f"<span class='gb ok'>{tip('✓', f'{nm}: confirmed starter.{srcs}')}</span>"
    elif "likely" in st:
        badge = f"<span class='gb likely'>{tip('Likely', f'{nm}: expected to start, not confirmed yet.{srcs}')}</span>"
    else:
        badge = f"<span class='gb proj'>{tip('Proj', f'{nm}: starter not announced yet (best guess or usual starter).{srcs}')}</span>"
    old_nm, _ = goalie_parts(logged)
    changed = ""
    if old_nm != nm and old_nm != "unknown":
        changed = (f" <span class='gb chg'>{tip('⇄ ' + e(old_nm.split(' ', 1)[-1]), f'Starter changed after this game was logged: the projection used {old_nm}. A better goalie now = projection too high; a worse one = too low.')}</span>")
    return f"<span class='gc'>{e(last)} {badge}{changed}</span>"


def team_row(abbr, proj, cutoff, goalie, goalie_now=None, b2b=False, score=None, out=None, dtd=None):
    hot = proj >= cutoff
    tname = TEAMS.get(abbr, abbr)
    right = (f"<div class='score'>{tip(str(score), f'{tname} scored {score}. The model projected {proj:.2f} before the game.', 'tr')}"
             f"<small>proj {proj:.2f}{' · HIGH' if hot else ''}</small></div>" if score is not None else
             f"<div class='pg'><b>{tip(f'{proj:.2f}', f'{tname} projected goals tonight (high-scoring cutoff: {cutoff:.2f}).', 'tr')}</b>"
             f"{'<span class=hot-tag>' + tip('HIGH', cls='tr') + '</span>' if hot else ''}</div>")
    on_b2b = str(b2b).strip().lower() in ("true", "1", "1.0")  # CSV may hold bools, strings or floats
    tag = f"<span class='b2b'>{tip('B2B', TIPS['B2B tag'])}</span>" if on_b2b else ""
    return f"""<div class='team'>
      {logo(abbr)}
      <div class='tname'><div class='full'>{name(abbr)} {tag}</div>{goalie_html(goalie, goalie_now)}
        {injury_html(out, dtd)}{goal_bar(proj, cutoff, abbr)}</div>
      {right}</div>"""


def breakdown(r, flagged):
    if pd.isna(getattr(r, "away_ev", float("nan"))):
        return "<div class='why'><div class='why-h'>Projection breakdown</div><p class='muted small'>Not available for this game.</p></div>"
    def row(side, abbr, proj):
        g = lambda c: getattr(r, f"{side}_{c}")
        adj = lambda v: f"{v * 100:+.1f}%" if abs(v) >= 0.0005 else "–"
        return (f"<tr><td>{logo(abbr, 18)} {e(abbr)}</td><td class='num'>{g('ev'):.2f}</td><td class='num'>{g('pp'):.2f}</td>"
                f"<td class='num'>{g('oth'):.2f}</td><td class='num'>{adj(g('gadj'))}</td><td class='num'>{adj(g('b2badj'))}</td>"
                f"<td class='num'>{'–' if pd.isna(g('spd')) else adj(g('spd'))}</td>"
                f"<td class='num'>{'–' if pd.isna(g('inj')) else adj(g('inj'))}</td>"
                f"<td class='num'><b>{proj:.2f}</b></td></tr>")
    return f"""<div class='why'><div class='why-h'>{'Why it’s flagged' if flagged else 'Projection breakdown'}</div>
      <table><thead><tr><th>{tip('Team', cls='tl')}</th><th class='num'>{tip('5v5')}</th><th class='num'>{tip('PP')}</th>
      <th class='num'>{tip('Oth')}</th><th class='num'>{tip('Gl')}</th><th class='num'>{tip('B2B')}</th>
      <th class='num'>{tip('Inj')}</th><th class='num'>{tip('Proj', cls='tr')}</th></tr></thead>
      <tbody>{row('away', r.away, r.proj_away)}{row('home', r.home, r.proj_home)}</tbody></table>{lineup_note(r)}</div>"""


def lineup_note(r):
    """Where each team's projected lineup came from (DailyFaceoff), so stale ones are obvious."""
    parts = [f"{e(t)}: {e(src)}" for t, src in ((r.away, getattr(r, "away_lineup", None)), (r.home, getattr(r, "home_lineup", None)))
             if isinstance(src, str) and src]
    if not parts:
        return ""
    return (f"<div class='lineup-src'>{tip('Lineups', TIPS['Lineups'], 'tl')}: {' · '.join(parts)}</div>")


def game_card(r):
    flagged = r.flag
    final = not pd.isna(r.final_total)
    ascore = int(r.away_score) if final else None
    hscore = int(r.home_score) if final else None
    rows = (team_row(r.away, r.proj_away, r.cutoff, r.away_goalie, r.away_goalie_now, r.away_b2b, ascore, r.away_out, r.away_dtd)
            + team_row(r.home, r.proj_home, r.cutoff, r.home_goalie, r.home_goalie_now, r.home_b2b, hscore, r.home_out, r.home_dtd))
    def kv(label, value, wide=False):
        return f"<div class='kv{' wide' if wide else ''}'><span>{tip(label)}</span><b>{value}</b></div>"
    blank = "<div class='kv'></div>"
    if final:
        vs = "<span class='pill muted-pill'>no line</span>"
        if not pd.isna(r.bet_total):
            t = r.bet_total
            vs = (f"<span class='pill over'>OVER {line(t)}</span>" if r.final_total > t else
                  f"<span class='pill under'>UNDER {line(t)}</span>" if r.final_total < t else f"<span class='pill'>PUSH {line(t)}</span>")
        moved = "" if pd.isna(r.close_total) or pd.isna(r.bet_total) or r.close_total == r.bet_total else (
            " ↑" if r.close_total > r.bet_total else " ↓")
        meta = [kv("Total goals", f"<span class='big-total'>{int(r.final_total)}</span>"), kv("vs line", vs),
                kv("Proj total", f"{r.proj:.2f}"),
                kv("Line", "–" if pd.isna(r.bet_total) else f"{line(r.bet_total)} → {line(r.close_total)}{moved}"),
                kv("P(7+)", f"{r.p7:.0%}"),
                kv("Best over", f"{book(r.best_book)} o{line(r.best_total)} {price(r.best_over)}") if not pd.isna(r.best_total) else kv("Best over", "–")]
        if flagged and not pd.isna(r.result):
            meta += [kv("Pick", f"<span class='res {e(r.result)}'>{e(r.result)} {r.profit:+.2f}u</span>"),
                     kv("Best book", "–" if pd.isna(r.profit_best) else f"{r.profit_best:+.2f}u"), blank]
    else:
        meta = [kv("Proj total", f"{r.proj:.2f}"), kv("P(7+)", f"{r.p7:.0%}"),
                kv("Line", "<span class='muted'>not posted</span>" if pd.isna(r.bet_total) else
                   f"{line(r.open_total)} → {line(r.bet_total)}"),
                kv("Over price", "–" if pd.isna(r.bet_over) else price(r.bet_over)),
                kv("Best over", f"{book(r.best_book)} o{line(r.best_total)} {price(r.best_over)}", wide=True) if not pd.isna(r.best_total)
                else kv("Best over", "<span class='muted'>–</span>", wide=True)]
    bar = (f"<div class='flagbar'>{tip('★ OVER FLAG', TIPS['OVER FLAG'], 'tl')} · {'over' if final else 'bet over'} {line(r.bet_total)}</div>"
           if flagged else "")
    return f"""<article class='card{' flagged' if flagged else ''}'>{bar or "<div class='flagbar empty'></div>"}{rows}
      <div class='meta'>{''.join(meta)}</div>{breakdown(r, flagged)}</article>"""


LAYOUT = "table"  # "table" (one table, two rows per game) or "cards" (one card per game); backup: tag card-dashboard-v1


def day_view(g):
    return day_table(g) if LAYOUT == "table" else day_cards(g)


def _is(v):
    return str(v).strip().lower() in ("true", "1", "1.0")


def trends_html(r):
    """Context line: both teams' last 10, head-to-head since 2020-21, and the trend lean."""
    def l10(side, abbr):
        n = getattr(r, f"{side}_l10_n", None)
        if pd.isna(n) or not n:
            return ""
        return f"<b>{e(abbr)}</b> L{int(n)} avg {getattr(r, f'{side}_l10_avg'):.1f} · {int(getattr(r, f'{side}_l10_7'))}/{int(n)} 7+"
    parts = [x for x in (l10("away", r.away), l10("home", r.home)) if x]
    hn = getattr(r, "h2h_n", None)
    if not pd.isna(hn) and hn:
        last = getattr(r, "h2h_last", None)
        parts.append(f"<b>H2H</b> {int(hn)} since '20 · avg {r.h2h_avg:.1f} · {int(r.h2h_7)}/{int(hn)} 7+"
                     + (f" <span class='muted'>· last: {e(last)}</span>" if isinstance(last, str) and last else ""))
    if not parts:
        return ""
    ln = getattr(r, "trend_lean", None)
    chip = (f" <span class='lean {str(ln).lower()}'>{tip('trends: ' + str(ln).lower(), TIPS['Lean'], 'tr')}</span>"
            if isinstance(ln, str) and ln else "")
    return (f"<div class='trends'>{tip('Trends', TIPS['Trends'], 'tl')} / {tip('H2H', TIPS['H2H'], 'tl')}: "
            f"{' &nbsp;|&nbsp; '.join(parts)}{chip}</div>")


def day_table(g):
    """One table for the day, two rows per game (away, home), sized to fit without scrolling on a
    desktop screen: decision columns first, then goalie, injuries and the projection breakdown."""
    g = current(g).sort_values(["p7", "proj"], ascending=[False, False])  # most likely to go 7+ first
    final_day = bool(len(g)) and g.final_total.notna().all()
    ranks = rank_tags(g.date.iloc[0]) if len(g) else {}  # the ranks teams had on game day
    head = f"<th>{tip('Team', cls='tl')}</th>"
    if final_day:
        head += f"<th class='num'>{tip('G', 'Final goals for this team (shootout winner gets +1, as sportsbooks settle).')}</th>"
    head += f"<th class='num projh'>{tip('Proj')}</th>"
    if final_day:
        head += (f"<th class='gcol ctr'>{tip('Total goals')}</th><th class='ctr'>{tip('Proj total')}</th><th class='ctr'>{tip('P(7+)')}</th>"
                 f"<th class='ctr'>{tip('Line')}</th><th class='ctr'>{tip('Pick')}</th>")
    else:
        head += (f"<th class='gcol ctr'>{tip('Proj total')}</th><th class='ctr'>{tip('P(7+)')}</th>"
                 f"<th class='ctr'>{tip('Line', 'Consensus total: opening line → now, and the over price (−120 = risk 120 to win 100). ★ FLAG = the model’s over pick.')}</th>")
    head += (f"<th class='gcol'>{tip('Goalie', 'Starting goalie, checked against DailyFaceoff, Rotowire and GoaliePost: ✓ confirmed, Likely, Proj (not announced), ⚠ sources disagree. Hover the badge for which sources said what. On results: who actually started (NHL box score), ⇄ = not the goalie the projection used.')}</th>"
             f"<th class='num bcol'>{tip('5v5')}</th><th class='num'>{tip('PP')}</th>"
             f"<th class='num'>{tip('Gl', cls='tr')}</th><th class='num'>{tip('Oth', cls='tr')}</th><th class='num'>{tip('B2B', cls='tr')}</th><th class='num'>{tip('Spd', cls='tr')}</th>"
             f"<th class='num'>{tip('Inj', cls='tr')}</th>")
    # fixed widths (%): Team (room for the OFF/DEF ranks) + Game/Result = 53.5 | Goalies 15.5 | Breakdown 31
    widths = ([15.5, 2.5, 5.5] if final_day else [18.5, 7]) \
        + ([7.5, 4.5, 4, 6, 8] if final_day else [8, 6, 14]) + [15.5] + [4.4, 3.9, 5.2, 3.9, 4.8, 4.4, 4.4]
    cols = "<colgroup>" + "".join(f"<col style='width:{w:.3f}%'>" for w in widths) + "</colgroup>"
    sections = (f"<tr class='sec'><th colspan='{3 if final_day else 2}'>Team</th>"
                f"<th class='gcol' colspan='{5 if final_day else 3}'>{'Result' if final_day else 'Game'}</th>"
                f"<th class='gcol'>Goalies</th><th class='bcol' colspan='7'>Projection breakdown</th></tr>")
    body, mcards = [], []
    for i, r in enumerate(g.itertuples()):
        flagged, final = bool(r.flag), not pd.isna(r.final_total)
        cls = ("flagged " if flagged else "") + ("alt" if i % 2 else "")

        def team(side, abbr, proj, score):
            hot = proj >= r.cutoff
            rk = f"<span class='rk-tag' title='{e(TIPS['Rank tag'])}'>{e(ranks[abbr])}</span>" if abbr in ranks else ""
            cells = (f"<td class='tm'>{logo(abbr, 22)}<b title='{e(TEAMS.get(abbr, abbr))}'>{e(abbr)}</b>{rk}</td>")
            if final_day:
                cells += f"<td class='num score-cell'>{int(score)}</td>"
            sq = f"<span class='b2b-sq' title='{e(TIPS['B2B tag'])}'></span>" if _is(getattr(r, f"{side}_b2b")) else ""
            cells += (f"<td class='num proj{' hot' if hot else ''}'>{sq}{tip(f'{proj:.2f}', f'{TEAMS.get(abbr, abbr)} projected goals (high-scoring cutoff {r.cutoff:.2f}).' + (' HIGH: above the cutoff.' if hot else ''))}"
                      f"<span class='hot-dot{'' if hot else ' off'}'>●</span></td>")
            return cells

        def detail(side):
            g_ = lambda c: getattr(r, f"{side}_{c}", float("nan"))
            cells = f"<td class='gl gcol'>{goalie_compact(g_('goalie'), g_('goalie_now'), g_('goalie_src'), g_('goalie_actual'))}</td>"
            return cells + breakdown_cells(side)

        def breakdown_cells(side):
            g_ = lambda c: getattr(r, f"{side}_{c}", float("nan"))
            def adj(v):
                if pd.isna(v):
                    return "<span class='muted' title='Not part of the model yet on this date'>n/a</span>"
                return "–" if abs(v) < 0.0005 else f"{v * 100:+.1f}%"
            if pd.isna(g_("ev")):
                return "<td class='num muted bcol' colspan='7'>n/a</td>"
            def td(stat, text, extra=""):
                t = tier(stat, g_(stat))
                if text == "–":  # ~0% (no adjustment): left uncolored
                    t = ""
                return f"<td class='num{extra}{' t-' + t if t else ''}'{f' title={chr(39)}{t}{chr(39)}' if t else ''}>{text}</td>"
            return (td("ev", f"{g_('ev'):.2f}", " bcol") + td("pp", f"{g_('pp'):.2f}") + td("gadj", adj(g_("gadj")))
                            + td("oth", f"{g_('oth'):.2f}") + td("b2badj", adj(g_("b2badj"))) + td("spd", adj(g_("spd")))
                            + td("inj", adj(g_("inj"))))

        c = call(r, flagged)
        st = start_time(getattr(r, "start_utc", None))
        gtime = f"<span class='gtime'>{st} ET</span><br>" if st else ""
        callpill = f"<span class='callpill c-{c.lower()}'>{tip(('🔨 ' if c == 'SLAM' else '') + c, TIPS[c])}</span>"
        if c != r.first_call:
            callpill += f" <span class='was'>{tip('was ' + r.first_call, f'First call when this game was logged: {r.first_call}. Updated with the latest goalies, lines and injuries.')}</span>"
        if final_day:
            t = r.bet_total
            vs = ("<span class='pill muted-pill'>no line</span>" if pd.isna(t) else
                  f"<span class='pill over'>O {line(t)}</span>" if r.final_total > t else
                  f"<span class='pill under'>U {line(t)}</span>" if r.final_total < t else f"<span class='pill'>P {line(t)}</span>")
            moved = "" if pd.isna(r.close_total) or pd.isna(t) or r.close_total == t else (" ↑" if r.close_total > t else " ↓")
            c, res = call_result(r, flagged)
            if res is None:
                outcome = "<span class='muted small'>no line</span>"
            elif c in ("PASS", "AVOID"):
                outcome = {"W": "<span class='res W'>✓ under</span>", "L": "<span class='res L'>✗ went over</span>"}.get(res, "<span class='res P'>push</span>")
            else:
                outcome = f"<span class='res {res}'>{res}</span>"
            if flagged and not pd.isna(r.close_total) and not pd.isna(r.close_over):  # paper pick, graded at the close
                pr = "W" if r.final_total > r.close_total else "L" if r.final_total < r.close_total else "P"
                pu = float(grade.payout(r.close_over)) if pr == "W" else -1.0 if pr == "L" else 0.0
                outcome += f"<br><span class='muted small'>{tip('paper', TIPS['Paper bet'])} {pr} {pu:+.2f}u</span>"
            pick = f"{gtime}{callpill}<br>{outcome}"
            game = (f"<td class='gcol tot' rowspan='2'><span class='big-total'>{int(r.final_total)}</span>{vs}</td>"
                    f"<td class='num' rowspan='2'>{r.proj:.2f}</td><td class='num' rowspan='2'>{r.p7:.0%}</td>"
                    f"<td rowspan='2' class='linecell'>{'–' if pd.isna(t) else f'{line(t)} → {line(r.close_total)}{moved}'}</td>"
                    f"<td rowspan='2' class='pickcell'>{pick}</td>")
        else:
            ln = ("<span class='muted'>not posted</span>" if pd.isna(r.bet_total) else
                  f"{line(r.open_total)} → {line(r.bet_total)} <span class='muted'>o{price(r.bet_over)}</span>")
            game = (f"<td class='num gcol big-total' rowspan='2'>{r.proj:.2f}</td><td class='num p7' rowspan='2'>{r.p7:.0%}</td>"
                    f"<td rowspan='2'>{gtime}{callpill}<br>{ln}</td>")
        ctx = f"<div class='why-text'>{reasoning(r, flagged)}</div>"
        mcards.append(mobile_card(r, final, callpill, st, f"{vs} {outcome}" if final_day else ln,
                                  breakdown_cells, cls, ranks))
        away = team("away", r.away, r.proj_away, r.away_score if final else None) + game + detail("away")
        home = team("home", r.home, r.proj_home, r.home_score if final else None) + detail("home")
        body.append(f"<tbody class='game {cls}'><tr class='away'>{away}</tr><tr class='home'>{home}</tr>"
                    + (f"<tr class='srcrow whyrow'><td colspan='22'>{ctx}</td></tr>" if ctx else "") + "</tbody>")
    key = ("<div class='tier-key'>Breakdown (for scoring):" + "".join(f"<span class='t-{t}'>{t}</span>" for t in reversed(TIER_NAMES)) + "</div>")
    return (f"{key}<div class='gtable'><table class='gt'>{cols}<thead>{sections}<tr>{head}</tr></thead>{''.join(body)}</table></div>"
            f"<div class='mcards'>{''.join(mcards)}</div>"
            "<p class='muted small legend tbl-only'>Two rows per game (away, then home). <span style='color:var(--accent)'>●</span> = team projected "
            "high-scoring. Proj = (5v5 + PP + Oth) × goalie (Gl) × back-to-back (B2B) × team speed (Spd) × injuries (Inj). "
            "Hover or tap any underlined label for an explanation.</p>")


def mobile_card(r, final, callpill, st, status, breakdown_cells, cls, ranks):
    """Phone layout (shown under 760px wide instead of the table): one card per game with the same
    call, line/result, teams, goalies, tier-colored breakdown and reasoning."""
    def team(side, abbr, proj, score):
        hot = proj >= r.cutoff
        g_ = lambda c: getattr(r, f"{side}_{c}", float("nan"))
        rk = f"<span class='rk-tag' title='{e(TIPS['Rank tag'])}'>{e(ranks[abbr])}</span>" if abbr in ranks else ""
        sq = f"<span class='b2b-sq' title='{e(TIPS['B2B tag'])}'></span>" if _is(getattr(r, f"{side}_b2b")) else ""
        return (f"<div class='mc-team'>{logo(abbr, 26)}<b>{e(abbr)}</b><span>{rk}</span>"
                + (f"<span class='mc-score'>{int(score)}</span>" if final else "")
                + f"<span class='mc-proj{' hot' if hot else ''}'>{sq}{proj:.2f}<span class='hot-dot{'' if hot else ' off'}'>●</span></span>"
                + f"<div class='mc-gl'>{goalie_compact(g_('goalie'), g_('goalie_now'), g_('goalie_src'), g_('goalie_actual'))}</div></div>")
    total = (f"<span class='big-total'>{int(r.final_total)}</span> goals · proj {r.proj:.2f}" if final
             else f"Proj total <b>{r.proj:.2f}</b>")
    head = "".join(f"<th class='num'>{tip(h, cls='tr' if i > 3 else '')}</th>" for i, h in enumerate(("5v5", "PP", "Gl", "Oth", "B2B", "Spd", "Inj")))
    bd = (f"<table class='gt mc-bd'><thead><tr><th></th>{head}</tr></thead><tbody>"
          f"<tr><td>{e(r.away)}</td>{breakdown_cells('away')}</tr><tr><td>{e(r.home)}</td>{breakdown_cells('home')}</tr></tbody></table>")
    return (f"<article class='mc {cls}'><div class='mc-top'>{f'<span class=gtime>{st} ET</span>' if st else ''}"
            f"<span class='mc-call'>{callpill}</span></div>"
            f"<div class='mc-status'>{status}</div>"
            f"{team('away', r.away, r.proj_away, r.away_score if final else None)}"
            f"{team('home', r.home, r.proj_home, r.home_score if final else None)}"
            f"<div class='mc-sum'>{total} · P(7+) <b>{r.p7:.0%}</b></div>{bd}"
            f"<details class='mc-why'><summary>Why this call</summary><div class='why-text'>{reasoning(r, bool(r.flag))}</div></details></article>")


def day_cards(g):
    g = g.sort_values(["flag", "proj"], ascending=[False, False])
    return (f"<div class='cards'>{''.join(game_card(r) for r in g.itertuples())}</div>"
            "<p class='muted small legend'>Breakdown: 5v5 + PP (power play) + Oth (other situations) goals, then Gl = opposing-goalie "
            "adjustment (+ means a below-average goalie), B2B = back-to-back and Inj = injury adjustments → Proj.</p>")


def day_summary(g):
    done = g[g.final_total.notna()]
    flags = int(current(g).flag.sum())
    parts = [f"{len(g)} games", f"<b>{flags} flag{'s' if flags != 1 else ''}</b>"]
    if len(done):
        wl = done[done.bet_total.notna()]
        parts.append(f"<b>{(wl.final_total > wl.bet_total).sum()} of {len(wl)}</b> went over the line")
        parts.append(f"avg <b>{done.final_total.mean():.1f}</b> goals (projected {done.proj.mean():.1f})")
        fl = closing_bets(done, keep_retro=True)  # paper picks, closing information only
        if len(fl):
            parts.append(f"flags <b>{(fl.res == 'W').sum()}-{(fl.res == 'L').sum()}-{(fl.res == 'P').sum()}</b> ({fl.units.sum():+.2f}u at close)")
        parts.append(call_record(current(done)))
    return " · ".join(parts)


def call_record(done):
    """'🔨 SLAM 1-0-0 · 1U 0-1-0 · PASS 1 of 2 stayed under · AVOID 6 of 10 stayed under' for finished games (vs the logged line)."""
    res = {"SLAM": [], "1U": [], "PASS": [], "AVOID": []}
    for r in done.itertuples():
        c, o = call_result(r, _is(r.flag))
        if o:
            res[c].append(o)
    out = []
    for c in ("SLAM", "1U"):
        x = res[c]
        out.append(f"{'🔨 ' if c == 'SLAM' else ''}{c} <b>{x.count('W')}-{x.count('L')}-{x.count('P')}</b>" if x else f"{c} –")
    for c in ("PASS", "AVOID"):
        a = res[c]
        out.append(f"{c} <b>{a.count('W')} of {len(a)}</b> stayed under" if a else f"{c} –")
    return "calls: " + " · ".join(out)


RETRO_NOTE = ("<p class='retro'><b>Retroactive day:</b> added after the fact from pre-game data only (earlier games, that day's "
              "projected starters, opening lines). Shown for reference; it does not count toward the paper trading record.</p>")


def slate(d):
    day = date.today().isoformat()  # Eastern time on GitHub Actions (TZ is set in the workflow)
    g = d[d.date == day]
    if g.empty:
        return f"<p class='muted'>{pd.Timestamp(day):%A, %B %-d}: no games logged for today (off day, or the morning run hasn't happened yet).</p>"
    return f"""<p class='sub'>{pd.Timestamp(day):%A, %B %-d} · {day_summary(g)} · bar tick = high-scoring cutoff
      ({current(g).cutoff.iloc[0]:.2f} goals){f" · starters as of {e(g.updated_at.dropna().max())}" if g.updated_at.notna().any() else ""}</p>
      {day_view(g)}"""


def yesterday(d):
    done = d[d.final_total.notna()]
    if done.empty:
        return "<p class='muted'>No finished games yet.</p>"
    day = done.date.max()
    g = d[d.date == day]
    return f"""{RETRO_NOTE if retro(g).any() else ""}<p class='sub'>{pd.Timestamp(day):%A, %B %-d} · {day_summary(g)}
      · <a href='days/{e(day)}.html'>day page →</a></p>{day_view(g)}"""


def accuracy(d):
    """How the projections did: summary tiles, then by projected total and by call (last pre-game projection)."""
    s = current(d[d.final_total.notna()])
    if s.empty:
        return "<p class='muted'>No finished games yet.</p>"
    s["call"] = [call(r, bool(r.flag)) for r in s.itertuples()]
    s["band"] = pd.cut(s.proj, [0, 5.5, 6.0, 6.5, 99], labels=["under 5.5", "5.5 – 6.0", "6.0 – 6.5", "6.5+"], right=False)

    def rows(groups):
        out = []
        for name, x in groups:
            if not len(x):
                continue
            diff = x.final_total.mean() - x.proj.mean()
            out.append(f"<tr><td>{name}</td><td class='num'>{len(x)}</td><td class='num'>{x.proj.mean():.2f}</td>"
                       f"<td class='num'>{x.final_total.mean():.2f}</td><td class='num {'pos' if diff > 0 else 'neg'}'>{diff:+.2f}</td>"
                       f"<td class='num'>{x.p7.mean():.0%}</td><td class='num'>{(x.final_total >= 7).mean():.0%}</td></tr>")
        return "".join(out)
    head = ("<thead><tr><th>{}</th><th class='num'>Games</th><th class='num'>Proj</th><th class='num'>Actual</th>"
            f"<th class='num'>{tip('Diff', 'Actual minus projected total goals. Projections run a little low by design (P(7+) corrects for it).', 'tr')}</th>"
            f"<th class='num'>{tip('Model 7+', 'Average model chance of 7+ goals.', 'tr')}</th>"
            f"<th class='num'>{tip('Actual 7+', 'How often those games actually had 7+ goals. Calibrated = close to Model 7+.', 'tr')}</th></tr></thead>")
    by_band = rows((str(b), x) for b, x in s.groupby("band", observed=True))
    by_call = rows((('🔨 ' if c == 'SLAM' else '') + c, s[s.call == c]) for c in ("SLAM", "1U", "PASS", "AVOID"))
    team_err = pd.concat([(s.away_score - s.proj_away).abs(), (s.home_score - s.proj_home).abs()]).mean()
    n_retro = int(retro(s).sum())
    return f"""<div class='tiles'>
      <div class='tile'><div class='label'>{tip('Games settled', 'Finished games in the log (live + retroactive).', 'tl')}</div><div class='num-big'>{len(s)}</div><div class='muted'>{n_retro} retroactive</div></div>
      <div class='tile'><div class='label'>{tip('Avg projected total', 'Average projected total (last run before puck drop) vs average actual goals.', 'tl')}</div><div class='num-big'>{s.proj.mean():.2f}</div><div class='muted'>actual {s.final_total.mean():.2f}</div></div>
      <div class='tile'><div class='label'>{tip('Model P(7+)', 'Average predicted chance of 7+ goals vs how often it actually happened. If the model is calibrated they match.', 'tl')}</div><div class='num-big'>{s.p7.mean():.0%}</div><div class='muted'>actual 7+ rate {(s.final_total >= 7).mean():.0%}</div></div>
      <div class='tile'><div class='label'>{tip('Team goals error', 'Average miss between a team’s projected and actual goals. Hockey is random; ~1.3–1.9 is normal.', 'tl')}</div><div class='num-big'>{team_err:.2f}</div><div class='muted'>avg miss per team</div></div></div>
      <div class='acc-grid'>
        <div><h3>By projected total</h3><div class='scroll'><table class='acc-t'>{head.format('Projected')}<tbody>{by_band}</tbody></table></div></div>
        <div><h3>By call</h3><div class='scroll'><table class='acc-t'>{head.format('Call')}<tbody>{by_call}</tbody></table></div></div>
      </div>
      <ul class='notes'><li>The test that matters is <b>Model 7+ vs Actual 7+</b>: if the model is calibrated they match, higher
      projection bands should score more, and SLAM should score more than 1U, PASS and AVOID.</li>
      <li>Uses each game's last projection and call before puck drop. Single-game misses are big in hockey, so judge this after
      a few hundred games, not a few nights.</li></ul>"""


def archive(d):
    if d.empty:
        return ""
    rows = []
    for day in sorted(d.date.unique(), reverse=True):
        g = d[d.date == day]
        rows.append(f"<li><a href='days/{e(day)}.html'><b>{pd.Timestamp(day):%a %b %-d}</b></a> · {day_summary(g)}"
                    f"{' · <i>retroactive</i>' if retro(g).any() else ''}</li>")
    return f"<ul class='archive'>{''.join(rows)}</ul>"


def day_page(d, day, days):
    g = d[d.date == day]
    i = days.index(day)
    prev_ = f"<a href='{days[i - 1]}.html'>← {pd.Timestamp(days[i - 1]):%b %-d}</a>" if i > 0 else "<span></span>"
    next_ = f"<a href='{days[i + 1]}.html'>{pd.Timestamp(days[i + 1]):%b %-d} →</a>" if i < len(days) - 1 else "<span></span>"
    body = f"""<header class='hero small-hero'><h1>{pd.Timestamp(day):%A, %B %-d, %Y}</h1>
      <p>{day_summary(g)}</p></header>
      <nav class='daynav'>{prev_}<a href='../index.html'>Dashboard</a>{next_}</nav>
      {RETRO_NOTE if retro(g).any() else ""}<section>{day_view(g)}</section>"""
    return shell(f"NHL Total Model · {day}", body, root="../")


def closing_bets(d, keep_retro=False):
    """The paper record, closing information only: games still flagged at the last run before puck drop,
    graded at the closing consensus total and over price. Retroactive days never count toward the record
    (keep_retro=True for a day's own summary)."""
    g = current(d if keep_retro else d[~retro(d)])
    g = g[g.flag & g.final_total.notna() & g.close_total.notna() & g.close_over.notna()].copy()
    g["res"] = np.where(g.final_total > g.close_total, "W", np.where(g.final_total < g.close_total, "L", "P"))
    g["units"] = np.where(g.res == "W", grade.payout(g.close_over), np.where(g.res == "L", -1.0, 0.0))
    return g


def record(d):
    cur = current(d[~retro(d)])
    f = cur[cur.flag]
    s = closing_bets(d)
    dec = s[s.res != "P"]
    w, l, p = (s.res == "W").sum(), (s.res == "L").sum(), (s.res == "P").sum()
    calls = [call(r, True) for r in s.itertuples()]
    s["call"] = calls
    by = {c: s[s.call == c] for c in ("SLAM", "1U", "PASS")}
    tiles = [
        ("Flagged picks", f"{len(f)}", f"{len(s)} settled"),
        ("Record", f"{w}-{l}-{p}" if len(s) else "–", f"{(dec.res == 'W').mean():.1%} wins" if len(dec) else "no results yet"),
        ("ROI · closing line", pct(s.units.mean() * 100) if len(s) else "–", f"{s.units.sum():+.2f}u" if len(s) else "&nbsp;"),
    ] + [(f"{'🔨 ' if c == 'SLAM' else ''}{c}", f"{(x.res == 'W').sum()}-{(x.res == 'L').sum()}-{(x.res == 'P').sum()}" if len(x) else "–",
          f"{x.units.sum():+.2f}u" if len(x) else "&nbsp;") for c, x in by.items()]
    rec_tips = {"Flagged picks": "Live OVER FLAG picks: games still flagged at the last model run before puck drop (retroactive days excluded).",
                "Record": "Wins-losses-pushes of those flagged overs at the closing consensus total.",
                "ROI · closing line": "Profit per unit risked at the closing consensus over price. Break-even at −110 needs 52.4% wins.",
                "🔨 SLAM": "Flagged picks the last pre-game call made a SLAM, at the closing line.",
                "1U": "Flagged picks the last pre-game call made a 1U, at the closing line.",
                "PASS": "Flagged picks the last pre-game call made a PASS (no bet): how they would have done at the closing line."}
    tiles_html = "".join(f"<div class='tile'><div class='label'>{tip(a, rec_tips.get(a), 'tl')}</div><div class='num-big'>{b}</div>"
                         f"<div class='muted'>{c_}</div></div>" for a, b, c_ in tiles)
    if len(s):
        rows = "".join(f"""<tr><td>{e(r.date)}</td><td class='matchup'>{logo(r.away, 22)}{logo(r.home, 22)} {e(r.away)} @ {e(r.home)}</td>
            <td>{'🔨 ' if r.call == 'SLAM' else ''}{e(r.call)}</td><td class='num'>o{line(r.close_total)} {price(r.close_over)}</td>
            <td class='num'>{int(r.final_total)}</td><td class='res {e(r.res)}'>{e(r.res)}</td><td class='num'>{r.units:+.2f}</td></tr>"""
                       for r in s.sort_values("date", ascending=False).itertuples())
        table = f"""<div class='scroll'><table><thead><tr><th>Date</th><th>Game</th><th>Call</th><th>Closing line</th>
          <th>Goals</th><th>Result</th><th>Units</th></tr></thead><tbody>{rows}</tbody></table></div>"""
    else:
        table = "<p class='muted'>No live flagged picks have settled yet. Judge the rule after 50–75 flagged picks, not before.</p>"
    return (f"<div class='tiles'>{tiles_html}</div>{table}"
            "<p class='muted small legend'>Closing information only: a pick counts if the game was still flagged at the last model run "
            "before puck drop, and it is graded at the closing consensus total and over price (1 unit per pick).</p>")


def rule_check():
    """SLAM rule check (src/rule_check.py), written once the log reaches 75 settled picks; '' until then."""
    path = paths.data("rule_check.json")
    if not os.path.exists(path):
        return ""
    import json
    rc = json.load(open(path))
    b, lv = rc["backtest"], rc["live"]
    names = {"current": "Current: SLAM both good/great, 1U needs a great team", "combined": f"Combined 5v5 above {rc['alt_ev_sum']:.2f}"}

    def cell(x, units=True):
        if not x or not x["n"]:
            return "<td class='num'>–</td>"
        roi = x["roi"] * 100
        return (f"<td class='num'>{x['w']}-{x['l']}-{x['p']}<br><span class='muted small'>{x['over']:.1%} · "
                f"<span class='{'pos' if roi > 0 else 'neg'}'>{pct(roi)}</span>{f' · {x['units']:+.1f}u' if units else ''}</span></td>")
    rows = ""
    for c in ("SLAM", "1U", "PASS"):
        for rule in ("current", "combined"):
            k = f"{rule}|{c}"
            if c == "PASS" and rule == "combined":
                continue
            rows += (f"<tr><td><b>{c}</b> · {names[rule]}</td>{cell(b.get(k + '|close|all'))}{cell(b.get(k + '|close|2021-23'), False)}"
                     f"{cell(b.get(k + '|close|2023-26'), False)}{cell(b.get(k + '|open|all'))}{cell(lv.get(k))}</tr>")
    return f"""<p class='sub'>Run {e(rc['date'])}, when the paper log reached {rc['picks']} settled picks. Report only: the calls
      on this page still use the current rule.</p>
      <div class='scroll'><table><thead><tr><th>Call · SLAM rule</th><th>2021-26 at close</th><th>2021-23 close</th>
      <th>2023-26 close</th><th>2021-26 at open</th><th>This season (live)</th></tr></thead><tbody>{rows}</tbody></table></div>
      <ul class='notes'><li>Each cell: won-lost-push over the line, then over %, ROI and units (1 unit per bet).</li>
      <li>Same flag and goalie AVOID for both rules. The combined rule has no PASS: every other flagged game is SLAM or 1U by combined 5v5. PASS rows count as overs (how they would have done if bet).</li>
      <li>This season = last pre-game call at its line, as the results table grades it.</li></ul>"""


RANK_STATS = [  # (key, header, decimals, explanation); per game, all situations unless noted
    ("goals", "Goals", 2, "Goals per game"), ("xg", "xG", 2, "Expected goals per game: every unblocked shot weighted by its chance of scoring (distance, angle, type, rebound)"),
    ("sog", "SOG", 1, "Shots on goal per game"), ("att", "Att", 1, "Shot attempts per game (on goal + missed + blocked)"),
    ("hd", "HD", 1, "High-danger shots per game (slot and crease)"), ("hdxg", "HD xG", 2, "Expected goals from high-danger shots only"),
    ("ppg", "PPG", 2, "Power-play goals per game (5-on-4)"), ("reb", "Reb", 1, "Rebound shots per game"),
    ("rebg", "Reb G", 2, "Rebound goals per game")]


def load_rankings(day=None):
    """data/team_rankings.csv (written by each model run) with rank columns r_*, or with day= the rankings
    saved for that game day (data/team_rankings_history.csv); None when missing."""
    path = paths.data("team_rankings.csv" if day is None else "team_rankings_history.csv")
    if not os.path.exists(path):
        return None
    r = pd.read_csv(path)
    if day is not None:
        r = r[r.date == day]
        if r.empty:
            return None
    best_high = {"gf": True, "ga": False, "gf_ev": True, "gf_pp": True, "ga_ev": False, "ga_pp": False,
                 "gf_adj": True, "ga_adj": False, "opp_d": False, "opp_o": True,
                 "score_off": True, "score_def": False, "score_off_adj": True, "score_def_adj": False}
    best_high |= {f"{k}F": True for k, *_ in RANK_STATS} | {f"{k}A": False for k, *_ in RANK_STATS}
    for c, hi in best_high.items():
        if c in r and r[c].notna().all():
            r[f"r_{c}"] = r[c].rank(ascending=not hi, method="min").astype(int)
    return r


def rank_tags(day=None):
    """{team: '#3 OFF / #10 DEF'} (current, or as of game day with day=); {} when there are no rankings.
    Total Offense / Total Defense ranks; days saved before those existed use the model's goals ranks."""
    r = load_rankings(day) if day is not None else None
    r = load_rankings() if r is None and (day is None or day == date.today().isoformat()) else r
    if r is None:
        return {}
    o, d_ = ("r_score_off", "r_score_def") if "r_score_off" in r else ("r_gf", "r_ga")
    return {x["team"]: f"#{x[o]} OFF / #{x[d_]} DEF" for _, x in r.iterrows()}


def rankings():
    """Total Offense / Total Defense: nine stats per game, combined by how well each predicts future goals
    (split_model.WEIGHTS), plus the model's own goals vs an average team and strength of schedule."""
    r = load_rankings()
    if r is None or "r_score_off" not in r:
        return ""
    n = len(r)

    def tcls(rank):  # rank fifths: 1st fifth = great ... last fifth = trash (green = strong unit)
        return "t-" + TIER_NAMES[4 - min(4, (rank - 1) * 5 // n)]

    def table(kind):
        side, score, model, opp = (("F", "score_off", "gf", "opp_d") if kind == "off" else ("A", "score_def", "ga", "opp_o"))
        k = "Rank OFF" if kind == "off" else "Rank DEF"
        w = split_model.WEIGHTS[side]

        def adj(x):  # Total rank after the schedule correction
            if not x["games"]:
                return "<td class='num muted' data-k='99'>–</td>"
            mv = x[f"r_{score}"] - x[f"r_{score}_adj"]
            arrow = "" if mv == 0 else f" <span class='{'pos' if mv > 0 else 'neg'} small'>{'↑' if mv > 0 else '↓'}{abs(mv)}</span>"
            return f"<td class='num {tcls(x[f'r_{score}_adj'])}' data-k='{x[f'r_{score}_adj']}'><b>#{x[f'r_{score}_adj']}</b>{arrow}</td>"

        def sched(x):  # last column
            if not x["games"]:
                return "<td class='num muted' data-k='99'>–</td>"
            return f"<td class='num' data-k='{x[f'r_{opp}']}'>#{x[f'r_{opp}']} <span class='muted small'>{x[opp] * 100:+.1f}%</span></td>"
        rows = "".join(
            f"<tr><td class='num' data-k='{x[f'r_{score}']}'>{x[f'r_{score}']}</td><td class='tm' data-k='{e(x['team'])}'>{logo(x['team'], 30)}<b title='{e(TEAMS.get(x['team'], x['team']))}'>{e(x['team'])}</b></td>"
            f"<td class='num {tcls(x[f'r_{score}'])}' data-k='{x[f'r_{score}']}'><b>{x[score] * (1 if kind == 'off' else -1):+.2f}</b></td>"
            f"<td class='num {tcls(x[f'r_{model}'])}' data-k='{x[f'r_{model}']}'>{x[model]:.2f} <span class='muted small'>#{x[f'r_{model}']}</span></td>" + adj(x)
            + "".join(f"<td class='num {tcls(x[f'r_{c}{side}'])}' data-k='{x[f'r_{c}{side}']}'>{x[f'{c}{side}']:.{dec}f} <span class='muted small'>#{x[f'r_{c}{side}']}</span></td>"
                      for c, _, dec, _ in RANK_STATS)
            + sched(x) + "</tr>"
            for _, x in r.sort_values(f"r_{score}").iterrows())
        verb = "allowed" if kind == "def" else ""
        heads = "".join(f"<th class='num'>{tip(h, f'{expl}{(' ' + verb) if verb else ''}. Weight in the total: {w[c] * 100:.0f}%. ' + ('Rank 1 = most.' if kind == 'off' else 'Rank 1 = fewest.'), 'tr' if i > 4 else '')}</th>"
                        for i, (c, h, _, expl) in enumerate(RANK_STATS))
        title = "Total Offense" if kind == "off" else "Total Defense (stats allowed)"
        return (f"<div class='rk' data-kind='{'offense' if kind == 'off' else 'defense'}'><h3>{title}</h3><table class='gt rk-t' data-sort='2'><thead><tr><th class='num'>#</th><th>Team</th>"
                f"<th class='num'>{tip('Total', TIPS[k + ' composite'])}</th><th class='num'>{tip('Model', TIPS[k + ' total'])}</th>"
                f"<th class='num'>{tip('Adj #', TIPS['Rank adj'])}</th>{heads}"
                f"<th class='num'>{tip('Sched', TIPS[k + ' sched'], 'tr')}</th>"
                f"</tr></thead><tbody>{rows}</tbody></table></div>")
    wf = split_model.WEIGHTS
    fmt = lambda side: ", ".join(f"{h} {wf[side][c] * 100:.0f}%" for c, h, *_ in sorted(RANK_STATS, key=lambda t: -wf[side][t[0]]))
    switch = ("<div class='rk-switch' role='tablist'><button type='button' data-show='offense' class='on'>Offense</button>"
              "<button type='button' data-show='defense'>Defense</button></div>")
    return (f"{switch}<div class='rk-wrap rk-stack'>{table('off')}{table('def')}</div>"
            "<ul class='notes'><li><b>Total</b> = the nine stats combined, each weighted by how well it predicted a team's "
            "future goals in 2021-26 (half a season vs the other half, 320 team-halves). Offense: " + fmt("F") + ". Defense: " + fmt("A") + ".</li>"
            "<li>Stats are per game and built like the model's ratings: last season pulled a third of the way to league average "
            "and worth 15 games, then this season's games. Early in the season they are mostly last season.</li>"
            "<li><b>Model</b> = the goals the model projects against a league-average opponent (what the picks use). "
            "<b>Sched</b> = how tough the opponents faced have been, judged by their Total Defense (for offense) or Total Offense "
            "(for defense) scores. <b>Adj #</b> = the Total rank after correcting every stat for that schedule.</li>"
            "<li>Colors = rank fifths, green = strong, red = weak. The #OFF / #DEF tags on the dashboard use these Total ranks.</li></ul>")


def backtest():
    def roi(v):
        return "<td class='num'>–</td>" if v is None else f"<td class='num {'pos' if v > 0 else 'neg'}'>{pct(v)}</td>"
    rows = "".join(f"<tr><td>{s}</td><td class='num'>{'–' if ob is None else ob}</td>{roi(oroi)}<td class='num'>{cb}</td>{roi(croi)}</tr>"
                   for s, ob, oroi, cb, croi in BACKTEST)
    return f"""<div class='scroll'><table><thead><tr><th>Season</th><th>{tip('Bets at open', 'Flagged overs if bet at the opening line (the first number books post).', 'down')}</th>
      <th>{tip('ROI at open', 'Profit per unit risked betting at the opening line.', 'down')}</th>
      <th>{tip('Bets at close', 'Flagged overs if bet at the closing line (right before puck drop). Counts differ because lines move into or out of 6/6.5.', 'down')}</th>
      <th>{tip('ROI at close', 'Profit per unit risked betting at the closing line.', 'down tr')}</th></tr></thead>
      <tbody>{rows}<tr class='total'><td>2021–26</td><td class='num'>585</td><td class='num pos'>+1.3%</td>
      <td class='num'>840</td><td class='num pos'>+2.4%</td></tr></tbody></table></div>
      <ul class='notes'>
        <li><b>Open</b> = betting the first line books post; <b>close</b> = the final line before puck drop. Counts differ
            because lines move into or out of 6 / 6.5 during the day.</li>
        <li>53–55% wins; uncertainty about ±3–4% ROI, so the past edge is small and not proven. Line shopping added about
            <b>+2.2 pts</b> on the same picks. Goalie ratings are calibrated to match how goalies actually play.</li>
        <li>Includes team skating speed (fitted on these same seasons, so its small gain is slightly optimistic). 2023-24 had
            very few flags, so its ROI is mostly noise.</li>
        <li>No 2022-23 opening lines in the data. With pre-2020 data the same rule was about break-even (2016–21).</li>
      </ul>"""


SCRIPT = """<script>
(function(){  // Team rankings: click a column header (not Team) to sort by it (best first), click again to reverse
  document.querySelectorAll('table.rk-t').forEach(function(t){
    var ths = t.tHead.rows[0].cells;
    function sort(i, rev){
      var body = t.tBodies[0], rows = Array.prototype.slice.call(body.rows);
      rows.sort(function(a, b){
        var x = a.cells[i].dataset.k, y = b.cells[i].dataset.k, nx = parseFloat(x), ny = parseFloat(y);
        var c = (isNaN(nx) || isNaN(ny)) ? x.localeCompare(y) : nx - ny;
        return rev ? -c : c;
      });
      rows.forEach(function(r){ body.appendChild(r); });
      Array.prototype.forEach.call(ths, function(h, j){ h.classList.toggle('sorted', j === i); h.classList.toggle('rev', j === i && rev); });
      t.dataset.sort = i; t.dataset.rev = rev ? '1' : '';
    }
    Array.prototype.forEach.call(ths, function(h, i){
      if (i === 1) return;  // Team name: not sortable
      h.classList.add('sortable');
      h.addEventListener('click', function(){ sort(i, String(t.dataset.sort) === String(i) && !t.dataset.rev); });
    });
    sort(2, false);  // always start sorted by Total
    window.addEventListener('pageshow', function(e){ if (e.persisted) sort(2, false); });  // also when restored from the back/forward cache
  });
})();
(function(){  // Team rankings: Offense / Defense switch (remembers the choice in the address, e.g. #defense)
  var sw = document.querySelector('.rk-switch'); if (!sw) return;
  function show(k){
    document.querySelectorAll('.rk[data-kind]').forEach(function(t){ t.hidden = t.dataset.kind !== k; });
    sw.querySelectorAll('button').forEach(function(b){ b.classList.toggle('on', b.dataset.show === k); b.setAttribute('aria-selected', b.dataset.show === k); });
  }
  sw.addEventListener('click', function(e){ var b = e.target.closest('button'); if (!b) return; show(b.dataset.show); history.replaceState(null, '', '#' + b.dataset.show); });
  show(location.hash === '#defense' ? 'defense' : 'offense');
})();
// one floating explanation box, placed next to the hovered/tapped label (fixed, so tables can't clip it)
const box = document.createElement("div"); box.id = "tipbox"; document.body.appendChild(box);
document.addEventListener("mouseover", show); document.addEventListener("focusin", show);
document.addEventListener("mouseout", hide); document.addEventListener("focusout", hide);
window.addEventListener("scroll", () => box.classList.remove("on"), {passive: true});
function show(ev) {
  const t = ev.target.closest && ev.target.closest(".tip"); if (!t) return;
  box.textContent = t.dataset.tip; box.classList.add("on");
  const r = t.getBoundingClientRect(), b = box.getBoundingClientRect();
  const left = Math.max(8, Math.min(r.left + r.width / 2 - b.width / 2, window.innerWidth - b.width - 8));
  const top = r.top - b.height - 8 >= 8 ? r.top - b.height - 8 : r.bottom + 8;
  box.style.left = left + "px"; box.style.top = top + "px";
}
function hide(ev) {
  const t = ev.target.closest && ev.target.closest(".tip");
  if (t && !(ev.relatedTarget && t.contains(ev.relatedTarget))) box.classList.remove("on");
}
</script>
"""

CSS = """
:root{--bg:#f3f5f8;--card:#fff;--ink:#0f1a2a;--muted:#5f6b7a;--line:#dfe4ea;--ice:#e8eef5;
  --accent:#1f6feb;--accent-soft:#c9dbf7;--gold:#c99700;--gold-soft:#fff4cc;--red:#c8102e;--pos:#1a7f37;--neg:#c62828}
@media (prefers-color-scheme:dark){:root{--bg:#0b1119;--card:#131c27;--ink:#e8edf3;--muted:#93a1b2;--line:#233040;--ice:#18222f;
  --accent:#58a6ff;--accent-soft:#1d3554;--gold:#e3b341;--gold-soft:#2b2410;--red:#ff5a6e;--pos:#3fb950;--neg:#f85149;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1360px;margin:0 auto;padding:0 16px 64px}
/* hero: a rink seen from above - red center line, blue lines, faceoff circle */
.hero{position:relative;overflow:hidden;margin:0 -16px;padding:34px 24px 30px;color:#fff;
  background:linear-gradient(90deg,transparent calc(50% - 2px),rgba(200,16,46,.85) calc(50% - 2px),rgba(200,16,46,.85) calc(50% + 2px),transparent calc(50% + 2px)),
    linear-gradient(90deg,transparent 30%,rgba(31,111,235,.75) 30%,rgba(31,111,235,.75) calc(30% + 6px),transparent calc(30% + 6px),
      transparent calc(70% - 6px),rgba(31,111,235,.75) calc(70% - 6px),rgba(31,111,235,.75) 70%,transparent 70%),
    radial-gradient(circle at 50% 50%,transparent 58px,rgba(31,111,235,.6) 59px,rgba(31,111,235,.6) 61px,transparent 62px),
    linear-gradient(160deg,#0d2440,#0a1a2e 60%,#081422)}
.lastrun{position:absolute;top:14px;right:18px;text-align:right;font-size:11px;line-height:1.35;color:#c9d6e6;z-index:2}
.lastrun b{display:block;font-size:13px;color:#fff;font-weight:700}.lastrun .tip{border-bottom-color:rgba(255,255,255,.45)}
@media (max-width:600px){.lastrun{position:static;text-align:left;margin-top:8px}}
.why-text .tt{display:block;margin:3px 0;padding-left:10px;border-left:3px solid var(--line)}
.mcards{display:none}
.rk-tag{margin-left:6px;font-size:10px;font-weight:700;color:var(--muted);white-space:nowrap}
.b2b-sq{display:inline-block;width:9px;height:9px;background:#dc2626;border-radius:2px;margin-right:5px;vertical-align:middle}
.acc-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:18px;margin-top:16px}.acc-grid h3{margin:0 0 6px;font-size:15px}table.acc-t{width:100%}table.acc-t td,table.acc-t th{padding:6px 8px}
.rk-switch{display:inline-flex;gap:4px;padding:4px;margin:0 0 14px;background:var(--ice);border:1px solid var(--line);border-radius:999px}
.rk-switch button{font:inherit;font-size:14px;font-weight:800;padding:7px 22px;border:0;border-radius:999px;background:transparent;color:var(--muted);cursor:pointer}
.rk-switch button.on{background:var(--card);color:var(--ink);box-shadow:0 1px 3px rgba(0,0,0,.25)}
.rk[hidden]{display:none!important}
table.rk-t th.sortable{cursor:pointer;user-select:none}table.rk-t th.sorted{color:var(--ink)}
table.rk-t th.sorted::after{content:" ▲";font-size:9px}table.rk-t th.sorted.rev::after{content:" ▼"}
.rk-wrap{display:flex;flex-wrap:wrap;gap:16px}.rk-stack{flex-direction:column}.rk-stack .rk{flex:0 0 auto;width:100%;max-width:100%}.rk{flex:1 1 360px;min-width:0;overflow-x:auto}.rk h3{margin:0 0 8px;font-size:15px}
table.gt.rk-t{table-layout:auto;font-size:13px}table.gt.rk-t td.tm b{font-size:16px;letter-spacing:.01em}table.gt.rk-t td.tm img{margin-right:8px;vertical-align:middle}table.gt.rk-t td,table.gt.rk-t th{padding:4px 8px;white-space:nowrap;overflow:visible;text-overflow:clip}
@media (max-width:760px){table.gt.rk-t{font-size:11.5px}table.gt.rk-t td,table.gt.rk-t th{padding:4px 3px}table.gt.rk-t td.tm b{font-size:14px}table.gt.rk-t td.tm picture,table.gt.rk-t td.tm img{width:24px!important;height:24px!important}table.gt.rk-t .small{font-size:9.5px}}
table.rk-t tbody tr:nth-child(even) td:not([class*=t-]){background:color-mix(in srgb,var(--ice) 50%,transparent)}
@media (max-width:760px){.gtable,.legend.tbl-only{display:none}.mcards{display:grid;gap:12px}}
.mc{background:var(--card);border:2px solid color-mix(in srgb,var(--muted) 45%,transparent);border-radius:12px;padding:12px 12px 8px}
.mc.flagged{border-color:var(--gold)}
.mc-top{display:flex;align-items:center;justify-content:space-between;gap:8px}.mc-top .gtime{font-size:15px}
.mc-status{margin:6px 0 4px;font-size:13px;line-height:1.35}
.mc-team{display:grid;grid-template-columns:auto auto 1fr auto auto;align-items:center;gap:6px;padding:6px 0;border-top:1px solid var(--line)}
.mc-team b{font-size:15px}.mc-team .b2b{justify-self:start}
.mc-score{font-size:18px;font-weight:800;grid-column:4}.mc-proj{grid-column:5;font-weight:700;font-variant-numeric:tabular-nums}
.mc-proj.hot{color:var(--accent)}.mc-gl{grid-column:1/-1;font-size:12.5px;color:var(--muted)}
.mc-sum{font-size:13px;padding:6px 0;border-top:1px solid var(--line)}.mc-sum .big-total{font-size:18px}
table.gt.mc-bd{table-layout:auto;font-size:11px;margin:2px 0 6px}table.gt.mc-bd td,table.gt.mc-bd th{padding:4px 2px;overflow:visible;text-overflow:clip;white-space:nowrap}
table.gt.mc-bd th{font-size:9.5px}table.gt.mc-bd td:first-child{font-weight:700;padding-right:4px}
.mc-why summary{cursor:pointer;font-size:13px;color:var(--muted);padding:4px 0}.mc-why .why-text{font-size:13px;line-height:1.45}
.hero h1{margin:0;font-size:clamp(28px,5vw,44px);letter-spacing:-.02em;position:relative}
.hero p{margin:6px 0 0;color:#c9d6e6;position:relative}
.hero .stats{display:flex;gap:12px;flex-wrap:wrap;margin-top:18px;position:relative}
.hero .stat{background:rgba(255,255,255,.1);backdrop-filter:blur(4px);border:1px solid rgba(255,255,255,.18);border-radius:10px;padding:8px 14px}
.hero .stat b{font-size:22px;display:block}.hero .stat span{font-size:12px;color:#c9d6e6;text-transform:uppercase;letter-spacing:.05em}
section{margin-top:28px}
h2{margin:0 0 4px;font-size:21px;letter-spacing:-.01em}
.sub{margin:0 0 14px;color:var(--muted)}.muted{color:var(--muted)}
.rule{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--gold);border-radius:10px;padding:12px 16px}
.retro{border-left:4px solid var(--muted);padding:8px 14px;border-radius:8px;background:var(--ice);margin:0 0 12px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}
.card{position:relative;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 14px 12px;
  display:flex;flex-direction:column}
.card.flagged{border:2px solid var(--gold);background:linear-gradient(180deg,var(--gold-soft),var(--card) 55%)}
.flagbar{margin:-14px -14px 8px;padding:6px 14px;min-height:29px;border-radius:12px 12px 0 0;background:var(--gold);color:#1a1200;font-size:12px;font-weight:800;letter-spacing:.05em}
.flagbar.empty{background:transparent;padding:0;min-height:0;margin-bottom:0}
.team{display:flex;align-items:center;gap:10px;padding:6px 0;min-height:78px}
.team+.team{border-top:1px dashed var(--line)}
.logo{display:inline-block;flex:none}.logo img{width:100%;height:100%;display:block}
.tname{flex:1;min-width:0}.full{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.goalie{font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar{position:relative;height:6px;border-radius:3px;background:var(--ice);margin-top:5px}
.bar .fill{height:100%;border-radius:3px;background:var(--accent-soft)}.bar .fill.hot{background:var(--accent)}
.bar .cut{position:absolute;top:-3px;width:2px;height:12px;background:var(--ink);opacity:.55;border-radius:1px}
.pg{text-align:right;min-width:62px}.pg b{font-size:20px;font-variant-numeric:tabular-nums}
.hot-tag{display:block;font-size:10px;font-weight:800;color:var(--accent);letter-spacing:.06em}
.score{font-size:28px;font-weight:800;min-width:40px;text-align:right;font-variant-numeric:tabular-nums;line-height:1.1}
.score small{display:block;font-size:11px;font-weight:600;color:var(--muted);white-space:nowrap}
.meta{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px 12px;align-items:start;margin-top:10px;padding-top:10px;border-top:1px solid var(--line)}
.meta .kv b{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.meta .kv.wide{grid-column:span 2}
.kv{display:flex;flex-direction:column;min-width:0}.kv>span{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);white-space:nowrap}
.kv b{font-variant-numeric:tabular-nums}.kv small{color:var(--muted);font-weight:500}
.big-total{font-size:22px;font-weight:800;line-height:1}
.pill{display:inline-block;font-size:12px;font-weight:800;padding:3px 10px;border-radius:999px;background:var(--ice);letter-spacing:.03em}
.pill.over{background:var(--pos);color:#fff}.pill.under{background:var(--neg);color:#fff}.muted-pill{color:var(--muted)}
.res.W{color:var(--pos)}.res.L{color:var(--neg)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:16px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.tile .label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.num-big{font-size:28px;font-weight:800;font-variant-numeric:tabular-nums}
.panel{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:700}
.num{text-align:right;font-variant-numeric:tabular-nums}tr.total td{font-weight:800}
.pos{color:var(--pos)}.neg{color:var(--neg)}td.matchup{display:flex;align-items:center;gap:4px}
ul.notes{margin:12px 0 0;padding-left:20px;color:var(--muted)}
dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:12px 0 0}
dl div{background:var(--ice);border-radius:10px;padding:10px 12px}dt{font-weight:800}dd{margin:2px 0 0;color:var(--muted)}
footer{margin-top:32px;font-size:13px;color:var(--muted)}a{color:var(--accent)}
.small{font-size:12px}
.gb{display:inline-block;font-size:10px;font-weight:800;letter-spacing:.03em;padding:1px 6px;border-radius:999px;margin-left:4px;vertical-align:1px}
.gb.ok{background:rgba(26,127,55,.15);color:var(--pos)}.gb.likely{background:rgba(201,151,0,.18);color:var(--gold)}
.gb.proj{background:var(--ice);color:var(--muted)}.gb.conflict{background:rgba(220,38,38,.18);color:var(--neg)}.gb.chg{background:var(--neg);color:#fff}
.goalie{white-space:normal;min-height:34px}
.injuries{min-height:16px;font-size:11px;line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.inj.out{color:var(--neg);font-weight:700}.inj.dtd{color:var(--muted)}
.b2b{display:inline-block;font-size:10px;font-weight:800;padding:1px 6px;border-radius:4px;background:var(--red);color:#fff;
  margin-left:4px;vertical-align:2px;letter-spacing:.04em}
.why{margin-top:auto;padding-top:10px;border-top:1px solid var(--line)}
.meta+.why{margin-top:auto}.card .meta{margin-bottom:10px}
.why-h{font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.05em;color:var(--accent)}
.card.flagged .why-h{color:var(--gold)}
.why table{font-size:12px;margin-top:4px}.why th,.why td{padding:4px 3px}.why th{font-size:10px}
.why td:first-child{white-space:nowrap}
.why td:first-child .logo{vertical-align:-4px;margin-right:2px}
.small-hero{padding:24px 24px 20px}.small-hero h1{font-size:clamp(22px,4vw,32px)}
.tabs{display:flex;gap:6px;margin:14px 0 4px;border-bottom:2px solid var(--line)}
.tab{padding:8px 16px;font-weight:700;font-size:14px;color:var(--muted);text-decoration:none;border-radius:8px 8px 0 0;margin-bottom:-2px;border:2px solid transparent}
.tab:hover{color:var(--ink)}.tab.on{color:var(--ink);background:var(--card);border-color:var(--line);border-bottom-color:var(--card)}
.daynav{display:flex;justify-content:space-between;align-items:center;margin:16px 0 0;font-weight:700}
.legend{margin:8px 0 0}
/* table layout: two rows per game, sized to fit a desktop screen */
.gtable{background:var(--card);border:4px solid color-mix(in srgb,var(--muted) 60%,transparent);border-radius:12px;overflow-x:auto}
table.gt{font-size:12.5px;border-collapse:separate;border-spacing:0;width:100%;table-layout:fixed}
.gt td,.gt th{overflow:hidden;text-overflow:ellipsis}
.gt thead tr:not(.sec) th{white-space:normal;line-height:1.25;vertical-align:bottom}
.gt td[rowspan]{white-space:normal}.gt td[rowspan].nowrap,.gt td[rowspan].tot{white-space:nowrap}
.gt td.tot{padding-left:3px;padding-right:3px}.gt td.linecell{white-space:normal;overflow:visible;text-overflow:clip;text-align:center}
.gt td.pickcell{line-height:1.15;padding-top:2px;padding-bottom:2px}.gt td.pickcell .small{font-size:10.5px}.gt td.pickcell .flagpill{margin-bottom:1px}
.gt td.tm{white-space:nowrap}.gt td.tm .b2b{margin-left:4px}.gt td.tm img,.gt td.tm picture{margin-right:5px}
.gt tbody.game tr.away td:not([rowspan]),.gt tbody.game tr.home td:not([rowspan]){height:34px;vertical-align:middle}
.gt th.num,.gt td.num{text-align:right}.gt th:not(.num),.gt td:not(.num){text-align:left}
.gt td,.gt th{vertical-align:middle}.gt thead tr:not(.sec) th{vertical-align:bottom}
.gt td.num,.gt td[rowspan]{font-variant-numeric:tabular-nums}
.gt th.projh{padding-right:15px}   /* lines the Proj header up with the numbers (room for the HIGH dot) */
.gt th{background:var(--card);padding:8px 5px;border-bottom:2px solid var(--line);font-size:10px;white-space:nowrap}
.gt td{padding:4px 5px;border-bottom:none;vertical-align:middle;white-space:nowrap}
/* each game is its own block: strong border between games */
.gt tbody.game tr.away td{border-top:4px solid color-mix(in srgb,var(--muted) 60%,transparent)}
.gt thead + tbody.game tr.away td{border-top:none}
.gt tbody.game tr.away td:not([rowspan]){padding-top:8px}.gt tbody.game tr.home td:not([rowspan]){padding-bottom:8px}
.gt tbody.alt td{background:color-mix(in srgb,var(--ice) 45%,transparent)}
.gt tbody.flagged td{background:var(--gold-soft)}
.gt tbody.flagged tr.away td:first-child,.gt tbody.flagged tr.home td:first-child{box-shadow:inset 4px 0 0 var(--gold)}
.gt td.tm,.gt thead tr:not(.sec) th:first-child{padding-left:10px}.gt td.tm img,.gt td.tm picture{vertical-align:middle;margin-right:6px}
.gt tbody td.t-great,.tier-key .t-great{background:rgba(22,163,74,.50)}.gt tbody td.t-good,.tier-key .t-good{background:rgba(22,163,74,.22)}
.gt tbody td.t-bad,.tier-key .t-bad{background:rgba(220,38,38,.22)}.gt tbody td.t-trash,.tier-key .t-trash{background:rgba(220,38,38,.50)}
.tier-key{display:flex;gap:6px;flex-wrap:wrap;align-items:center;font-size:12px;color:var(--muted);margin:6px 0}
.tier-key span{padding:1px 8px;border-radius:4px;color:var(--ink)}
.gt tbody td.t-mid,.tier-key .t-mid{background:rgba(234,179,8,.28)}
.gt td.proj{font-weight:800;font-size:13px}.gt td.proj.hot{color:var(--accent)}
.hot-dot{display:inline-block;width:10px;text-align:right;color:var(--accent);font-size:9px;vertical-align:2px}.hot-dot.off{visibility:hidden}
/* every column gets its own border; sections get a stronger one */
.gt th,.gt td{border-left:3px solid var(--line)}
.gt tr > :first-child{border-left:none}
.gt tbody.game tr.home td:not([rowspan]){border-top:3px solid var(--line)}
.gt tr.srcrow td{border-left:none;border-top:1px dashed color-mix(in srgb,var(--line) 70%,transparent)}
.gt td.gcol,.gt th.gcol,.gt td.bcol,.gt th.bcol{border-left:4px solid color-mix(in srgb,var(--muted) 60%,transparent)}
.gt tr.sec th{border-left:none}.gt tr.sec th.gcol,.gt tr.sec th.bcol{border-left:4px solid color-mix(in srgb,var(--muted) 60%,transparent)}
.gt thead tr:not(.sec) th{border-bottom:4px solid color-mix(in srgb,var(--muted) 60%,transparent)}
.gt td[rowspan],.gt td[rowspan].num,.gt th.ctr{text-align:center}
.gt tr.sec th{font-size:10.5px;font-weight:800;letter-spacing:.08em;color:var(--ink);text-align:left;padding:7px 8px 5px;
  border-bottom:1px solid var(--line);background:color-mix(in srgb,var(--ice) 60%,var(--card))}
.gt tr.sec th:first-child{border-top-left-radius:12px}.gt tr.sec th:last-child{border-top-right-radius:12px}
.gt td[rowspan]{vertical-align:middle;font-weight:600}.gt td.p7{font-weight:800}
.gt td.big-total{font-size:18px;font-weight:800}
.gt td.tot .big-total{display:inline-block;width:2.1ch;text-align:right;font-size:18px;margin-right:6px;vertical-align:-2px}
.gt .score-cell{font-size:15px;font-weight:800}
.gt td.gl{white-space:normal}.gt .gc{white-space:normal;line-height:1.5}.gt .gc .gb{margin-left:2px;white-space:nowrap}
.gt td.outs{white-space:normal;padding-top:5px;padding-bottom:5px}
.gt .outlist{display:flex;flex-direction:column;gap:2px;font-size:11px;line-height:1.3}
.gt .outlist .ip{color:var(--neg)}.gt .outlist .ip b{font-weight:700;white-space:nowrap}.gt .outlist .ip.dtd{color:var(--muted)}
.gt .itag{font-size:9.5px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.03em}
.gt .pill{font-size:11px;padding:2px 7px}
.was{font-size:9.5px;color:var(--muted);white-space:nowrap}.was .tip{border-bottom-style:dotted}
.gtime{font-size:13px;font-weight:800;color:var(--ink);white-space:nowrap}
.callpill{display:inline-block;font-size:10px;font-weight:800;padding:1px 8px;border-radius:999px;margin-bottom:2px;letter-spacing:.04em}
.callpill.c-slam{background:var(--gold);color:#1a1200}.callpill.c-1u{border:1.5px solid var(--gold);color:var(--ink)}
.callpill.c-pass{border:1px dashed var(--gold);color:var(--muted);font-weight:700}
.callpill.c-avoid{border:1px solid var(--line);color:var(--muted);font-weight:700}.callpill .tip{border-bottom:none}
.flagpill{display:inline-block;background:var(--gold);color:#1a1200;font-size:10px;font-weight:800;padding:1px 7px;border-radius:999px;margin-bottom:2px}
.gt tr.srcrow td{padding:0 8px 6px 38px;white-space:nowrap}
.gt tr.whyrow td{white-space:normal;padding:7px 14px 9px;text-align:left!important}
.gt .why-text{font-size:12.5px;line-height:1.5;color:var(--muted);max-width:none}.gt .why-text b{color:var(--ink)}.gt tr.srcrow .lineup-src{margin-top:1px;font-size:10.5px}
.gt .trends{font-size:11px;color:var(--ink);line-height:1.5}.gt .trends b{font-weight:700}
.lean{display:inline-block;font-size:10px;font-weight:800;padding:1px 7px;border-radius:999px;margin-left:6px;text-transform:uppercase;letter-spacing:.03em}
.lean.over{background:rgba(26,127,55,.16);color:var(--pos)}.lean.under{background:rgba(198,40,40,.14);color:var(--neg)}
.lineup-src{margin-top:6px;font-size:11px;color:var(--muted);line-height:1.35}
.tip{position:relative;cursor:help;border-bottom:1px dotted currentColor;outline:none}
#tipbox{position:fixed;left:0;top:0;max-width:260px;white-space:pre-line;font-size:12px;font-weight:500;line-height:1.4;
  text-align:left;color:#f2f5f9;background:#0f1a2a;border:1px solid rgba(255,255,255,.18);padding:7px 10px;border-radius:8px;
  box-shadow:0 8px 22px rgba(0,0,0,.3);opacity:0;visibility:hidden;transition:opacity .12s;z-index:100;pointer-events:none}
#tipbox.on{opacity:1;visibility:visible}
.tip.injwrap{display:block;border-bottom:none}.tip.injwrap .injuries{text-decoration:underline dotted;text-underline-offset:2px}
.gb .tip,.b2b .tip,.flagbar .tip,.hot-tag .tip{border-bottom-color:rgba(127,127,127,.6)}
ul.archive{list-style:none;margin:0;padding:0}ul.archive li{padding:8px 0;border-bottom:1px solid var(--line)}
ul.archive li:last-child{border-bottom:none}
"""


def tabs(active, has_rankings):
    """Tab bar between the dashboard and the team rankings page."""
    if not has_rankings:
        return ""
    t = [("dash", "index.html", "Dashboard"), ("rank", "rankings.html", "Team rankings")]
    return ("<nav class='tabs'>" + "".join(f"<a href='{u}' class='tab{' on' if k == active else ''}'>{n}</a>" for k, u, n in t)
            + "</nav>")


def shell(title, body, root=""):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<link rel="icon" type="image/svg+xml" href="{root}favicon.svg" media="(prefers-color-scheme: light)">
<link rel="icon" type="image/svg+xml" href="{root}favicon-dark.svg" media="(prefers-color-scheme: dark)">
<link rel="icon" type="image/png" sizes="32x32" href="{root}favicon-32.png">
<link rel="apple-touch-icon" href="{root}apple-touch-icon.png"><style>{CSS}</style></head>
<body><div class="wrap">{body}
{SCRIPT}
<footer>Paper trading only, not betting advice · Team logos © NHL and its teams ·
<a href="https://github.com/Prezbo8/NHL-total-model">github.com/Prezbo8/NHL-total-model</a></footer>
</div></body></html>"""


def last_run():
    """'Sat, Oct 3 · 5:17 PM EDT' from the last model run (data/last_run.txt); falls back to the log's latest update."""
    try:
        t = pd.Timestamp(open(paths.data("last_run.txt")).read().strip().rsplit(" ", 1)[0])
        tz = open(paths.data("last_run.txt")).read().strip().rsplit(" ", 1)[1]
    except (OSError, ValueError, IndexError):
        u = paper.read_log().updated_at.dropna()
        if u.empty:
            return ""
        t, tz = pd.Timestamp(u.max()), "ET"
    return f"{t:%a, %b %-d} · {t:%-I:%M %p} {tz}"


def build():
    d = paper.read_log()
    lr = last_run()
    stamp = (f"<div class='lastrun'>{tip('Last model run', 'When the model last ran: re-checked goalies, lineups, injuries and lines, and re-projected every game that had not started. It runs every hour from 11:17 AM to 10:17 PM Eastern and 15 minutes before each game.', 'tr down')}"
             f"<b>{e(lr)}</b></div>") if lr else ""
    rk = rankings()
    body = f"""
<header class="hero"><h1>NHL Total Model</h1>{stamp}</header>
{tabs("dash", bool(rk))}

<section><h2>Today's slate</h2>{slate(d)}</section>

<section><h2>Yesterday's results</h2>{yesterday(d)}</section>

<section><h2>Paper trading record</h2>{record(d)}</section>

{f"<section><h2>SLAM rule check · 75 picks</h2><div class='panel'>{rc}</div></section>" if (rc := rule_check()) else ""}

<section><h2>Projection accuracy</h2><div class="panel">{accuracy(d)}</div></section>

<section><h2>Archive</h2><div class="panel">{archive(d)}</div></section>

<section><h2>Backtest · frozen rule, 2020+ data only</h2><div class="panel">{backtest()}</div></section>

<section><h2>How it works</h2><div class="panel">
<p style="margin:0">Each team's goals are projected separately for <b>5-on-5</b> (expected goals + actual goals for/against per 60) and the
<b>power play</b> (PP and PK efficiency × penalties drawn and taken), plus other situations. The opposing <b>starting goalie's</b>
goals saved above expected scales goals allowed, <b>back-to-backs</b> cut the tired team's scoring ~8% (opponent +6.5%), and
<b>team skating speed</b> nudges fast teams up (+2% per step) and their opponents down (−1.7%).
Data from the 2020-21 season onward only (MoneyPuck, NHL API, DailyFaceoff, Action Network). Runs on GitHub Actions every 2 hours from 11 AM to 9 PM ET.</p>
<dl>
<div><dt>Projected goals bar</dt><dd>Each team's projected goals on a 0–4.5 scale. The tick marks the high-scoring cutoff; a solid bar means past it.</dd></div>
<div><dt>P(7+)</dt><dd>Model's chance of 7+ total goals: wins an over 6.5 and an over 6 (exactly 6 pushes an over 6). NHL average ≈ 45%.</dd></div>
<div><dt>OVER FLAG</dt><dd>Both teams past the cutoff and the line is 6 or 6.5. These are the picks that count in the record.</dd></div>
<div><dt>Goalie badges</dt><dd>✓ Confirmed / Likely / Projected starter, from DailyFaceoff, refreshed every run (every 2 hours). "Changed" = different from the starter the projection used.</dd></div>
<div><dt>B2B</dt><dd>Team played yesterday: its projected scoring is cut ~8% and its opponent's raised ~6.5%.</dd></div>
<div><dt>Injuries &amp; lineups</dt><dd>ESPN's injury list plus DailyFaceoff's projected lineups checked against the official NHL roster. Players who are out, on IR, suspended, or missing from tonight's lineup (scratch) are replaced by a replacement-level skater. GF = change to his team's scoring, GA = change to goals against (shown for whichever is bigger; hover for both). Day-to-day players are shown but not adjusted.</dd></div>
<div><dt>Breakdown</dt><dd>Each team's goals = (5-on-5 + power play + other situations) × opposing-goalie × back-to-back × team speed × injury adjustments. A + goalie number means the opposing goalie has been below average.</dd></div>
<div><dt>Team speed (Spd)</dt><dd>How often a team's skaters hit 20+ mph (NHL EDGE), last season vs the league. Fast teams score a little more and allow a little less, so it shifts team projections but barely changes totals.</dd></div>
</dl></div></section>"""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(shell("NHL Total Model", body))
    rk_path = os.path.join(os.path.dirname(OUT), "rankings.html")
    if rk:
        with open(rk_path, "w") as f:
            f.write(shell("NHL Total Model · Team rankings",
                          f"<header class='hero'><h1>Team rankings</h1>{stamp}</header>{tabs('rank', True)}"
                          f"<section><div class='panel'>{rk}</div></section>"))
    elif os.path.exists(rk_path):
        os.remove(rk_path)
    days = sorted(d.date.unique())
    os.makedirs(os.path.join(os.path.dirname(OUT), "days"), exist_ok=True)
    for day in days:
        with open(os.path.join(os.path.dirname(OUT), "days", f"{day}.html"), "w") as f:
            f.write(day_page(d, day, days))
    print(f"wrote {OUT} + {len(days)} day pages")


if __name__ == "__main__":
    build()
