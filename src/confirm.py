"""Starting-goalie and injury confirmations from several sources, combined.

Goalies: DailyFaceoff (model.dailyfaceoff), Rotowire and GoaliePost each give tonight's expected starter
with a status. combine() turns them into one starter per team:
  - Confirmed  when at least one source confirms him and no source confirms someone else
  - Conflict   when sources confirm different goalies (the starter with more confirmations is used)
  - Likely     when no source confirms, but at least one says likely / expected
  - Projected  otherwise
Each source can fail on its own (site down, page changed): the others still work.

Injuries: Rotowire's per-team injury list (OUT / IR / DTD) as a second source next to ESPN.
"""
import html
import json
import re
import unicodedata
import urllib.request

ROTOWIRE = "https://www.rotowire.com/hockey/nhl-lineups.php"
GOALIEPOST = "https://goaliepost.com/"
RW_ABBR = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "UTAH": "UTA", "MON": "MTL", "CLB": "CBJ", "WAS": "WSH"}
RANK = {"confirmed": 3, "likely": 2, "projected": 1}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
                                               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=30) as f:
        return f.read().decode("utf-8", "replace")


def status(text):
    t = str(text).lower()
    if "unconfirmed" in t or "not confirmed" in t:
        return "projected"
    if "confirm" in t:
        return "confirmed"
    if "likely" in t or "expect" in t or "probable" in t:
        return "likely"
    return "projected"


def key(name):
    """Comparable goalie name: accents and punctuation dropped, lowercase ('Ukko-Pekka Luukkonen' -> 'ukkopekka luukkonen')."""
    n = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", "", n).strip()


def same(a, b):
    """Same goalie? Full name, or same last name with matching first initial (handles 'U. Luukkonen')."""
    ka, kb = key(a), key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    la, lb = ka.split(), kb.split()
    return la[-1] == lb[-1] and la[0][0] == lb[0][0]


def rotowire():
    """({team: (goalie, status)}, {team: [(player, pos, injury status)]}) from Rotowire's lineups page."""
    s = _get(ROTOWIRE)
    goalies, injuries = {}, {}
    for blk in s.split('class="lineup is-nhl"')[1:]:
        abbrs = [RW_ABBR.get(a, a) for a in re.findall(r'class="lineup__abbr">\s*([A-Z]{2,4})\s*<', blk)[:2]]
        sides = re.split(r'<ul class="lineup__list is-(?:visit|home)"', blk)[1:3]
        for team, part in zip(abbrs, sides):
            g = re.search(r'lineup__player-highlight-name">\s*<a[^>]*>([^<]+)</a>.*?<div class="flex-row[^"]*"[^>]*>\s*(?:<div[^>]*></div>)?\s*([A-Za-z ]+)',
                          part, re.S)
            if g:
                goalies[team] = (html.unescape(g.group(1).strip()), status(g.group(2)))
            inj = part.split("INJURIES", 1)[1] if "INJURIES" in part else ""
            injuries[team] = [(html.unescape(n), p, st) for p, n, st in re.findall(
                r'lineup__pos">([A-Z]+)</div>\s*<a[^>]*title="([^"]+)"[^>]*>.*?</a>\s*<span class="lineup__inj">([^<]+)</span>', inj, re.S)]
    return goalies, injuries


def goaliepost():
    """{team: (goalie, status, nhl_id, source)} from GoaliePost (includes each goalie's NHL player id)."""
    u = _get(GOALIEPOST).replace('\\"', '"').replace("\\\\", "\\")
    dec, out = json.JSONDecoder(), {}
    for mt in re.finditer(r'"predictedGoalies":', u):
        try:
            pg, _ = dec.raw_decode(u, mt.end())
            t0 = u.rfind('"teams":', 0, mt.start())
            teams, _ = dec.raw_decode(u, t0 + len('"teams":'))
        except ValueError:
            continue
        for side in ("HOME", "AWAY"):
            abbr = teams.get(side, {}).get("team", {}).get("abbreviation")
            best = max(pg.get(side, []), key=lambda g: RANK[status(g.get("likeliness"))], default=None)
            if abbr and best:
                src = (best.get("links") or [{}])[0].get("text")
                out[abbr] = (best["goalie"]["fullName"], status(best.get("likeliness")), best["goalie"].get("externalId"), src)
    return out


def gather(dfo_by_team, rw_goalies=None):
    """{team: [(source, goalie, status, nhl_id or None)]} from all three sources.
    dfo_by_team: {team: (goalie, status text)}; rw_goalies: rotowire()[0] if already fetched."""
    out = {}
    for t, (g, st) in dfo_by_team.items():
        if g:
            out.setdefault(t, []).append(("DailyFaceoff", g, status(st), None))
    srcs = (("Rotowire", (lambda: rw_goalies) if rw_goalies is not None else (lambda: rotowire()[0])), ("GoaliePost", goaliepost))
    for name, fn in srcs:
        try:
            for t, v in fn().items():
                out.setdefault(t, []).append((name, v[0], v[1], v[2] if len(v) > 2 else None))
        except Exception as e:
            print(f"(goalie source {name} unavailable: {type(e).__name__}: {str(e)[:80]})")
    return out


def combine(reports):
    """One starter from [(source, goalie, status[, nhl_id])] ->
    (goalie, 'Confirmed'|'Conflict'|'Likely'|'Projected', summary, nhl_id or None)."""
    if not reports:
        return None, "Projected", "", None
    groups = []  # [(goalie name, [(source, status)], [every spelling seen], [nhl ids seen])]
    for src, g, st, *rest in reports:
        pid = rest[0] if rest else None
        for grp in groups:
            if same(grp[0], g):
                grp[1].append((src, st)); grp[2].append(g); grp[3].append(pid); break
        else:
            groups.append((g, [(src, st)], [g], [pid]))
    score = lambda grp: (sum(st == "confirmed" for _, st in grp[1]), max(RANK[st] for _, st in grp[1]), len(grp[1]))
    groups.sort(key=score, reverse=True)
    best = groups[0]
    full = max(best[2], key=len)  # prefer the full first name over an initial ('Ukko-Pekka' over 'U.')
    confirmed_elsewhere = any(st == "confirmed" for grp in groups[1:] for _, st in grp[1])
    top = max(RANK[st] for _, st in best[1])
    label = ("Conflict" if confirmed_elsewhere or (len(groups) > 1 and top < 3 and score(groups[1])[1:] == score(best)[1:])
             else "Confirmed" if top == 3 else "Likely" if top == 2 else "Projected")
    summary = "; ".join(f"{src}: {g if not same(g, best[0]) else '✓'} ({st})" for g, srcs, *_ in groups for src, st in srcs)
    return full, label, summary, next((p for p in best[3] if p), None)


RW_OUT = {"OUT", "IR", "IR-LT", "IR-NR", "SUSP", "NHI"}  # Rotowire statuses that mean he isn't playing tonight


def add_rotowire_injuries(injured, rw_injuries):
    """Add Rotowire's injured skaters to ESPN's list (same row format as injuries.fetch), without duplicates.
    A player ESPN calls day-to-day but Rotowire lists as out becomes out."""
    norm = lambda n: key(n)
    merged = [dict(r) for r in injured]
    have = {(r["team"], norm(r["name"])): r for r in merged}
    for team, players in rw_injuries.items():
        for name, pos, st in players:
            if pos == "G":  # goalies are handled through the starting goalie
                continue
            out = st.upper() in RW_OUT
            r = have.get((team, norm(name)))
            if r is not None:
                if out and r["status"] == "Day-To-Day":
                    r.update(status="Out", note=(r.get("note") or "") + " (Rotowire: out)")
                continue
            row = {"team": team, "name": name, "pos": pos, "status": "Out" if out else "Day-To-Day",
                   "ret": None, "note": f"Rotowire: {st}", "tag": "IR" if st.upper().startswith("IR") else None}
            merged.append(row); have[(team, norm(name))] = row
    return merged


def actual_starters(game_id):
    """{'away': (name, nhl_id), 'home': (name, nhl_id)} from the NHL box score once the game has started."""
    url = f"https://api-web.nhle.com/v1/gamecenter/{int(game_id)}/boxscore"
    b = json.loads(_get(url))
    out = {}
    for side, k in (("away", "awayTeam"), ("home", "homeTeam")):
        for g in b.get("playerByGameStats", {}).get(k, {}).get("goalies", []):
            if g.get("starter"):
                out[side] = (g.get("name", {}).get("default", ""), g.get("playerId"))
    return out
