"""How each game's projection moved during the day (dashboard 'How the projection moved').

Every model run adds a snapshot per game that hasn't started to data/moves/<day>.json, changed or not (a run log):
{"AWY@HOM": [{at, proj, line, a/h: {lam, goalie, status, out, dtd, lineup, gadj, inj}}, ...]}.
news() lists what the scraper picked up that the projection doesn't show (goalie status, day-to-day, lineup source,
the line); explain() turns two snapshots into the change in the total and its causes, each team's change split into
goalie / injuries & lineup / ratings & other data (finished games, refreshed stats) by how much each factor moved.
"""
import json
import os

import numpy as np
import pandas as pd

import paths
import split_model

MIN_MOVE = 0.005  # a smaller move in the total counts as no change
EXTRA_HALF = split_model.EXTRA / 2  # each team's fixed part, not scaled by goalie / injuries


def path(day):
    return paths.data(f"moves/{day}.json")


def load(day):
    p = path(day)
    return json.load(open(p)) if os.path.exists(p) else {}


def _names(v, sep):
    return sorted({x.split("|")[0].split(" (")[0].strip() for x in str(v or "").split(sep) if x.strip()})  # tags / order ignored


def _side(r, s):
    g = str(r[f"{s}_goalie_now"])
    return {"lam": round(float(r[f"proj_{s}"]), 3), "goalie": g.split(" (")[0],
            "status": g.split(" (", 1)[1].rstrip(")") if " (" in g else "",
            "out": _names(r.get(f"{s}_out"), ";"), "dtd": _names(r.get(f"{s}_dtd"), ","), "lineup": r.get(f"{s}_lineup") or "",
            "gadj": round(float(r.get(f"{s}_gadj") or 0), 4), "inj": round(float(r.get(f"{s}_inj") or 0), 4)}


def record(day, rows, started=(), at=None):
    """Add this run's snapshot for each game in rows (model.today log rows) not in `started` (game keys)."""
    at = at or pd.Timestamp.now(tz="America/New_York").strftime("%-I:%M %p")
    d = load(day)
    for r in rows:
        key = f"{r['away']}@{r['home']}"
        if key in started:
            continue  # frozen at puck drop
        line = None if pd.isna(r.get("bet_total")) or pd.isna(r.get("bet_over")) else [float(r["bet_total"]), int(r["bet_over"])]
        d.setdefault(key, []).append({"at": at, "proj": round(float(r["proj"]), 3), "line": line,
                                      "a": _side(r, "away"), "h": _side(r, "home")})
    os.makedirs(os.path.dirname(path(day)), exist_ok=True)
    with open(path(day), "w") as f:
        json.dump(d, f, separators=(",", ":"))


def moved(prev, cur):
    """True when the projection, a goalie or who is out changed (what explain() accounts for)."""
    return abs(cur["proj"] - prev["proj"]) >= MIN_MOVE or any(
        prev[s]["goalie"] != cur[s]["goalie"] or prev[s]["out"] != cur[s]["out"] for s in ("a", "h"))


def news(prev, cur, away, home):
    """[text] what this run picked up beyond the projection's causes: goalie status (same goalie), day-to-day
    players, a new lineup source / update, the line. Keys missing from either snapshot count as unchanged."""
    out = []
    for s, t in (("a", away), ("h", home)):
        p, c = prev[s], cur[s]
        has = lambda k: k in p and k in c
        if p["goalie"] == c["goalie"] and has("status") and p["status"] != c["status"]:
            out.append(f"{t} goalie {c['goalie']}: {p['status']} → {c['status']}")
        if has("dtd"):
            out += [f"{n} ({t}) day-to-day" for n in c["dtd"] if n not in p["dtd"]]
            out += [f"{n} ({t}) off day-to-day" for n in p["dtd"] if n not in c["dtd"] and n not in c["out"]]
        if has("lineup") and p["lineup"] != c["lineup"] and c["lineup"]:
            out.append(f"{t} lineup: {c['lineup']}")
    if "line" in prev and "line" in cur and prev["line"] != cur["line"] and cur["line"]:
        was = f"{prev['line'][0]:g} o{prev['line'][1]:+d}" if prev["line"] else "none"
        out.append(f"Line {was} → {cur['line'][0]:g} o{cur['line'][1]:+d}")
    return out


def explain(prev, cur, away, home):
    """[(text, goals)] causes of the move from prev to cur in the game total, biggest first. Each team's change is split
    by factor: lam = base x (1 + goalie adj) x (1 + injuries) (+ a fixed part), so a factor's share = lam x its relative
    change. Injuries are one cause for the game (a missing player moves his own team's goals and the opponent's)."""
    causes, inj, other = [], 0.0, 0.0
    for s, opp, opp_s in (("a", home, "h"), ("h", away, "a")):
        p, c = prev[s], cur[s]
        # the scaled part (lam minus the fixed EXTRA / 2) = base x goalie x injury factors: split its change by each
        # factor's share of the log change, so the pieces add up exactly
        lg = np.log((1 + c["gadj"]) / (1 + p["gadj"]))
        li = np.log((1 + c["inj"]) / (1 + p["inj"]))
        lt = np.log((c["lam"] - EXTRA_HALF) / (p["lam"] - EXTRA_HALF))
        d_lam = c["lam"] - p["lam"]
        g, i = (d_lam * lg / lt, d_lam * li / lt) if abs(lt) > 1e-9 else (0.0, 0.0)
        inj += i
        other += d_lam - g - i
        og, cg = prev[opp_s]["goalie"], cur[opp_s]["goalie"]  # a team's goals depend on the OPPOSING goalie
        if og != cg:
            causes.append((f"{opp} goalie: {og} → {cg}", g))
        elif abs(g) >= MIN_MOVE:
            causes.append((f"{opp} goalie {cg}: rating updated", g))
    bits = []
    for side, t in (("a", away), ("h", home)):
        bits += [f"{n} ({t}) out" for n in cur[side]["out"] if n not in prev[side]["out"]]
        bits += [f"{n} ({t}) back in" for n in prev[side]["out"] if n not in cur[side]["out"]]
    if bits or abs(inj) >= MIN_MOVE:
        causes.append(("Injuries / lineup: " + (", ".join(bits) if bits else "adjustment updated"), inj))
    if abs(other) >= MIN_MOVE:
        causes.append(("Ratings / other data updated (finished games, refreshed stats)", other))
    return sorted(causes, key=lambda x: -abs(x[1]))
