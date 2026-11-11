"""Historical NHL totals from Action Network: book 15 = consensus close, book 30 = opening line."""
import json
import os
import time
import urllib.request
from datetime import date, timedelta

import pandas as pd
import paths

ODDS = paths.data("odds_history.csv")
ODDS_OPEN = paths.data("odds_open.csv")
URL = "https://api.actionnetwork.com/web/v2/scoreboard/nhl?period=game&date={}"  # v2 since Nov 10 2026 (v1 answers 404)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
SEASONS = [(date(2022, 10, 1), date(2023, 4, 20)), (date(2023, 10, 1), date(2024, 4, 25)),
           (date(2024, 10, 1), date(2025, 4, 25)), (date(2025, 10, 1), date(2026, 4, 25))]


def scoreboard(d):
    """Action Network's NHL scoreboard for one day (v2)."""
    req = urllib.request.Request(URL.format(d.strftime("%Y%m%d")), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as f:
        return json.load(f)


def _p(odds):
    return 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)


def totals(g):
    """{book id: (total, over price, under price)} for one v2 game: each book's main game total (markets -> book ->
    event -> total: an over and an under at the same value). Live, alternate and suspended lines (line_status other
    than 'normal') are skipped; if a book still has several totals, its main one is the pair priced closest to even."""
    out = {}
    for book, mk in (g.get("markets") or {}).items():
        ts = [o for o in ((mk or {}).get("event") or {}).get("total") or []
              if not o.get("is_live") and not o.get("is_alt_market") and o.get("line_status") in (None, "normal")
              and o.get("odds") is not None and o.get("value") is not None]
        under = {o["value"]: o["odds"] for o in ts if o.get("side") == "under"}
        pairs = [(float(o["value"]), int(o["odds"]), int(under[o["value"]])) for o in ts
                 if o.get("side") == "over" and o["value"] in under]
        if pairs:  # the main line: fair over chance closest to 50%
            out[int(book)] = min(pairs, key=lambda x: abs(_p(x[1]) / (_p(x[1]) + _p(x[2])) - 0.5))
    return out


def day_games(d, book=15, completed_only=True, data=None):
    """One row per game with book's total (15 = consensus, 30 = opening line). data: an already-read scoreboard."""
    data = scoreboard(d) if data is None else data
    rows = []
    for g in data.get("games", []):
        if completed_only and g.get("status") != "complete":
            continue
        line = totals(g).get(book)
        if not line:
            continue
        teams = {t["id"]: t["abbr"] for t in g["teams"]}
        rows.append({"date": d.isoformat(), "start": g["start_time"], "home": teams[g["home_team_id"]],
                     "away": teams[g["away_team_id"]], "total": line[0], "over": line[1], "under": line[2]})
    return rows


def fetch_all(book=15, path=ODDS):
    done = set(pd.read_csv(path).date) if os.path.exists(path) else set()
    rows = []
    for start, end in SEASONS:
        d = start
        while d <= end:
            if d.isoformat() not in done:
                try:
                    rows += day_games(d, book)
                except Exception as e:
                    print(d, "error", e)
                time.sleep(1)
            d += timedelta(days=1)
        if rows:
            old = pd.read_csv(path) if os.path.exists(path) else pd.DataFrame()
            pd.concat([old, pd.DataFrame(rows)]).to_csv(path, index=False)
            rows = []
        print("done season starting", start, flush=True)


if __name__ == "__main__":
    import sys
    fetch_all(30, ODDS_OPEN) if "open" in sys.argv else fetch_all()


# ---- backup: DraftKings' total from ESPN's public scoreboard, only for games Action Network has no current line for ----
ESPN = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates={}"
CONSENSUS, BACKUP, SAVED = "consensus", "DraftKings (ESPN backup)", " (last saved)"


def _num(v):
    """'+110' / '-115' / 'EVEN' / 110.0 / '' / None / NaN -> int price or None."""
    if v is None or (isinstance(v, float) and v != v) or str(v).strip() == "":
        return None
    s = str(v).strip().upper()
    return 100 if s == "EVEN" else int(round(float(s)))


def norm_line(total, over, under):
    """{'total': float, 'over': int, 'under': int or None}, or None when the total or the over price is missing."""
    o = _num(over)
    try:
        t = float(total)
    except (TypeError, ValueError):
        return None
    if t != t or o is None:
        return None
    return {"total": t, "over": o, "under": _num(under)}


def espn_scoreboard(d):
    req = urllib.request.Request(ESPN.format(d.strftime("%Y%m%d")), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as f:
        return json.load(f)


def espn_lines(data, warn=print):
    """{(home, away): line} from an ESPN scoreboard (the requested slate): DraftKings' current total ('close' while the
    game hasn't started) for games not yet started (status state 'pre'). Teams matched by full name, like the ESPN
    injury list (injuries.fetch); an unknown name is reported and that game skipped."""
    import model as m
    from teams import TEAMS
    by_name = {m.norm_name(v): k for k, v in TEAMS.items()}
    out = {}
    for e in (data or {}).get("events", []):
        c = (e.get("competitions") or [{}])[0]
        state = ((c.get("status") or e.get("status") or {}).get("type") or {}).get("state")
        if state != "pre":
            continue
        teams = {}
        for x in c.get("competitors", []):
            name = (x.get("team") or {}).get("displayName", "")
            ab = by_name.get(m.norm_name(name))
            if ab is None:
                warn(f"(ESPN odds: unknown team name {name!r}; game skipped)")
            teams[x.get("homeAway")] = ab
        if not teams.get("home") or not teams.get("away"):
            continue
        tot = ((c.get("odds") or [{}])[0] or {}).get("total") or {}
        ov, un = ((tot.get("over") or {}).get("close") or {}), ((tot.get("under") or {}).get("close") or {})
        val = str(ov.get("line") or "")[1:]  # 'o6.5' -> '6.5'
        if str(un.get("line") or "")[1:] != val:
            continue
        line = norm_line(val, ov.get("odds"), un.get("odds"))
        if line:
            out[(teams["home"], teams["away"])] = line
    return out


def fill_lines(lines, upcoming, espn=None, saved=None):
    """Fill each not-started game's current line ('now') when Action Network has none: DraftKings from ESPN first, else the
    game's last saved line. lines: {(home, away): {'open': ..., 'now': ...}} (changed in place); upcoming: [(home, away)]
    not started; espn: {(home, away): line}; saved: {(home, away): (line, its source)}.
    Returns {(home, away): source of its current line} for every game in lines / upcoming with one."""
    src = {k: CONSENSUS for k, v in lines.items() if v.get("now")}
    for k in upcoming:
        if (lines.get(k) or {}).get("now"):
            continue
        if espn and espn.get(k):
            lines.setdefault(k, {})["now"], src[k] = espn[k], BACKUP
        elif saved and saved.get(k):
            line, was = saved[k]
            base = (was or CONSENSUS).replace(SAVED, "")
            lines.setdefault(k, {})["now"], src[k] = line, base + SAVED
    return src


def no_line(lines, upcoming):
    """['AWY@HOM', ...]: not-started games with no usable line at all (no current and no opening line)."""
    return [f"{a}@{h}" for h, a in upcoming if not ((lines.get((h, a)) or {}).get("now") or (lines.get((h, a)) or {}).get("open"))]


def line_health(h, missing, no_line_games):
    """Health bookkeeping for the lines (h = the health module): 'ESPN odds (backup)' resets when it wasn't needed, so an
    old failure count can't stick; 'Betting lines' fails (retries + an alert after 2 runs) when a game has no line and an
    odds source failed this run; when every source answered and a game is simply off the board, only a summary line."""
    if not missing:
        h._results.setdefault("ESPN odds (backup)", None)
    if not no_line_games:
        h._results.setdefault("Betting lines", None)
        return
    msg = f"no line for {len(no_line_games)} game{'s' if len(no_line_games) != 1 else ''}: {', '.join(no_line_games)}"
    if h._results.get("Action Network now lines") or h._results.get("ESPN odds (backup)"):
        h._results["Betting lines"] = msg
    else:
        print(f"({msg}: every source answered, off the board)")
        h.note(f"✗ Betting lines: {msg} (every source answered: off the board)")
