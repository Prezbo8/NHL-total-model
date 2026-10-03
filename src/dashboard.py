"""Build docs/index.html (GitHub Pages dashboard) from data/paper_trades.csv.

  python3 src/dashboard.py
"""
import html
import os
from datetime import date

import pandas as pd

import paper
import paths
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
    "Pick": "The call (SLAM / 1U / AVOID) and how it did at the logged consensus line. SLAM / 1U: W = went over (units at 1 unit risked). AVOID: ✓ = stayed under, ✗ = went over.",
    "Best book": "Same pick at the best sportsbook price (the 'Best over' book), in units.",
    "Team": "Team, away first then home.",
    "5v5": "Goals this team should score at full strength (5 skaters vs 5). Most of a team's goals come from here.",
    "PP": "Goals this team should score on the power play: how good its power play is, how bad the other team's penalty kill is, and how many penalties are expected.",
    "Oth": "Goals from everything else (4-on-4, overtime, empty nets). Same league-average number for every team, so it has no colors.",
    "Gl": "How the other team's goalie changes this team's scoring. + = weak goalie, more goals. − = strong goalie, fewer goals.",
    "B2B": "Tired legs: a team that played yesterday scores 8% less. A team whose opponent played yesterday scores 6.5% more.",
    "Spd": "How fast this team skates compared with the opponent (20+ mph bursts last season). Fast teams score a bit more and allow a bit less.",
    "Inj": "Injuries and scratches: this team's missing scorers (fewer goals) plus the other team's missing defenders (more goals).",
    "Proj": "Projected goals = (5v5 + PP + Oth) × goalie × back-to-back × team speed × injury adjustments.",
    "HIGH": "Projected 2.95+ goals (top 40% of last season's team projections). An OVER FLAG needs both teams HIGH.",
    "Confirmed": "Starter confirmed (DailyFaceoff). Refreshed every run.",
    "Likely": "Starter expected but not confirmed yet (DailyFaceoff).",
    "Projected": "Starter not announced yet: DailyFaceoff's guess, or this team's usual recent starter.",
    "OVER FLAG": "The model's pick: both teams projected high-scoring and the line is 6 or 6.5. Bet the OVER at the 'Best over' book. These are the picks that count in the record.",
    "Lineups": "Projected lineup source (DailyFaceoff line combinations, checked against the official NHL roster). A reporter name = tonight's lineup; 'last game's lineup' = not updated for tonight yet. Regulars missing from the lineup are treated as out (scratch).",
    "Trends": "Each team's last 10 games: average total goals and how many went 7+ (over 6.5). Context only: tested on 2023-26, recent form adds almost nothing beyond the projection (the model already uses it).",
    "H2H": "Head-to-head since 2020-21: meetings, average total, how many went 7+, and the last 3 scores. Context only: tested on 2023-26, it adds very little beyond the projection.",
    "Lean": "Trend lean: OVER/UNDER when both teams' last-10 7+ rates and the head-to-head 7+ rate run clearly above/below the league's ~45%. Weak signal: it supports or questions the model's pick, it doesn't make one.",
    "SLAM": "Flagged over where both teams are good or great at 5-on-5. Went over 54% (opening line) / 57% (closing line) in 2021-26.",
    "1U": "Flagged over, but not both teams good at 5-on-5. Went over 53% in 2021-26.",
    "AVOID": "Not flagged, or flagged but both teams face strong goalies. These went over only 45-49% in 2021-26.",
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
    """'SLAM' / '1U' / 'AVOID' for a game. Tested 2021-26 at 6/6.5 lines (over %, open / close):
    flagged + both teams good/great at 5v5 54% / 57%; other flagged 53% / 53%; flagged but both teams
    facing strong goalies (Gl bad/trash) 46% / 45%; not flagged 47% / 49%."""
    if not flagged:
        return "AVOID"
    both = lambda stat, ts: all(tier(stat, getattr(r, f"{s}_{stat}", float("nan"))) in ts for s in ("away", "home"))
    if both("gadj", ("bad", "trash")):
        return "AVOID"
    return "SLAM" if both("ev", ("good", "great")) else "1U"


def call_result(r, flagged):
    """(call, outcome) for a finished game vs the logged line: SLAM/1U -> 'W'/'L'/'P' (over won / lost / push);
    AVOID -> 'W' when it stayed under (avoiding was right), 'L' when it went over, 'P' on a push; None without a line."""
    c = call(r, flagged)
    if pd.isna(r.bet_total) or pd.isna(r.final_total):
        return c, None
    over = r.final_total > r.bet_total
    if r.final_total == r.bet_total:
        return c, "P"
    return c, ("L" if over else "W") if c == "AVOID" else ("W" if over else "L")


def tip(label, text=None, cls=""):
    """Label with an explanation that pops up on hover (or tap on a phone)."""
    t = text or TIPS.get(label, "")
    return f"<span class='tip {cls}' tabindex='0' data-tip='{e(t)}'>{label}</span>" if t else label


def e(x):
    return html.escape("" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x))


def price(x):
    return "" if pd.isna(x) else f"{int(x):+d}"


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


def goalie_compact(logged, now):
    """Table version: last name + short badge; full details in the hover text."""
    now = now if isinstance(now, str) else logged
    nm, status = goalie_parts(now)
    st = status.lower()
    last = short_name(nm) if nm != "unknown" else "?"
    if "confirmed" in st and "un" not in st:
        badge = f"<span class='gb ok'>{tip('✓', f'{nm}: confirmed starter (DailyFaceoff).')}</span>"
    elif "likely" in st:
        badge = f"<span class='gb likely'>{tip('Likely', f'{nm}: expected to start, not confirmed yet.')}</span>"
    else:
        badge = f"<span class='gb proj'>{tip('Proj', f'{nm}: starter not announced yet (DailyFaceoff guess or usual starter).')}</span>"
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
    g = g.sort_values(["flag", "proj"], ascending=[False, False])
    final_day = bool(len(g)) and g.final_total.notna().all()
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
    head += (f"<th class='gcol'>{tip('Goalie', 'Starting goalie: ✓ confirmed, Likely, or Proj (not announced). ⇄ = changed after the game was logged.')}</th>"
             f"<th class='num bcol'>{tip('5v5')}</th><th class='num'>{tip('PP')}</th><th class='num'>{tip('Oth')}</th>"
             f"<th class='num'>{tip('Gl', cls='tr')}</th><th class='num'>{tip('B2B', cls='tr')}</th><th class='num'>{tip('Spd', cls='tr')}</th>"
             f"<th class='num'>{tip('Inj', cls='tr')}</th>")
    # fixed widths (%), same section sizes in both tables so they line up:
    # Team 18 | Game/Result 34 | Goalies 17 | Breakdown 31
    widths = ([9, 3.5, 5.5] if final_day else [10, 8]) \
        + ([8.5, 5.5, 5, 7, 8] if final_day else [10, 8, 16]) + [17] + [4.4, 3.9, 3.9, 5.2, 4.8, 4.4, 4.4]
    cols = "<colgroup>" + "".join(f"<col style='width:{w:.3f}%'>" for w in widths) + "</colgroup>"
    sections = (f"<tr class='sec'><th colspan='{3 if final_day else 2}'>Team</th>"
                f"<th class='gcol' colspan='{5 if final_day else 3}'>{'Result' if final_day else 'Game'}</th>"
                f"<th class='gcol'>Goalies</th><th class='bcol' colspan='7'>Projection breakdown</th></tr>")
    body = []
    for i, r in enumerate(g.itertuples()):
        flagged, final = bool(r.flag), not pd.isna(r.final_total)
        cls = ("flagged " if flagged else "") + ("alt" if i % 2 else "")

        def team(side, abbr, proj, score):
            hot = proj >= r.cutoff
            b2b = f" <span class='b2b'>{tip('B2B', TIPS['B2B tag'])}</span>" if _is(getattr(r, f"{side}_b2b")) else ""
            cells = (f"<td class='tm'>{logo(abbr, 22)}<b title='{e(TEAMS.get(abbr, abbr))}'>{e(abbr)}</b>{b2b}</td>")
            if final_day:
                cells += f"<td class='num score-cell'>{int(score)}</td>"
            cells += (f"<td class='num proj{' hot' if hot else ''}'>{tip(f'{proj:.2f}', f'{TEAMS.get(abbr, abbr)} projected goals (high-scoring cutoff {r.cutoff:.2f}).' + (' HIGH: above the cutoff.' if hot else ''))}"
                      f"<span class='hot-dot{'' if hot else ' off'}'>●</span></td>")
            return cells

        def detail(side):
            g_ = lambda c: getattr(r, f"{side}_{c}", float("nan"))
            def adj(v):
                return "–" if pd.isna(v) or abs(v) < 0.0005 else f"{v * 100:+.1f}%"
            cells = f"<td class='gl gcol'>{goalie_compact(g_('goalie'), g_('goalie_now'))}</td>"
            if pd.isna(g_("ev")):
                return cells + "<td class='num muted bcol' colspan='7'>n/a</td>"
            def td(stat, text, extra=""):
                t = tier(stat, g_(stat))
                return f"<td class='num{extra}{' t-' + t if t else ''}'{f' title={chr(39)}{t}{chr(39)}' if t else ''}>{text}</td>"
            return cells + (td("ev", f"{g_('ev'):.2f}", " bcol") + td("pp", f"{g_('pp'):.2f}") + td("oth", f"{g_('oth'):.2f}")
                            + td("gadj", adj(g_("gadj"))) + td("b2badj", adj(g_("b2badj"))) + td("spd", adj(g_("spd")))
                            + td("inj", adj(g_("inj"))))

        c = call(r, flagged)
        callpill = f"<span class='callpill c-{c.lower()}'>{tip(('🔨 ' if c == 'SLAM' else '') + c, TIPS[c])}</span>"
        if final_day:
            t = r.bet_total
            vs = ("<span class='pill muted-pill'>no line</span>" if pd.isna(t) else
                  f"<span class='pill over'>O {line(t)}</span>" if r.final_total > t else
                  f"<span class='pill under'>U {line(t)}</span>" if r.final_total < t else f"<span class='pill'>P {line(t)}</span>")
            moved = "" if pd.isna(r.close_total) or pd.isna(t) or r.close_total == t else (" ↑" if r.close_total > t else " ↓")
            c, res = call_result(r, flagged)
            if res is None:
                outcome = "<span class='muted small'>no line</span>"
            elif c == "AVOID":
                outcome = {"W": "<span class='res W'>✓ under</span>", "L": "<span class='res L'>✗ went over</span>"}.get(res, "<span class='res P'>push</span>")
            elif flagged and not pd.isna(r.result):
                outcome = (f"<span class='res {e(r.result)}'>{e(r.result)} {r.profit:+.2f}u</span>"
                           + ("" if pd.isna(r.profit_best) else f"<br><span class='muted small'>best book {r.profit_best:+.2f}u</span>"))
            else:
                outcome = f"<span class='res {res}'>{res}</span>"
            pick = f"{callpill}<br>{outcome}"
            game = (f"<td class='gcol tot' rowspan='2'><span class='big-total'>{int(r.final_total)}</span>{vs}</td>"
                    f"<td class='num' rowspan='2'>{r.proj:.2f}</td><td class='num' rowspan='2'>{r.p7:.0%}</td>"
                    f"<td rowspan='2' class='nowrap'>{'–' if pd.isna(t) else f'{line(t)} → {line(r.close_total)}{moved}'}</td>"
                    f"<td rowspan='2' class='pickcell'>{pick}</td>")
        else:
            ln = ("<span class='muted'>not posted</span>" if pd.isna(r.bet_total) else
                  f"{line(r.open_total)} → {line(r.bet_total)} <span class='muted'>o{price(r.bet_over)}</span>")
            game = (f"<td class='num gcol big-total' rowspan='2'>{r.proj:.2f}</td><td class='num p7' rowspan='2'>{r.p7:.0%}</td>"
                    f"<td rowspan='2'>{callpill}<br>{ln}</td>")
        ctx = ""  # lineup source and trends / H2H are logged but not shown
        away = team("away", r.away, r.proj_away, r.away_score if final else None) + game + detail("away")
        home = team("home", r.home, r.proj_home, r.home_score if final else None) + detail("home")
        body.append(f"<tbody class='game {cls}'><tr class='away'>{away}</tr><tr class='home'>{home}</tr>"
                    + (f"<tr class='srcrow'><td colspan='22'>{ctx}</td></tr>" if ctx else "") + "</tbody>")
    key = ("<div class='tier-key'>Breakdown (for scoring):" + "".join(f"<span class='t-{t}'>{t}</span>" for t in reversed(TIER_NAMES)) + "</div>")
    return (f"{key}<div class='gtable'><table class='gt'>{cols}<thead>{sections}<tr>{head}</tr></thead>{''.join(body)}</table></div>"
            "<p class='muted small legend'>Two rows per game (away, then home). <span style='color:var(--accent)'>●</span> = team projected "
            "high-scoring. Proj = (5v5 + PP + Oth) × goalie (Gl) × back-to-back (B2B) × team speed (Spd) × injuries (Inj). "
            "Hover or tap any underlined label for an explanation.</p>")


def day_cards(g):
    g = g.sort_values(["flag", "proj"], ascending=[False, False])
    return (f"<div class='cards'>{''.join(game_card(r) for r in g.itertuples())}</div>"
            "<p class='muted small legend'>Breakdown: 5v5 + PP (power play) + Oth (other situations) goals, then Gl = opposing-goalie "
            "adjustment (+ means a below-average goalie), B2B = back-to-back and Inj = injury adjustments → Proj.</p>")


def day_summary(g):
    done = g[g.final_total.notna()]
    flags = int((g.flag).sum())
    parts = [f"{len(g)} games", f"<b>{flags} flag{'s' if flags != 1 else ''}</b>"]
    if len(done):
        wl = done[done.bet_total.notna()]
        parts.append(f"<b>{(wl.final_total > wl.bet_total).sum()} of {len(wl)}</b> went over the line")
        parts.append(f"avg <b>{done.final_total.mean():.1f}</b> goals (projected {done.proj.mean():.1f})")
        fl = done[(done.flag) & done.result.notna()]
        if len(fl):
            parts.append(f"flags <b>{(fl.result == 'W').sum()}-{(fl.result == 'L').sum()}-{(fl.result == 'P').sum()}</b> ({fl.profit.sum():+.2f}u)")
        parts.append(call_record(done))
    return " · ".join(parts)


def call_record(done):
    """'🔨 SLAM 1-0-0 · 1U 0-1-0 · AVOID 6 of 10 stayed under' for finished games (vs the logged line)."""
    res = {"SLAM": [], "1U": [], "AVOID": []}
    for r in done.itertuples():
        c, o = call_result(r, _is(r.flag))
        if o:
            res[c].append(o)
    out = []
    for c in ("SLAM", "1U"):
        x = res[c]
        out.append(f"{'🔨 ' if c == 'SLAM' else ''}{c} <b>{x.count('W')}-{x.count('L')}-{x.count('P')}</b>" if x else f"{c} –")
    a = res["AVOID"]
    out.append(f"AVOID <b>{a.count('W')} of {len(a)}</b> stayed under" if a else "AVOID –")
    return "calls: " + " · ".join(out)


RETRO_NOTE = ("<p class='retro'><b>Retroactive day:</b> added after the fact from pre-game data only (earlier games, that day's "
              "projected starters, opening lines). Shown for reference; it does not count toward the paper trading record.</p>")


def slate(d):
    day = date.today().isoformat()  # Eastern time on GitHub Actions (TZ is set in the workflow)
    g = d[d.date == day]
    if g.empty:
        return f"<p class='muted'>{pd.Timestamp(day):%A, %B %-d}: no games logged for today (off day, or the morning run hasn't happened yet).</p>"
    return f"""<p class='sub'>{pd.Timestamp(day):%A, %B %-d} · {day_summary(g)} · bar tick = high-scoring cutoff
      ({g.cutoff.iloc[0]:.2f} goals){f" · starters as of {e(g.updated_at.dropna().max())}" if g.updated_at.notna().any() else ""}</p>
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
    s = d[d.final_total.notna()].copy()
    if s.empty:
        return "<p class='muted'>No finished games yet.</p>"
    s["band"] = pd.cut(s.proj, [0, 5.5, 6.0, 6.5, 99], labels=["under 5.5", "5.5 – 6.0", "6.0 – 6.5", "6.5+"], right=False)
    rows = []
    for band, x in s.groupby("band", observed=True):
        rows.append(f"<tr><td>{band}</td><td class='num'>{len(x)}</td><td class='num'>{x.proj.mean():.2f}</td>"
                    f"<td class='num'>{x.final_total.mean():.2f}</td><td class='num'>{x.p7.mean():.0%}</td>"
                    f"<td class='num'>{(x.final_total >= 7).mean():.0%}</td></tr>")
    team_err = pd.concat([(s.away_score - s.proj_away).abs(), (s.home_score - s.proj_home).abs()]).mean()
    n_retro = int(retro(s).sum())
    return f"""<div class='tiles'>
      <div class='tile'><div class='label'>{tip('Games settled', 'Finished games in the log (live + retroactive).', 'tl')}</div><div class='num-big'>{len(s)}</div><div class='muted'>{n_retro} retroactive</div></div>
      <div class='tile'><div class='label'>{tip('Avg projected total', 'Average projected total vs average actual goals. Projections run a little low by design; P(7+) corrects for it.', 'tl')}</div><div class='num-big'>{s.proj.mean():.2f}</div><div class='muted'>actual {s.final_total.mean():.2f}</div></div>
      <div class='tile'><div class='label'>{tip('Model P(7+)', 'Average predicted chance of 7+ goals vs how often it actually happened. If the model is calibrated they match.', 'tl')}</div><div class='num-big'>{s.p7.mean():.0%}</div><div class='muted'>actual 7+ rate {(s.final_total >= 7).mean():.0%}</div></div>
      <div class='tile'><div class='label'>{tip('Team goals error', 'Average miss between a team’s projected and actual goals. Hockey is random; ~1.3–1.9 is normal.', 'tl')}</div><div class='num-big'>{team_err:.2f}</div><div class='muted'>avg miss per team</div></div></div>
      <div class='scroll'><table><thead><tr><th>Projected total</th><th>Games</th><th>Avg proj</th><th>Avg goals</th>
      <th>Model P(7+)</th><th>Actual 7+</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
      <ul class='notes'><li>The test that matters is <b>Model P(7+) vs Actual 7+</b>: if the model is calibrated they match, and
      higher projection bands should score more. Projected totals run a little low by design; P(7+) converts them using history.</li>
      <li>Single-game misses are big in hockey, so judge this after a few hundred games, not a few nights.</li></ul>"""


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


def record(d):
    d = d[~retro(d)]  # backfilled days never count toward the live record
    f = d[d.flag]
    s = f[f.result.notna()]
    dec = s[s.result != "P"]
    w, l, p = (s.result == "W").sum(), (s.result == "L").sum(), (s.result == "P").sum()
    sb = s[s.profit_best.notna()]
    c = s.clv.dropna()
    tiles = [
        ("Flagged picks", f"{len(f)}", f"{len(s)} settled"),
        ("Record", f"{w}-{l}-{p}" if len(s) else "–", f"{(dec.result == 'W').mean():.1%} wins" if len(dec) else "no results yet"),
        ("ROI · consensus", pct(s.profit.mean() * 100) if len(s) else "–", f"{s.profit.sum():+.2f}u" if len(s) else "&nbsp;"),
        ("ROI · best book", pct(sb.profit_best.mean() * 100) if len(sb) else "–", f"{sb.profit_best.sum():+.2f}u" if len(sb) else "&nbsp;"),
        ("Line moved our way", f"{(c > 0).mean():.0%}" if len(c) else "–", f"of {len(c)} · target 70%+" if len(c) else "target 70%+"),
    ]
    rec_tips = {"Flagged picks": "Live OVER FLAG picks logged so far (retroactive days excluded).",
                "Record": "Wins-losses-pushes of flagged overs at the logged consensus line.",
                "ROI · consensus": "Profit per unit risked at the logged consensus price. Break-even at −110 needs 52.4% wins.",
                "ROI · best book": "Same picks at the best sportsbook price: what line shopping adds.",
                "Line moved our way": "Share of picks where the closing line moved toward the over after we logged it. The best early sign of a real edge (target 70%+)."}
    tiles_html = "".join(f"<div class='tile'><div class='label'>{tip(a, rec_tips.get(a), 'tl')}</div><div class='num-big'>{b}</div>"
                         f"<div class='muted'>{c_}</div></div>" for a, b, c_ in tiles)
    if len(s):
        rows = "".join(f"""<tr><td>{e(r.date)}</td><td class='matchup'>{logo(r.away, 22)}{logo(r.home, 22)} {e(r.away)} @ {e(r.home)}</td>
            <td class='num'>o{line(r.bet_total)} {price(r.bet_over)}</td><td>{e(r.best_book)} o{line(r.best_total)} {price(r.best_over)}</td>
            <td class='num'>{line(r.close_total)}</td><td class='num'>{int(r.final_total)}</td>
            <td class='res {e(r.result)}'>{e(r.result)}</td><td class='num'>{r.profit:+.2f}</td>
            <td class='num'>{'' if pd.isna(r.profit_best) else f'{r.profit_best:+.2f}'}</td></tr>"""
                       for r in s.sort_values("date", ascending=False).itertuples())
        table = f"""<div class='scroll'><table><thead><tr><th>Date</th><th>Game</th><th>Bet</th><th>Best book</th>
          <th>Close</th><th>Goals</th><th>Result</th><th>Units</th><th>Best</th></tr></thead><tbody>{rows}</tbody></table></div>"""
    else:
        table = "<p class='muted'>No live flagged picks have settled yet. Judge the rule after 50–75 flagged picks, not before.</p>"
    return f"<div class='tiles'>{tiles_html}</div>{table}"


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
.gb.proj{background:var(--ice);color:var(--muted)}.gb.chg{background:var(--neg);color:#fff}
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
.daynav{display:flex;justify-content:space-between;align-items:center;margin:16px 0 0;font-weight:700}
.legend{margin:8px 0 0}
/* table layout: two rows per game, sized to fit a desktop screen */
.gtable{background:var(--card);border:4px solid color-mix(in srgb,var(--muted) 60%,transparent);border-radius:12px;overflow-x:auto}
table.gt{font-size:12.5px;border-collapse:separate;border-spacing:0;width:100%;table-layout:fixed}
.gt td,.gt th{overflow:hidden;text-overflow:ellipsis}
.gt thead tr:not(.sec) th{white-space:normal;line-height:1.25;vertical-align:bottom}
.gt td[rowspan]{white-space:normal}.gt td[rowspan].nowrap,.gt td[rowspan].tot{white-space:nowrap}
.gt td.tot{padding-left:3px;padding-right:3px}
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
.tier-key .t-mid{border:1px solid var(--line)}
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
.callpill{display:inline-block;font-size:10px;font-weight:800;padding:1px 8px;border-radius:999px;margin-bottom:2px;letter-spacing:.04em}
.callpill.c-slam{background:var(--gold);color:#1a1200}.callpill.c-1u{border:1.5px solid var(--gold);color:var(--ink)}
.callpill.c-avoid{border:1px solid var(--line);color:var(--muted);font-weight:700}.callpill .tip{border-bottom:none}
.flagpill{display:inline-block;background:var(--gold);color:#1a1200;font-size:10px;font-weight:800;padding:1px 7px;border-radius:999px;margin-bottom:2px}
.gt tr.srcrow td{padding:0 8px 6px 38px;white-space:nowrap}.gt tr.srcrow .lineup-src{margin-top:1px;font-size:10.5px}
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
<a href="https://github.com/Prezbo8/nhl-total-model">github.com/Prezbo8/nhl-total-model</a></footer>
</div></body></html>"""


def build():
    d = paper.read_log()
    body = f"""
<header class="hero"><h1>NHL Total Model</h1></header>

<section><h2>Today's slate</h2>{slate(d)}</section>

<section><h2>Yesterday's results</h2>{yesterday(d)}</section>

<section><h2>Paper trading record</h2>{record(d)}</section>

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
    days = sorted(d.date.unique())
    os.makedirs(os.path.join(os.path.dirname(OUT), "days"), exist_ok=True)
    for day in days:
        with open(os.path.join(os.path.dirname(OUT), "days", f"{day}.html"), "w") as f:
            f.write(day_page(d, day, days))
    print(f"wrote {OUT} + {len(days)} day pages")


if __name__ == "__main__":
    build()
