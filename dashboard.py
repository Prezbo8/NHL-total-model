"""Build docs/index.html (GitHub Pages dashboard) from paper_trades.csv.

  python3 dashboard.py
"""
import html
import os
from datetime import datetime

import pandas as pd

import paper

OUT = "docs/index.html"

# backtest numbers (strict 2020-21+ data, frozen rule) from history.py / compare.py, Oct 2 2026
BACKTEST = [  # season, open bets, open ROI, close bets, close ROI
    ("2021-22", 341, 3.2, 352, 4.4), ("2022-23", None, None, 238, 1.7), ("2023-24", 12, 6.5, 18, -5.7),
    ("2024-25", 47, 12.9, 47, 16.3), ("2025-26", 136, 7.8, 150, 3.6),
]
GRADE = [("Backtest results (2020+, with line shopping)", 30, 89), ("Beats the market", 25, 88),
         ("Stats and method", 15, 94), ("How trustworthy the edge is", 20, 70), ("Live proof", 10, 70)]


def e(x):
    return html.escape("" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x))


def price(x):
    return "" if pd.isna(x) else f"{int(x):+d}"


def line(t):
    return "" if pd.isna(t) else f"{t:g}"


def pct(x, d=1):
    return "–" if x is None or pd.isna(x) else f"{x:+.{d}f}%"


def slate(d):
    if d.empty:
        return "<p class='muted'>No games logged yet.</p>"
    day = d.date.max()
    g = d[d.date == day].sort_values("proj", ascending=False)
    rows = []
    for r in g.itertuples():
        ha = "<span class='hi'>+</span>" if r.proj_away >= r.cutoff else ""
        hh = "<span class='hi'>+</span>" if r.proj_home >= r.cutoff else ""
        best = (f"{e(r.best_book)} o{line(r.best_total)} {price(r.best_over)}" if not pd.isna(r.best_total) else "–")
        flag = "<span class='flag'>OVER FLAG</span>" if r.flag == True else ""
        res = ""
        if not pd.isna(r.final_total):
            res = f"{int(r.away_score)}-{int(r.home_score)} = {int(r.final_total)}"
        rows.append(f"""<tr class='{"flagged" if r.flag == True else ""}'>
          <td><b>{e(r.away)} @ {e(r.home)}</b> {flag}</td>
          <td class='num'>{r.proj:.2f}</td>
          <td class='num'>{r.proj_away:.2f}{ha} / {r.proj_home:.2f}{hh}</td>
          <td class='num'>{r.p7:.1%}</td>
          <td class='num'>{line(r.open_total)} → {line(r.bet_total)} <span class='muted'>o{price(r.bet_over)}</span></td>
          <td>{best}</td>
          <td class='small'>{e(r.away_goalie)}<br>{e(r.home_goalie)}</td>
          <td class='num'>{res or "<span class='muted'>pending</span>"}</td></tr>""")
    cutoff = g.cutoff.iloc[0]
    return f"""<p class='muted'>{e(day)} · high-scoring = projected <b>{cutoff:.2f}+</b> goals (marked <span class='hi'>+</span>) ·
      logged {e(g.logged_at.min())}</p>
      <div class='scroll'><table><thead><tr><th>Game</th><th>Proj</th><th>Away / home</th><th>P(7+)</th>
      <th>Open → logged line</th><th>Best over 6/6.5</th><th>Starters (away / home)</th><th>Final</th></tr></thead>
      <tbody>{''.join(rows)}</tbody></table></div>"""


def yesterday(d):
    """Most recent day with final scores: every logged game's result vs the line."""
    done = d[d.final_total.notna()]
    if done.empty:
        return ("<p class='muted'>No finished games yet. Each morning's run fills in the previous night's final "
                "scores here (first results: the Oct 2 games, after the Oct 3 morning run).</p>")
    day = done.date.max()
    g = done[done.date == day].sort_values("proj", ascending=False)
    is_retro = retro(g).any()
    rows, overs, n_line = [], 0, 0
    for r in g.itertuples():
        vs = ""
        if not pd.isna(r.bet_total):
            n_line += 1
            if r.final_total > r.bet_total:
                vs, overs = "<span class='pos'><b>OVER</b></span>", overs + 1
            elif r.final_total < r.bet_total:
                vs = "<span class='neg'><b>UNDER</b></span>"
            else:
                vs = "<b>PUSH</b>"
        flag = "<span class='flag'>OVER FLAG</span>" if r.flag == True else ""
        pick = ""
        if r.flag == True and not pd.isna(r.result):
            pick = f"<span class='res {e(r.result)}'>{e(r.result)}</span> {r.profit:+.2f}u"
            if not pd.isna(r.profit_best):
                pick += f" <span class='muted'>(best book {r.profit_best:+.2f}u)</span>"
        moved = ""
        if not pd.isna(r.close_total) and not pd.isna(r.bet_total) and r.close_total != r.bet_total:
            moved = " ↑" if r.close_total > r.bet_total else " ↓"
        rows.append(f"""<tr class='{"flagged" if r.flag == True else ""}'>
          <td><b>{e(r.away)} @ {e(r.home)}</b> {flag}</td>
          <td class='num'>{r.proj:.2f}</td><td class='num'>{r.p7:.1%}</td>
          <td class='num'>{line(r.bet_total)} → {line(r.close_total)}{moved}</td>
          <td class='num'>{e(r.away)} {int(r.away_score)} – {int(r.home_score)} {e(r.home)}</td>
          <td class='num'><b>{int(r.final_total)}</b></td><td>{vs}</td><td>{pick or "<span class='muted'>–</span>"}</td></tr>""")
    flagged = g[(g.flag == True) & g.result.notna()]
    fl = (f"Flagged picks: <b>{(flagged.result == 'W').sum()}-{(flagged.result == 'L').sum()}-{(flagged.result == 'P').sum()}</b>, "
          f"{flagged.profit.sum():+.2f}u" if len(flagged) else "No flagged picks")
    note = ("<p class='retro'><b>Retroactive:</b> this day was added after the fact from pre-game data only "
            "(ratings from earlier games, that day's projected starters, opening lines). It's shown for reference and "
            "does <b>not</b> count toward the paper trading record.</p>") if is_retro else ""
    return f"""{note}<p class='muted'>{e(day)} · {len(g)} games · <b>{overs} of {n_line}</b> went over the logged line ·
      avg total <b>{g.final_total.mean():.1f}</b> goals (model projected {g.proj.mean():.1f}) · {fl}</p>
      <div class='scroll'><table><thead><tr><th>Game</th><th>Proj</th><th>P(7+)</th><th>Line (logged → close)</th>
      <th>Final</th><th>Goals</th><th>vs line</th><th>Pick result</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"""


def retro(d):
    return d.logged_at.astype(str).str.contains("retroactively")


def record(d):
    d = d[~retro(d)]  # backfilled days are shown in results but never count toward the live record
    f = d[d.flag == True]
    s = f[f.result.notna()]
    dec = s[s.result != "P"]
    w, l, p = (s.result == "W").sum(), (s.result == "L").sum(), (s.result == "P").sum()
    sb = s[s.profit_best.notna()]
    c = s.clv.dropna()
    tiles = [
        ("Flagged picks", f"{len(f)}", f"{len(s)} settled"),
        ("Record", f"{w}-{l}-{p}" if len(s) else "–", f"{(dec.result == 'W').mean():.1%} wins" if len(dec) else "no results yet"),
        ("ROI (consensus)", pct(s.profit.mean() * 100) if len(s) else "–", f"{s.profit.sum():+.2f}u" if len(s) else ""),
        ("ROI (best book)", pct(sb.profit_best.mean() * 100) if len(sb) else "–", f"{sb.profit_best.sum():+.2f}u" if len(sb) else ""),
        ("Line moved our way", f"{(c > 0).mean():.0%}" if len(c) else "–", f"of {len(c)} · target 70%+"),
    ]
    tiles_html = "".join(f"<div class='tile'><div class='label'>{a}</div><div class='big'>{b}</div><div class='muted'>{c_}</div></div>"
                         for a, b, c_ in tiles)
    if len(s):
        rows = "".join(f"""<tr><td>{e(r.date)}</td><td>{e(r.away)} @ {e(r.home)}</td>
            <td class='num'>o{line(r.bet_total)} {price(r.bet_over)}</td><td>{e(r.best_book)} o{line(r.best_total)} {price(r.best_over)}</td>
            <td class='num'>{line(r.close_total)}</td><td class='num'>{int(r.final_total)}</td>
            <td class='res {e(r.result)}'>{e(r.result)}</td><td class='num'>{r.profit:+.2f}</td>
            <td class='num'>{'' if pd.isna(r.profit_best) else f'{r.profit_best:+.2f}'}</td></tr>"""
                       for r in s.sort_values("date", ascending=False).itertuples())
        table = f"""<div class='scroll'><table><thead><tr><th>Date</th><th>Game</th><th>Bet</th><th>Best book</th>
          <th>Close</th><th>Goals</th><th>Result</th><th>Units</th><th>Units (best)</th></tr></thead><tbody>{rows}</tbody></table></div>"""
    else:
        table = "<p class='muted'>No flagged picks have settled yet. Judge the rule after 50–75 flagged picks, not before.</p>"
    return f"<div class='tiles'>{tiles_html}</div>{table}"


def backtest():
    rows = "".join(f"<tr><td>{s}</td><td class='num'>{'–' if ob is None else ob}</td><td class='num {'' if oroi is None else ('pos' if oroi > 0 else 'neg')}'>{pct(oroi)}</td>"
                   f"<td class='num'>{cb}</td><td class='num {'pos' if croi > 0 else 'neg'}'>{pct(croi)}</td></tr>"
                   for s, ob, oroi, cb, croi in BACKTEST)
    return f"""<div class='scroll'><table><thead><tr><th>Season</th><th>Open bets</th><th>Open ROI</th><th>Close bets</th><th>Close ROI</th></tr></thead>
      <tbody>{rows}<tr class='total'><td>2021–26</td><td class='num'>536</td><td class='num pos'>+5.3%</td><td class='num'>805</td><td class='num pos'>+3.9%</td></tr></tbody></table></div>
      <ul class='notes'>
        <li>~55% wins. Uncertainty is about ±3–4% ROI, so the edge is real-looking but not proven.</li>
        <li>Line shopping (best of DraftKings / FanDuel / BetRivers / BetMGM) added about <b>+2.2 pts</b> ROI on the same picks.</li>
        <li>Caveat: with pre-2020 data the same rule was about break-even in 2016–21 (−0.8% open, +0.3% close).</li>
        <li>No 2022-23 opening lines in the data; seasons with few bets (2023-24) are noisy.</li>
      </ul>"""


def grade():
    total = sum(w * s for _, w, s in GRADE) / 100
    rows = "".join(f"<tr><td>{n}</td><td class='num'>{w}%</td><td class='num'>{s}%</td></tr>" for n, w, s in GRADE)
    return f"""<div class='gradebox'><div class='big'>{total:.0f}%</div><div>B · not yet proven live</div></div>
      <div class='scroll'><table><thead><tr><th>Part</th><th>Weight</th><th>Score</th></tr></thead><tbody>{rows}</tbody></table></div>
      <p class='muted'>A- if 50–75 live flagged picks win ~55%+ with lines moving toward the over; about 75% if they run near 50%.</p>"""


CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1f;--muted:#6b6b70;--line:#e3e3e0;--accent:#1f6feb;--flag:#b8860b;--flagbg:#fff6dc;--pos:#1a7f37;--neg:#c62828}
@media (prefers-color-scheme:dark){:root{--bg:#111214;--card:#1a1b1e;--ink:#ececee;--muted:#9a9aa2;--line:#2c2d31;--accent:#58a6ff;--flag:#e3b341;--flagbg:#2a2310;--pos:#3fb950;--neg:#f85149;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
header h1{margin:0;font-size:28px}header p{margin:4px 0 0;color:var(--muted)}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;margin-top:20px}
h2{margin:0 0 12px;font-size:19px}.muted{color:var(--muted)}.small{font-size:13px}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;white-space:nowrap}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600}
td.small{white-space:normal;min-width:180px}.num{text-align:right;font-variant-numeric:tabular-nums}
tr.flagged td{background:var(--flagbg)}tr.total td{font-weight:700}
.flag{display:inline-block;background:var(--flag);color:#fff;font-size:11px;font-weight:700;padding:2px 6px;border-radius:4px;margin-left:6px}
.hi{color:var(--accent);font-weight:700}.pos{color:var(--pos)}.neg{color:var(--neg)}
.res.W{color:var(--pos);font-weight:700}.res.L{color:var(--neg);font-weight:700}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:16px}
.tile{border:1px solid var(--line);border-radius:10px;padding:12px}.tile .label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.big{font-size:28px;font-weight:700;font-variant-numeric:tabular-nums}
.retro{border-left:4px solid var(--muted);padding:8px 14px;border-radius:6px;background:var(--bg);margin:0 0 10px}
.rule{border-left:4px solid var(--flag);padding:8px 14px;background:var(--flagbg);border-radius:6px}
.gradebox{display:flex;align-items:baseline;gap:14px;margin-bottom:12px}.gradebox .big{font-size:44px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px}@media (max-width:760px){.grid2{grid-template-columns:1fr}}
.grid2 section{margin-top:0}ul.notes{margin:12px 0 0;padding-left:20px;color:var(--muted)}dt{font-weight:700;margin-top:10px}dd{margin:2px 0 0;color:var(--muted)}
"""


def build():
    d = pd.read_csv(paper.LOG) if os.path.exists(paper.LOG) else pd.DataFrame(columns=paper.COLS)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>NHL Total Model</title><style>{CSS}</style></head>
<body><div class="wrap">
<header><h1>NHL Total Model</h1><p>Over/under projections, OVER flags and live paper trading · updated {datetime.now():%b %d, %Y %I:%M %p}</p></header>

<section><h2>The rule</h2><div class="rule"><b>OVER only</b>, consensus line <b>6 or 6.5</b> (never 5.5), and <b>both teams</b> projected
as high-scoring (top 40% of last season's team projections). Bet it at the <b>best over</b> book.</div></section>

<section><h2>Yesterday's results</h2>{yesterday(d)}</section>

<section><h2>Latest slate</h2>{slate(d)}</section>

<section><h2>Paper trading record</h2>{record(d)}</section>

<div class="grid2" style="margin-top:20px">
<section><h2>Backtest: frozen rule, 2020+ data only</h2>{backtest()}</section>
<section><h2>Grade</h2>{grade()}</section>
</div>

<section><h2>How it works</h2>
<p>Each team's goals are projected separately for <b>5-on-5</b> (expected goals + actual goals for/against per 60) and the
<b>power play</b> (PP and PK efficiency × penalties drawn and taken), plus other situations. The opposing
<b>starting goalie's</b> goals saved above expected scales goals allowed, and <b>back-to-backs</b> cut the tired team's scoring ~8%
(opponent +6.5%). Uses only data from the 2020-21 season onward (MoneyPuck, NHL API, DailyFaceoff, Action Network).</p>
<dl>
<dt>P(7+)</dt><dd>Model's chance the game has 7 or more goals: wins an over 6.5 and an over 6 (exactly 6 pushes an over 6). The NHL average is about 45%.</dd>
<dt>Proj</dt><dd>Projected total goals (away + home).</dd>
<dt>Best over 6/6.5</dt><dd>The best-value over at 6 or 6.5 across DraftKings, FanDuel, BetRivers and BetMGM.</dd>
<dt>Line moved our way</dt><dd>Whether the closing line moved toward the over after the pick: the best early sign of a real edge.</dd>
</dl></section>

<p class="muted small">Paper trading only, not betting advice. Source: <a href="https://github.com/Prezbo8/nhl-total-model">github.com/Prezbo8/nhl-total-model</a></p>
</div></body></html>"""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(page)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    build()
