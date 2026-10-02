"""Build docs/index.html (GitHub Pages dashboard) from paper_trades.csv.

  python3 dashboard.py
"""
import html
import os
from datetime import date

import pandas as pd

import paper

OUT = "docs/index.html"

# backtest numbers (strict 2020-21+ data, frozen rule) from history.py / compare.py, Oct 2 2026
BACKTEST = [  # season, open bets, open ROI, close bets, close ROI  (calibrated goalies, G_SHRINK=200; Oct 2 2026)
    ("2021-22", 428, -1.8, 434, 0.2), ("2022-23", None, None, 256, 4.5), ("2023-24", 11, 1.1, 19, -10.6),
    ("2024-25", 44, 6.6, 44, 10.4), ("2025-26", 137, 5.7, 150, 3.5),
]

from teams import TEAMS  # noqa: E402

SCALE = 4.5  # projected-goal bars run 0 -> 4.5 goals


TIPS = {
    "Proj total": "Projected total goals for the game (away + home), from the model.",
    "P(7+)": "Model's chance of 7 or more total goals. 7+ wins an over 6.5 and an over 6 (exactly 6 pushes an over 6). NHL average ≈ 45%.",
    "Line": "Consensus total: opening line → line when logged (on results: logged line → closing line). ↑/↓ = which way it moved.",
    "Over price": "Consensus price for the over at the logged line (American odds: −120 = risk 120 to win 100; +110 = risk 100 to win 110).",
    "Best over": "Best-value over at 6 or 6.5 across DraftKings, FanDuel, BetRivers, BetMGM and Caesars, chosen with the model's probabilities (an over 6 can push).",
    "Total goals": "Final total goals (a shootout winner counts as one goal, as sportsbooks settle it).",
    "vs line": "Did the game go over or under the line that was logged before it started?",
    "Pick": "Result of the OVER FLAG bet at the logged consensus line, in units (1 unit risked).",
    "Best book": "Same pick at the best sportsbook price (the 'Best over' book), in units.",
    "Team": "Team, away first then home.",
    "5v5": "Projected even-strength (5-on-5) goals: team's 5v5 attack × opponent's 5v5 defense × 5v5 minutes.",
    "PP": "Projected power-play goals: PP efficiency × opponent's penalty kill × power-play time (penalties drawn × opponent's penalties taken).",
    "Oth": "Other situations (4-on-4, 3-on-3 overtime, empty nets, 5-on-3): league average, same for every team.",
    "Gl": "Opposing-goalie adjustment. + = facing a below-average goalie (more goals), − = facing an above-average goalie.",
    "B2B": "Back-to-back adjustment: −8% if this team played yesterday, +6.5% if its opponent did.",
    "Inj": "Injury adjustment: this team's injured players (less scoring) plus the opponent's injured defenders (more scoring). – = game logged before injuries were tracked.",
    "Proj": "Projected goals = (5v5 + PP + Oth) × goalie × back-to-back × injury adjustments.",
    "HIGH": "Projected 2.95+ goals (top 40% of last season's team projections). An OVER FLAG needs both teams HIGH.",
    "Confirmed": "Starter confirmed (DailyFaceoff). Refreshed every run.",
    "Likely": "Starter expected but not confirmed yet (DailyFaceoff).",
    "Projected": "Starter not announced yet: DailyFaceoff's guess, or this team's usual recent starter.",
    "OVER FLAG": "The model's pick: both teams projected high-scoring and the line is 6 or 6.5. Bet the OVER at the 'Best over' book. These are the picks that count in the record.",
    "B2B tag": "Played yesterday: the model cuts this team's scoring ~8% and raises its opponent's ~6.5%.",
}


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
            last = e(name.split(" ", 1)[-1])
            effect = f"{-d_off * 100:+.1f}% GF" if abs(d_off) >= abs(d_def) else f"{d_def * 100:+.1f}% GA"
            items.append(f"<span>{last} {effect}</span>")
        more = players_out[3:]
        if more:
            items.append(f"<span>+{len(more)} more</span>")
        parts.append(f"<span class='inj out'>Out: {', '.join(items)}</span>")
    if isinstance(dtd, str) and dtd and len(players_out) < 3:
        parts.append("<span class='inj dtd'>DTD: "
                     f"{', '.join(e(n.split(' ', 1)[-1]) for n in dtd.split(', ')[:2])}</span>")
    if not parts:
        return "<div class='injuries'></div>"
    full = []
    for name, d_off, d_def in players_out:
        full.append(f"{name}: team scoring {-d_off * 100:+.1f}%, opponent scoring {d_def * 100:+.1f}%")
    if isinstance(dtd, str) and dtd:
        full.append(f"Day-to-day (usually plays, not adjusted): {dtd}")
    text = ("Out = injured / suspended, already taken out of the projection. GF = his team's goals, GA = goals against. "
            + " | ".join(full))
    return f"<div class='tip injwrap' tabindex='0' data-tip='{e(text)}'><div class='injuries'>{' '.join(parts)}</div></div>"


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
                f"<td class='num'>{'–' if pd.isna(g('inj')) else adj(g('inj'))}</td>"
                f"<td class='num'><b>{proj:.2f}</b></td></tr>")
    return f"""<div class='why'><div class='why-h'>{'Why it’s flagged' if flagged else 'Projection breakdown'}</div>
      <table><thead><tr><th>{tip('Team', cls='tl')}</th><th class='num'>{tip('5v5')}</th><th class='num'>{tip('PP')}</th>
      <th class='num'>{tip('Oth')}</th><th class='num'>{tip('Gl')}</th><th class='num'>{tip('B2B')}</th>
      <th class='num'>{tip('Inj')}</th><th class='num'>{tip('Proj', cls='tr')}</th></tr></thead>
      <tbody>{row('away', r.away, r.proj_away)}{row('home', r.home, r.proj_home)}</tbody></table></div>"""


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
    return " · ".join(parts)


RETRO_NOTE = ("<p class='retro'><b>Retroactive day:</b> added after the fact from pre-game data only (earlier games, that day's "
              "projected starters, opening lines). Shown for reference; it does not count toward the paper trading record.</p>")


def slate(d):
    day = date.today().isoformat()  # Eastern time on GitHub Actions (TZ is set in the workflow)
    g = d[d.date == day]
    if g.empty:
        return f"<p class='muted'>{pd.Timestamp(day):%A, %B %-d}: no games logged for today (off day, or the morning run hasn't happened yet).</p>"
    return f"""<p class='sub'>{pd.Timestamp(day):%A, %B %-d} · {day_summary(g)} · bar tick = high-scoring cutoff
      ({g.cutoff.iloc[0]:.2f} goals){f" · starters as of {e(g.updated_at.dropna().max())}" if g.updated_at.notna().any() else ""}</p>
      {day_cards(g)}"""


def yesterday(d):
    done = d[d.final_total.notna()]
    if done.empty:
        return "<p class='muted'>No finished games yet.</p>"
    day = done.date.max()
    g = d[d.date == day]
    return f"""{RETRO_NOTE if retro(g).any() else ""}<p class='sub'>{pd.Timestamp(day):%A, %B %-d} · {day_summary(g)}
      · <a href='days/{e(day)}.html'>day page →</a></p>{day_cards(g)}"""


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
      {RETRO_NOTE if retro(g).any() else ""}<section>{day_cards(g)}</section>"""
    return shell(f"NHL Total Model · {day}", body)


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
      <tbody>{rows}<tr class='total'><td>2021–26</td><td class='num'>620</td><td class='num pos'>+0.5%</td>
      <td class='num'>903</td><td class='num pos'>+2.3%</td></tr></tbody></table></div>
      <ul class='notes'>
        <li><b>Open</b> = betting the first line books post; <b>close</b> = the final line before puck drop. Counts differ
            because lines move into or out of 6 / 6.5 during the day.</li>
        <li>53–55% wins; uncertainty about ±3–4% ROI, so the past edge is small and not proven. Line shopping added about
            <b>+2.2 pts</b> on the same picks. Goalie ratings are calibrated to match how goalies actually play.</li>
        <li>No 2022-23 opening lines in the data. With pre-2020 data the same rule was about break-even (2016–21).</li>
      </ul>"""


SCRIPT = """<script>
// keep hover explanations on screen: anchor them left/right when near an edge
document.addEventListener("mouseover", show); document.addEventListener("focusin", show);
function show(ev) {
  const t = ev.target.closest && ev.target.closest(".tip"); if (!t) return;
  const r = t.getBoundingClientRect(), w = Math.min(250, window.innerWidth - 24);
  t.classList.remove("tl", "tr");
  if (r.left + r.width / 2 - w / 2 < 8) t.classList.add("tl");
  else if (r.left + r.width / 2 + w / 2 > window.innerWidth - 8) t.classList.add("tr");
  t.classList.toggle("down", r.top < 140);
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
.wrap{max-width:1180px;margin:0 auto;padding:0 16px 64px}
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
.tip{position:relative;cursor:help;border-bottom:1px dotted currentColor;outline:none}
.tip::after{content:attr(data-tip);position:absolute;bottom:calc(100% + 8px);left:50%;transform:translateX(-50%);
  width:max-content;max-width:250px;white-space:normal;text-transform:none;letter-spacing:0;font-size:12px;font-weight:500;
  line-height:1.4;text-align:left;color:#f2f5f9;background:#0f1a2a;border:1px solid rgba(255,255,255,.18);padding:7px 10px;
  border-radius:8px;box-shadow:0 8px 22px rgba(0,0,0,.3);opacity:0;visibility:hidden;transition:opacity .12s;z-index:60;pointer-events:none}
.tip:hover::after,.tip:focus::after,.tip:focus-within::after{opacity:1;visibility:visible}
.tip.tl::after{left:0;transform:none}.tip.tr::after{left:auto;right:0;transform:none}
.tip.down::after{bottom:auto;top:calc(100% + 8px)}
.tip.injwrap{display:block;border-bottom:none}.tip.injwrap .injuries{text-decoration:underline dotted;text-underline-offset:2px}
.gb .tip,.b2b .tip,.flagbar .tip,.hot-tag .tip{border-bottom-color:rgba(127,127,127,.6)}
ul.archive{list-style:none;margin:0;padding:0}ul.archive li{padding:8px 0;border-bottom:1px solid var(--line)}
ul.archive li:last-child{border-bottom:none}
"""


def shell(title, body):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<link rel="icon" href="https://assets.nhle.com/logos/nhl/svg/NHL_light.svg"><style>{CSS}</style></head>
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
goals saved above expected scales goals allowed, and <b>back-to-backs</b> cut the tired team's scoring ~8% (opponent +6.5%).
Data from the 2020-21 season onward only (MoneyPuck, NHL API, DailyFaceoff, Action Network). Runs on GitHub Actions every 2 hours from 11 AM to 9 PM ET.</p>
<dl>
<div><dt>Projected goals bar</dt><dd>Each team's projected goals on a 0–4.5 scale. The tick marks the high-scoring cutoff; a solid bar means past it.</dd></div>
<div><dt>P(7+)</dt><dd>Model's chance of 7+ total goals: wins an over 6.5 and an over 6 (exactly 6 pushes an over 6). NHL average ≈ 45%.</dd></div>
<div><dt>OVER FLAG</dt><dd>Both teams past the cutoff and the line is 6 or 6.5. These are the picks that count in the record.</dd></div>
<div><dt>Goalie badges</dt><dd>✓ Confirmed / Likely / Projected starter, from DailyFaceoff, refreshed every run (every 2 hours). "Changed" = different from the starter the projection used.</dd></div>
<div><dt>B2B</dt><dd>Team played yesterday: its projected scoring is cut ~8% and its opponent's raised ~6.5%.</dd></div>
<div><dt>Injuries</dt><dd>From ESPN's injury list. Players who are Out, on IR or suspended are replaced by a replacement-level skater. GF = change to his team's scoring, GA = change to goals against (shown for whichever is bigger; hover for both). Day-to-day players are shown but not adjusted.</dd></div>
<div><dt>Breakdown</dt><dd>Each team's goals = (5-on-5 + power play + other situations) × opposing-goalie adjustment × back-to-back adjustment. A + goalie number means the opposing goalie has been below average.</dd></div>
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
