"""How each game's projection moved during the day (dashboard 'How the projection moved').

Every model run adds a snapshot per game that hasn't started, but only when something changed (projection, goalie or
who is out), to data/moves/<day>.json: {"AWY@HOM": [{at, proj, a/h: {lam, goalie, out, gadj, inj}}, ...]}.
explain() turns two snapshots into the change in the total and its causes, each team's change split into
goalie / injuries & lineup / ratings & other data (finished games, refreshed stats) by how much each factor moved.
"""
import json
import os

import numpy as np
import pandas as pd

import paths
import split_model

MIN_MOVE = 0.005
EXTRA_HALF = split_model.EXTRA / 2  # each team's fixed part, not scaled by goalie / injuries  # a snapshot is kept when the total moves this much, or a goalie / out list changes


def path(day):
    return paths.data(f"moves/{day}.json")


def load(day):
    p = path(day)
    return json.load(open(p)) if os.path.exists(p) else {}


def _side(r, s):
    out = sorted({x.split("|")[0].split(" (")[0].strip() for x in str(r.get(f"{s}_out") or "").split(";") if x.strip()})  # tags / order ignored
    return {"lam": round(float(r[f"proj_{s}"]), 3), "goalie": str(r[f"{s}_goalie_now"]).split(" (")[0],
            "out": out, "gadj": round(float(r.get(f"{s}_gadj") or 0), 4), "inj": round(float(r.get(f"{s}_inj") or 0), 4)}


def record(day, rows, started=(), at=None):
    """Add this run's snapshot for each game in rows (model.today log rows) not in `started` (game keys)."""
    at = at or pd.Timestamp.now(tz="America/New_York").strftime("%-I:%M %p")
    d = load(day)
    for r in rows:
        key = f"{r['away']}@{r['home']}"
        if key in started:
            continue  # frozen at puck drop
        snap = {"at": at, "proj": round(float(r["proj"]), 3), "a": _side(r, "away"), "h": _side(r, "home")}
        hist = d.setdefault(key, [])
        if hist:
            last = hist[-1]
            same = (abs(last["proj"] - snap["proj"]) < MIN_MOVE
                    and all(last[s]["goalie"] == snap[s]["goalie"] and last[s]["out"] == snap[s]["out"] for s in ("a", "h")))
            if same:
                continue
        hist.append(snap)
    os.makedirs(os.path.dirname(path(day)), exist_ok=True)
    with open(path(day), "w") as f:
        json.dump(d, f, separators=(",", ":"))


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
