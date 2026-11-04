"""AI-written game notes (Google Gemini, free tier): a short paragraph per game that reads like it was written for that
game, in place of the fixed template (which stays as the fallback).

Facts in, writing out. Each game's fact sheet = the template's own text (dashboard.reasoning: the call and why, both
teams' goal effects, goalies, line) + recent form (form_* below: last-10 record, streak, last-10 goals, the goalie's last
5 games, scoring vs the model over two weeks; saved by model.today() and frozen at puck drop) + last-10 totals and head to
head from the log + after the game, how the goals came (NHL scoring summary). Gemini writes the paragraph; a check
rejects it if it uses a number that isn't in the facts, names another call, or breaks the format (one retry, then the
template stays). A note is rewritten only when its game's facts change (signature()), and saved in data/notes/<day>.json.
No GEMINI_API_KEY (GitHub secret), or Gemini failing / out of free requests = the template, as before.

  python3 src/notes.py             # today's games + debriefs of finished games (the hourly run, after projecting)
  python3 src/notes.py --preview   # print today's notes, save nothing (Tests workflow, started by hand)
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

import pandas as pd

import paths

MODEL = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
API = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
MAX_CALLS = 14   # per run: the free tier allows a limited number of requests a day (per Google project)
PAUSE = 6        # seconds between requests (the free tier allows ~10 a minute)
WORDS = (55, 160)
CALLS = ("SLAM", "1U", "PASS", "AVOID")

SYSTEM = """You write the game note for one NHL game on a hockey betting model's dashboard. The reader is the model's owner,
who bets overs (only lines of 6 or 6.5) and knows hockey. Rules:
1. Use only the facts in the JSON. Copy every number exactly as it appears there. Never round, add up or invent numbers,
   players, results or history.
2. One paragraph of 70-130 words. Plain text: no headings, lists, markdown, emojis or exclamation marks.
3. Say the model's call (the "call" field: SLAM, 1U, PASS or AVOID) and its main reason in your own words. Never suggest
   a different call or a different bet.
4. Open with the angle in "lead_with", not with the call. Don't open the way any of "openings_used_today" open, and don't
   reuse their sentence shapes.
5. Recent form (records, streaks, recent scoring, a goalie's last games) is context: the projection already counts every
   game, and form alone hasn't predicted totals. Use it to make the note specific to this game, never as the reason to bet.
6. If "result" is in the facts, the game is over: write the debrief instead. Say how it finished against the line, whether
   the call was right, and why, from how the goals came (5-on-5, power play, shorthanded, empty net, overtime) compared
   with what the model expected.
7. Write like a sharp hockey writer: specific, varied sentence length, no cliches, no hype."""


def path(day):
    return paths.data(f"notes/{day}.json")


def load(day):
    p = path(day)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def save(day, d):
    os.makedirs(os.path.dirname(path(day)), exist_ok=True)
    with open(path(day), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))


# ---- recent form (model.today saves it, frozen at puck drop) ----

def goalie_last(gid, season, n=5):
    """{'games', 'goals_allowed', 'expected_goals_against'} over a goalie's last n regular-season games this season."""
    import goalies
    if gid is None or pd.isna(gid):
        return None
    if not hasattr(goalie_last, "gg"):
        goalie_last.gg = pd.read_csv(goalies.GOALIE_GAMES)
    g = goalie_last.gg
    g = g[(g.playerId == gid) & (g.season == season) & (g.gameId.astype(int).astype(str).str[4:6] == "02")].sort_values("gameId").tail(n)
    if not len(g):
        return None
    return {"games": int(len(g)), "goals_allowed": int(g.goals.sum()), "expected_goals_against": round(float(g.xGoals.sum()), 1)}


def form_snapshot(day, standings, starters, team_form, started, season):
    """Each playing team's recent form, saved in data/notes/<day>.json under 'form' and frozen at puck drop.
    standings: NHL standings rows (elimination.standings); starters: {team: (goalie name, NHL id or None)};
    team_form: trends.team_form frame (scoring / allowing vs the model per window); started: teams whose game began."""
    d = load(day)
    old = d.get("form", {})
    rows = {r["teamAbbrev"]["default"]: r for r in standings or []}
    f14 = {x.team: x for x in team_form[team_form.window == "14"].itertuples()} if team_form is not None and len(team_form) else {}
    out = {}
    for team, (gname, gid) in starters.items():
        if team in started and team in old:
            out[team] = old[team]
            continue
        t, s = {}, rows.get(team)
        if s:
            t.update(record=f"{s['wins']}-{s['losses']}-{s['otLosses']}",
                     streak=f"{s.get('streakCode') or ''}{s.get('streakCount') or ''}",
                     last10_record=f"{s.get('l10Wins')}-{s.get('l10Losses')}-{s.get('l10OtLosses')}",
                     last10_goals_for=s.get("l10GoalsFor"), last10_goals_against=s.get("l10GoalsAgainst"))
        x = f14.get(team)
        if x is not None and x.gp >= 3:
            t["last_2_weeks"] = {"games": int(x.gp), "scored_vs_projection_per_game": round(float(x.scoring), 2),
                                 "allowed_vs_projection_per_game": round(float(-x.allowing), 2),
                                 "goals_vs_expected_goals_per_game": round(float(x.finishing), 2),
                                 "goals_allowed_vs_expected_per_game": round(float(-x.goaltending), 2)}
        g = goalie_last(gid, season)
        if gname and g:
            t["goalie"] = {"name": gname, **{f"last_{g['games']}_{k}": v for k, v in g.items() if k != "games"}}
        out[team] = t
    d["form"] = {**old, **out}
    save(day, d)


# ---- the fact sheet ----

def plain(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(s))).split())


def _out(v):
    """'Tyler Kleven|-0.0158|0.0105; ...' -> ['Tyler Kleven']"""
    return [x.split("|")[0].strip() for x in str(v or "").split(";") if x.strip() and x.strip() != "nan"]


def facts(r, flagged, form, debrief=None):
    """Everything the note may say about one game (dashboard.current row r)."""
    import dashboard
    away, home = r.away, r.home
    val = lambda c: None if pd.isna(getattr(r, c, None)) else getattr(r, c)
    teams = {}
    for side, t in (("away", away), ("home", home)):
        x = dict(form.get(t, {}))
        x["projected_goals"] = round(float(getattr(r, f"proj_{side}")), 2)
        if val(f"{side}_l10_n"):
            x["last10_games_average_total_goals"] = val(f"{side}_l10_avg")
            x["last10_games_with_7_plus_goals"] = f"{int(val(f'{side}_l10_7'))} of {int(val(f'{side}_l10_n'))}"
        x["players_out"] = _out(getattr(r, f"{side}_out", None))
        opp_g = form.get(home if side == "away" else away, {}).get("goalie")
        if opp_g:
            x["faces_goalie"] = opp_g
        teams[t] = x
    f = {"game": f"{away} @ {home}", "call": dashboard.call(r, flagged), "model_notes": plain(dashboard.reasoning(r, flagged)),
         "teams": teams}
    if val("h2h_n"):
        f["head_to_head_since_2020"] = {"games": int(val("h2h_n")), "average_total_goals": val("h2h_avg"),
                                        "games_with_7_plus": int(val("h2h_7")), "last_meetings": val("h2h_last")}
    if not pd.isna(r.final_total):
        f["result"] = {"final": f"{away} {int(r.away_score)}, {home} {int(r.home_score)}", "total_goals": int(r.final_total),
                       "line": val("bet_total"), **(debrief or {})}
    return f


def lead_with(f):
    """The most unusual thing about this game, so notes don't all open the same way."""
    c = []
    for t, x in f["teams"].items():
        s = x.get("streak") or ""
        if len(s) > 1 and s[0] in "WL" and s[1:].isdigit() and int(s[1:]) >= 3:
            c.append((1.0 + int(s[1:]) / 5, f"{t}'s {'winning' if s[0] == 'W' else 'losing'} streak ({s})"))
        w = (x.get("last10_record") or "").split("-")[0]
        if w.isdigit() and (int(w) >= 7 or int(w) <= 3):
            c.append((1.2, f"{t}'s last 10 games ({x['last10_record']})"))
        g = x.get("faces_goalie") or {}
        ga, xga = next((v for k, v in g.items() if k.endswith("goals_allowed")), None), next((v for k, v in g.items() if k.endswith("expected_goals_against")), None)
        if ga is not None and xga is not None and abs(ga - xga) >= 2:
            c.append((1.0 + abs(ga - xga) / 3, f"how {g['name']} has played lately (the goalie {t} faces)"))
        m = (x.get("last_2_weeks") or {}).get("scored_vs_projection_per_game")
        if m is not None and abs(m) >= 0.5:
            c.append((1.0 + abs(m), f"{t}'s scoring over the last two weeks"))
        if x.get("players_out"):
            c.append((0.6, f"who {t} is missing"))
    if "result" in f:
        return "how the goals actually came, compared with the call"
    return max(c)[1] if c else "the matchup that decides the call"


# ---- Gemini ----

def gemini(system, prompt):
    key = os.environ.get("GEMINI_API_KEY")
    body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 1.0, "maxOutputTokens": 2048}}
    req = urllib.request.Request(API.format(MODEL), data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})  # key in a header, never the URL
    with urllib.request.urlopen(req, timeout=60) as f:
        out = json.load(f)
    return "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"] if not p.get("thought")).strip()


NUM = re.compile(r"(?<![\w.])[+\-−]?\d+(?:\.\d+)?(?:-\d+){0,2}%?")


def numbers(s):
    """Every number in a text, normalized ('−0.14' -> '-0.14'; '5-on-5' etc. are not numbers here)."""
    s = re.sub(r"\b\d-on-\d\b", " ", str(s).replace("−", "-"))
    return {m.group(0) for m in NUM.finditer(s)}


ALWAYS_OK = {"5", "10"}  # "last 5" / "last 10" games, whether or not the facts spell it out


def allowed(f):
    """Numbers a note may use: every number in its facts, with and without sign / percent sign."""
    out, s = set(ALWAYS_OK), json.dumps(f, ensure_ascii=False)
    for n in numbers(s) | set(re.findall(r"\d+(?:\.\d+)?", s)):  # the 2nd: digits inside codes ('W4' -> 4 straight, '#2')
        out |= {n, n.lstrip("+-"), n.rstrip("%"), n.lstrip("+-").rstrip("%")}
    return out


def check(text, f):
    """'' when the note is usable, else why not (sent back to Gemini on the retry)."""
    words = len(text.split())
    if not WORDS[0] <= words <= WORDS[1]:
        return f"it is {words} words; write {WORDS[0] + 15}-{WORDS[1] - 30}"
    if "\n" in text.strip() or re.search(r"\*\*|!|^\s*(?:#|[-•*] )", text, re.M):  # (a '#' rank like '#2 defense' is fine)
        return "use one plain paragraph: no line breaks, markdown, lists or exclamation marks"
    if f["call"] not in text:
        return f"say the model's call, {f['call']}, by name"
    other = [c for c in CALLS if c != f["call"] and re.search(rf"\b{c}\b", text)]
    if other:
        return f"only the model's call ({f['call']}) may be named, not {', '.join(other)}"
    bad = sorted(n for n in numbers(text) if n not in allowed(f) and n.lstrip("+-").rstrip("%") not in allowed(f))
    if bad:
        return f"these numbers are not in the facts: {', '.join(bad)}. Use only numbers copied from the facts"
    return ""


def opening(text):
    return " ".join(text.split()[:8])


def write_note(f, used):
    """(text, '') or (None, why) after up to 2 tries."""
    ask = (f"Facts:\n{json.dumps({**f, 'lead_with': lead_with(f), 'openings_used_today': used}, ensure_ascii=False)}\n\n"
           "Write the note.")
    why = ""
    for _ in range(2):
        text = gemini(SYSTEM, ask if not why else ask + f"\n\nYour last version can't be used: {why}. Rewrite it.")
        why = check(text, f)
        if not why:
            return text, ""
        time.sleep(PAUSE)
    return None, why


# ---- colors (applied when the dashboard renders a note) ----

def colors(f):
    """{number as written: css classes}: goal effects and team projections by what they do to tonight's goals
    (green = more), last-10 records and streaks hot / cold (form, not goals)."""
    out = {}
    for m in re.finditer(r"([+\-−]\d+\.\d\d)\b", f["model_notes"]):
        v = float(m.group(1).replace("−", "-"))
        out[m.group(1).replace("−", "-")] = "t-great" if v >= 0.10 else "t-good" if v >= 0.03 else "t-trash" if v <= -0.10 else "t-bad" if v <= -0.03 else "t-mid"
    for t, x in f["teams"].items():
        cut = re.search(r"cutoff (\d\.\d\d)", f["model_notes"])
        if cut:
            out[f"{x['projected_goals']:.2f}"] = "t-good" if x["projected_goals"] >= float(cut.group(1)) else "t-bad"
        rec = x.get("last10_record") or ""
        w = rec.split("-")[0]
        if w.isdigit():
            out[rec] = "hot" if int(w) >= 7 else "cold" if int(w) <= 3 else "even"
    return out


def colorize(text, cls):
    """HTML for a note: escaped, with each known number wrapped in its color chip (first match of each wins)."""
    s = html.escape(text).replace("−", "-")
    if not cls:
        return s
    pat = re.compile("|".join(sorted((re.escape(k) for k in cls), key=len, reverse=True)))
    return pat.sub(lambda m: f"<span class='nv {cls[m.group(0)]}'>{m.group(0)}</span>", s)


# ---- the run ----

def signature(f):
    """What a note depends on: a new note only when one of these changes (not on every hundredth of a goal)."""
    t = {k: {"proj": round(v["projected_goals"] * 20) / 20, "out": v.get("players_out"), "form": [v.get("streak"), v.get("last10_record")],
             "goalie": (v.get("faces_goalie") or {}).get("name")} for k, v in f["teams"].items()}
    line = re.search(r"against a (\d+(?:\.\d)?) line", f["model_notes"])
    return json.dumps({"call": f["call"], "teams": t, "line": line.group(1) if line else None,
                       "unconfirmed": "aren't confirmed" in f["model_notes"], "result": f.get("result")}, sort_keys=True, default=str)


def debrief(game_id):
    """How the goals came (NHL scoring summary): per team, by strength; overtime / shootout; shots."""
    if not game_id or pd.isna(game_id):
        return {}
    with urllib.request.urlopen(urllib.request.Request(f"https://api-web.nhle.com/v1/gamecenter/{int(game_id)}/landing",
                                                       headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as f:
        d = json.load(f)
    how = {}
    for p in d.get("summary", {}).get("scoring", []):
        for g in p.get("goals", []):
            t = g["teamAbbrev"]["default"] if isinstance(g.get("teamAbbrev"), dict) else g.get("teamAbbrev")
            kind = {"pp": "power_play", "sh": "shorthanded"}.get(g.get("strength"), "even_strength")
            if g.get("goalModifier") == "empty-net":
                kind = "empty_net"
            how.setdefault(t, {}).setdefault(kind, 0)
            how[t][kind] += 1
    end = (d.get("gameOutcome") or {}).get("lastPeriodType")
    return {"goals_by_team_and_type": how, "shots": {d["awayTeam"]["abbrev"]: d["awayTeam"].get("sog"), d["homeTeam"]["abbrev"]: d["homeTeam"].get("sog")},
            **({"ended_in": {"OT": "overtime", "SO": "a shootout"}[end]} if end in ("OT", "SO") else {})}


def models():
    """Names of the Gemini models this key can call (printed by --preview, to pick GEMINI_MODEL)."""
    req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                                 headers={"x-goog-api-key": os.environ.get("GEMINI_API_KEY", "")})
    with urllib.request.urlopen(req, timeout=30) as f:
        return [m["name"].split("/")[-1] for m in json.load(f).get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])]


def run(preview=False):
    import dashboard
    import health
    import paper
    if not os.environ.get("GEMINI_API_KEY"):
        print("(game notes: no GEMINI_API_KEY secret: the dashboard keeps the template)")
        return
    if preview:
        try:
            print("(models this key can use: " + ", ".join(m for m in models() if "flash" in m or "pro" in m) + f"; using {MODEL})")
        except Exception as e:
            print(f"(couldn't list the models: {type(e).__name__}: {str(e)[:120]})")
    today = date.today().isoformat()
    log = dashboard.current(paper.read_log())
    days = [d for d in ((date.today() - timedelta(days=1)).isoformat(), today) if (log.date == d).any()]
    calls, made, kept, failed = 0, 0, 0, []
    now = pd.Timestamp.now(tz="UTC")
    for day in days:
        d = load(day)
        notes, form, dbr = d.get("notes", {}), d.get("form", {}), d.get("debrief", {})
        g = log[log.date == day]
        used = [opening(n["text"]) for n in notes.values() if n.get("text")]
        for r in g.itertuples():
            key = f"{r.away}@{r.home}"
            started = isinstance(r.start_utc, str) and pd.Timestamp(r.start_utc) <= now
            if started and pd.isna(r.final_total):
                continue  # under way: keep the pre-game note until it's final
            if not pd.isna(r.final_total) and key not in dbr:
                try:
                    dbr[key] = debrief(r.game_id)
                except Exception as e:
                    print(f"(game notes: no scoring summary for {key} yet: {type(e).__name__})")
            f = facts(r, dashboard._is(r.flag), form, dbr.get(key))
            sig = signature(f)
            if notes.get(key, {}).get("sig") == sig:
                kept += 1
                continue
            if calls >= MAX_CALLS:
                break
            try:
                text, why = write_note(f, used)
                calls += 1
            except urllib.error.HTTPError as e:
                msg = e.read().decode()[:200]
                print(f"(game notes: Gemini answered {e.code}: {msg})")
                if e.code in (429, 403):
                    calls = MAX_CALLS  # out of free requests (or no access): the rest keep their note / the template
                failed.append(key)
                continue
            except Exception as e:
                print(f"(game notes: {key} failed: {type(e).__name__}: {str(e)[:150]})")
                failed.append(key)
                continue
            if text is None:
                print(f"(game notes: {key} rejected twice ({why}): the template stays)")
                failed.append(key)
                continue
            notes[key] = {"text": text, "colors": colors(f), "sig": sig, "model": MODEL,
                          "at": pd.Timestamp.now(tz="America/New_York").strftime("%-I:%M %p"), "kind": "debrief" if "result" in f else "preview"}
            used.append(opening(text))
            made += 1
            if preview:
                print(f"\n=== {key} ({f['call']}, lead: {lead_with(f)}) ===\n{text}")
            time.sleep(PAUSE)
        if not preview:
            d.update(notes=notes, debrief=dbr)
            save(day, d)
    print(f"(game notes: {made} written, {kept} unchanged, {len(failed)} kept the template, {calls} Gemini requests)")
    health.note(f"✓ Game notes (Gemini): {made} written, {kept} unchanged" + (f"; {len(failed)} kept the template ({', '.join(failed)})" if failed else ""))


if __name__ == "__main__":
    run(preview="--preview" in sys.argv)
