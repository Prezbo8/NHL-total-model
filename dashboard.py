"""Build docs/index.html (GitHub Pages dashboard) from paper_trades.csv.

  python3 dashboard.py
"""
import html
import os
from datetime import date, datetime

import pandas as pd

import paper

OUT = "docs/index.html"

# backtest numbers (strict 2020-21+ data, frozen rule) from history.py / compare.py, Oct 2 2026
BACKTEST = [  # season, open bets, open ROI, close bets, close ROI
    ("2021-22", 341, 3.2, 352, 4.4), ("2022-23", None, None, 238, 1.7), ("2023-24", 12, 6.5, 18, -5.7),
    ("2024-25", 47, 12.9, 47, 16.3), ("2025-26", 136, 7.8, 150, 3.6),
]

TEAMS = {
    "ANA": "Anaheim Ducks", "ARI": "Arizona Coyotes", "BOS": "Boston Bruins", "BUF": "Buffalo Sabres",
    "CGY": "Calgary Flames", "CAR": "Carolina Hurricanes", "CHI": "Chicago Blackhawks", "COL": "Colorado Avalanche",
    "CBJ": "Columbus Blue Jackets", "DAL": "Dallas Stars", "DET": "Detroit Red Wings", "EDM": "Edmonton Oilers",
    "FLA": "Florida Panthers", "LAK": "Los Angeles Kings", "MIN": "Minnesota Wild", "MTL": "Montréal Canadiens",
    "NSH": "Nashville Predators", "NJD": "New Jersey Devils", "NYI": "New York Islanders", "NYR": "New York Rangers",
    "OTT": "Ottawa Senators", "PHI": "Philadelphia Flyers", "PIT": "Pittsburgh Penguins", "SJS": "San Jose Sharks",
    "SEA": "Seattle Kraken", "STL": "St. Louis Blues", "TBL": "Tampa Bay Lightning", "TOR": "Toronto Maple Leafs",
    "UTA": "Utah Mammoth", "VAN": "Vancouver Canucks", "VGK": "Vegas Golden Knights", "WSH": "Washington Capitals",
    "WPG": "Winnipeg Jets",
}
SCALE = 4.5  # projected-goal bars run 0 -> 4.5 goals


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
    badge = ("<span class='gb ok'>✓ Confirmed</span>" if "confirmed" in st and "un" not in st else
             "<span class='gb likely'>Likely</span>" if "likely" in st else "<span class='gb proj'>Projected</span>")
    old_nm, _ = goalie_parts(logged)
    changed = (f"<span class='gb chg' title='Projection was made with {e(old_nm)} in net'>Changed from {e(old_nm)}</span>"
               if old_nm != nm and old_nm != "unknown" else "")
    return f"<div class='goalie'>{e(nm)} {badge}{changed}</div>"


def team_row(abbr, proj, cutoff, goalie, goalie_now=None, b2b=False, score=None):
    hot = proj >= cutoff
    right = (f"<div class='score'>{score}<small>proj {proj:.2f}{' · HIGH' if hot else ''}</small></div>" if score is not None else
             f"<div class='pg'><b>{proj:.2f}</b>{'<span class=hot-tag>HIGH</span>' if hot else ''}</div>")
    on_b2b = str(b2b).strip().lower() in ("true", "1", "1.0")  # CSV may hold bools, strings or floats
    tag = "<span class='b2b' title='Played yesterday: model cuts this team’s scoring ~8%'>B2B</span>" if on_b2b else ""
    return f"""<div class='team'>
      {logo(abbr)}
      <div class='tname'><div class='full'>{name(abbr)} {tag}</div>{goalie_html(goalie, goalie_now)}
        {goal_bar(proj, cutoff, abbr)}</div>
      {right}</div>"""


def breakdown(r, flagged):
    if pd.isna(getattr(r, "away_ev", float("nan"))):
        return "<div class='why'><div class='why-h'>Projection breakdown</div><p class='muted small'>Not available for this game.</p></div>"
    def row(side, abbr, proj):
        g = lambda c: getattr(r, f"{side}_{c}")
        adj = lambda v: f"{v * 100:+.1f}%" if abs(v) >= 0.0005 else "–"
        return (f"<tr><td>{logo(abbr, 18)} {e(abbr)}</td><td class='num'>{g('ev'):.2f}</td><td class='num'>{g('pp'):.2f}</td>"
                f"<td class='num'>{g('oth'):.2f}</td><td class='num'>{adj(g('gadj'))}</td><td class='num'>{adj(g('b2badj'))}</td>"
                f"<td class='num'><b>{proj:.2f}</b></td></tr>")
    return f"""<div class='why'><div class='why-h'>{'Why it’s flagged' if flagged else 'Projection breakdown'}</div>
      <table><thead><tr><th>Team</th><th class='num'>5v5</th><th class='num'>PP</th><th class='num'>Oth</th>
      <th class='num' title='Opposing goalie adjustment'>Gl</th><th class='num'>B2B</th><th class='num'>Proj</th></tr></thead>
      <tbody>{row('away', r.away, r.proj_away)}{row('home', r.home, r.proj_home)}</tbody></table></div>"""


def game_card(r):
    flagged = r.flag
    final = not pd.isna(r.final_total)
    ascore = int(r.away_score) if final else None
    hscore = int(r.home_score) if final else None
    rows = (team_row(r.away, r.proj_away, r.cutoff, r.away_goalie, getattr(r, "away_goalie_now", None), getattr(r, "away_b2b", False), ascore)
            + team_row(r.home, r.proj_home, r.cutoff, r.home_goalie, getattr(r, "home_goalie_now", None), getattr(r, "home_b2b", False), hscore))
    def kv(label, value):
        return f"<div class='kv'><span>{label}</span><b>{value}</b></div>"
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
                kv("Best over", f"{book(r.best_book)} o{line(r.best_total)} {price(r.best_over)}") if not pd.isna(r.best_total)
                else kv("Best over", "<span class='muted'>–</span>"), blank]
    bar = f"<div class='flagbar'>★ OVER FLAG · {'over' if final else 'bet over'} {line(r.bet_total)}</div>" if flagged else ""
    return f"""<article class='card{' flagged' if flagged else ''}'>{bar or "<div class='flagbar empty'></div>"}{rows}
      <div class='meta'>{''.join(meta)}</div>{breakdown(r, flagged)}</article>"""


def day_cards(g):
    g = g.sort_values(["flag", "proj"], ascending=[False, False])
    return (f"<div class='cards'>{''.join(game_card(r) for r in g.itertuples())}</div>"
            "<p class='muted small legend'>Breakdown: 5v5 + PP (power play) + Oth (other situations) goals, then Gl = opposing-goalie "
            "adjustment (+ means a below-average goalie) and B2B = back-to-back adjustment → Proj.</p>")


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
      <div class='tile'><div class='label'>Games settled</div><div class='num-big'>{len(s)}</div><div class='muted'>{n_retro} retroactive</div></div>
      <div class='tile'><div class='label'>Avg projected total</div><div class='num-big'>{s.proj.mean():.2f}</div><div class='muted'>actual {s.final_total.mean():.2f}</div></div>
      <div class='tile'><div class='label'>Model P(7+)</div><div class='num-big'>{s.p7.mean():.0%}</div><div class='muted'>actual 7+ rate {(s.final_total >= 7).mean():.0%}</div></div>
      <div class='tile'><div class='label'>Team goals error</div><div class='num-big'>{team_err:.2f}</div><div class='muted'>avg miss per team</div></div></div>
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
    tiles_html = "".join(f"<div class='tile'><div class='label'>{a}</div><div class='num-big'>{b}</div><div class='muted'>{c_}</div></div>"
                         for a, b, c_ in tiles)
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
    return f"""<div class='scroll'><table><thead><tr><th>Season</th><th>Bets at open</th><th>ROI at open</th>
      <th>Bets at close</th><th>ROI at close</th></tr></thead>
      <tbody>{rows}<tr class='total'><td>2021–26</td><td class='num'>536</td><td class='num pos'>+5.3%</td>
      <td class='num'>805</td><td class='num pos'>+3.9%</td></tr></tbody></table></div>
      <ul class='notes'>
        <li><b>Open</b> = betting the first line books post; <b>close</b> = the final line before puck drop. Counts differ
            because lines move into or out of 6 / 6.5 during the day.</li>
        <li>~55% wins; uncertainty about ±3–4% ROI. Line shopping added about <b>+2.2 pts</b> on the same picks.</li>
        <li>No 2022-23 opening lines in the data. With pre-2020 data the same rule was about break-even (2016–21).</li>
      </ul>"""


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
.card{position:relative;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 14px 12px;overflow:hidden;
  display:flex;flex-direction:column}
.card.flagged{border:2px solid var(--gold);background:linear-gradient(180deg,var(--gold-soft),var(--card) 55%)}
.flagbar{margin:-14px -14px 8px;padding:6px 14px;min-height:29px;background:var(--gold);color:#1a1200;font-size:12px;font-weight:800;letter-spacing:.05em}
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
.meta .kv b{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
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
ul.archive{list-style:none;margin:0;padding:0}ul.archive li{padding:8px 0;border-bottom:1px solid var(--line)}
ul.archive li:last-child{border-bottom:none}
"""


def shell(title, body):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<link rel="icon" href="https://assets.nhle.com/logos/nhl/svg/NHL_light.svg"><style>{CSS}</style></head>
<body><div class="wrap">{body}
<footer>Paper trading only, not betting advice · Team logos © NHL and its teams ·
<a href="https://github.com/Prezbo8/nhl-total-model">github.com/Prezbo8/nhl-total-model</a></footer>
</div></body></html>"""


def build():
    d = paper.read_log()
    live = d[~retro(d)]
    today = d[d.date == date.today().isoformat()]
    settled = live[(live.flag) & live.result.notna()]
    body = f"""
<header class="hero">
  <h1>NHL Total Model</h1>
  <p>Over/under projections, OVER flags and live paper trading · updated {datetime.now():%b %-d, %Y %-I:%M %p} ET</p>
  <div class="stats">
    <div class="stat"><b>{int((today.flag).sum()) if len(today) else 0}</b><span>flags today</span></div>
    <div class="stat"><b>{len(today)}</b><span>games today</span></div>
    <div class="stat"><b>{(settled.result == 'W').sum()}-{(settled.result == 'L').sum()}-{(settled.result == 'P').sum()}</b><span>live record</span></div>
  </div>
</header>

<section><div class="rule"><b>The rule:</b> bet the <b>OVER</b> only when the consensus line is <b>6 or 6.5</b> (never 5.5) and
<b>both teams</b> are projected high-scoring (bar past the tick). Take it at the <b>best over</b> book. Check the goalies:
a <span class='gb chg'>Changed</span> tag means the starter differs from the one the projection used.</div></section>

<section><h2>Yesterday's results</h2>{yesterday(d)}</section>

<section><h2>Today's slate</h2>{slate(d)}</section>

<section><h2>Paper trading record</h2>{record(d)}</section>

<section><h2>Projection accuracy</h2><div class="panel">{accuracy(d)}</div></section>

<section><h2>Archive</h2><div class="panel">{archive(d)}</div></section>

<section><h2>Backtest · frozen rule, 2020+ data only</h2><div class="panel">{backtest()}</div></section>

<section><h2>How it works</h2><div class="panel">
<p style="margin:0">Each team's goals are projected separately for <b>5-on-5</b> (expected goals + actual goals for/against per 60) and the
<b>power play</b> (PP and PK efficiency × penalties drawn and taken), plus other situations. The opposing <b>starting goalie's</b>
goals saved above expected scales goals allowed, and <b>back-to-backs</b> cut the tired team's scoring ~8% (opponent +6.5%).
Data from the 2020-21 season onward only (MoneyPuck, NHL API, DailyFaceoff, Action Network). Runs on GitHub Actions at 11 AM and 5 PM ET.</p>
<dl>
<div><dt>Projected goals bar</dt><dd>Each team's projected goals on a 0–4.5 scale. The tick marks the high-scoring cutoff; a solid bar means past it.</dd></div>
<div><dt>P(7+)</dt><dd>Model's chance of 7+ total goals: wins an over 6.5 and an over 6 (exactly 6 pushes an over 6). NHL average ≈ 45%.</dd></div>
<div><dt>OVER FLAG</dt><dd>Both teams past the cutoff and the line is 6 or 6.5. These are the picks that count in the record.</dd></div>
<div><dt>Goalie badges</dt><dd>✓ Confirmed / Likely / Projected starter, from DailyFaceoff, refreshed every run. "Changed" = different from the starter the projection used.</dd></div>
<div><dt>B2B</dt><dd>Team played yesterday: its projected scoring is cut ~8% and its opponent's raised ~6.5%.</dd></div>
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
