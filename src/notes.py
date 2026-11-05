"""AI-written game notes (Google Gemini, free tier): a short paragraph per game that reads like it was written for that
game, in place of the fixed template (which stays as the fallback).

Facts in, writing out. The AI gets only the model's and the repo's own numbers (facts()): the call and why, the
projected total vs the line, and per team its projected goals, 5-on-5 / power-play tiers, the goalie it faces (tag +
grade) and the model's factors pushing its goals up or holding them back (dashboard.team_reasons: goals, ranks); then,
as context, recent form saved by the model run (form_snapshot: record, last-10 record, streak and goals from the NHL
standings, the goalie's last 5 games and scoring vs the model over two weeks, each with a plain 'means'), last-10 totals
and head to head from the log; after the game, how the goals came (NHL scoring summary). Each game on a slate opens
with a different kind of angle (leads(), assigned in run()). A check rejects a note that uses a number not in the
facts, names another call, leaves out the call or stops mid-sentence (one retry, then the template stays). A note is
rewritten only when its game's facts change (signature()); saved in data/notes/<day>.json. No GEMINI_API_KEY (GitHub
secret), or Gemini failing / out of free requests = the template, as before.

  python3 src/notes.py             # today's games + debriefs of finished games (the hourly run, after projecting)
  python3 src/notes.py --preview   # also print today's notes + their dashboard HTML (Preview game notes workflow)
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, timedelta

import pandas as pd

import paths

# tried in order: an overloaded / unavailable / out-of-free-requests model hands over to the next (each has its own free
# allowance). Nov 4 2026: 2.5-flash 404s for new keys, and the newest Flash answered 503 "high demand" all afternoon.
MODELS = list(dict.fromkeys(m for m in (os.environ.get("GEMINI_MODEL"), "gemini-flash-latest", "gemini-3.6-flash",
                                        "gemini-flash-lite-latest") if m))
API = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
MAX_CALLS = 14   # notes per run: the free tier allows a limited number of requests a day (per Google project)
PAUSE = 6        # seconds between notes (the free tier allows ~10 requests a minute)
WORDS = (50, 140)
CALLS = ("SLAM", "1U", "PASS", "AVOID")

SYSTEM = """You write the game note for one NHL game on a hockey model's dashboard. The reader owns the model, bets overs
(lines of 6 or 6.5 only) and knows hockey. Every fact comes from the model itself: use them and nothing else.
1. Explain the model's call ("call": SLAM, 1U, PASS or AVOID) with the model's numbers: the projected total against the
   line, each team's projected goals, and the factors pushing them up or holding them back (in goals, with the ranks and
   goalie grades given). Say the call by name. Never suggest a different call or a different bet.
2. Use only the facts. Copy every number exactly as written: never round, add, or invent numbers, players, results or
   history. The "means" fields tell you what a number means: follow them.
3. 60-110 words, one paragraph of complete sentences, plain text: no headings, lists, markdown, emojis or exclamation marks.
4. Open with "lead_with". Don't open the way any of "openings_used_today" open, and don't start with a player's name
   unless lead_with is about that player.
5. Recent form (records, streaks, recent scoring, a goalie's last games) is context: the model already counts every game,
   and form alone hasn't predicted totals. Use it to make the note specific to this game, never as the reason to bet.
6. If "result" is in the facts, the game is over: write the debrief. Say how it finished against the line, whether the
   call was right, and why, from how the goals came compared with what the model expected.
7. Plain words, like a sharp hockey writer: say "both teams need to project 3.10 goals or more", not "high-scoring
   cutoff". Specific, varied sentences, no cliches, no hype."""


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


# ---- the fact sheet: the model's numbers, then form as context ----

def plain(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(s))).split())


def _out(v):
    """'Tyler Kleven|-0.0158|0.0105; ...' -> ['Tyler Kleven']"""
    return [x.split("|")[0].strip() for x in str(v or "").split(";") if x.strip() and x.strip() != "nan"]


def _goalie_means(g, team):
    ga = next((v for k, v in g.items() if k.endswith("goals_allowed")), None)
    xga = next((v for k, v in g.items() if k.endswith("expected_goals_against")), None)
    if ga is None or xga is None:
        return None
    d = round(xga - ga, 1)
    return (f"he has been better than expected, stopping {d:.1f} more goals than expected: harder for {team} to score" if d >= 1.5
            else f"he has been worse than expected, allowing {-d:.1f} more goals than expected: easier for {team} to score" if d <= -1.5
            else "about as expected")


def facts(r, flagged, form, debrief=None):
    """What the note may say about one game (a dashboard.current row): the model's numbers first, form as context.
    None when the game has no breakdown (the template explains it)."""
    import dashboard
    v = lambda s_, k: getattr(r, f"{s_}_{k}", float("nan"))
    val = lambda c: None if pd.isna(getattr(r, c, None)) else getattr(r, c)
    if pd.isna(v("away", "ev")) or pd.isna(r.cutoff):
        return None
    call, rk = dashboard.call(r, flagged), dashboard.rank_lookup(r.date)
    S = (("away", r.away), ("home", r.home))
    teams = {}
    for (s_, t), (o_, opp) in ((S[0], S[1]), (S[1], S[0])):
        proj, avg, up, down = dashboard.team_reasons(r, s_, t, o_, opp, rk, v)
        gname = dashboard.goalie_parts(getattr(r, f"{o_}_goalie", ""))[0]
        x = {"projected_goals": round(float(proj), 2)}
        if avg is not None:
            x["vs_an_average_team"] = f"{proj - avg:+.2f}"
        x["five_on_five"] = f"{dashboard.tier('ev', v(s_, 'ev'))} ({v(s_, 'ev'):.2f} projected goals)"
        x["power_play"] = f"{dashboard.tier('pp', v(s_, 'pp'))} ({v(s_, 'pp'):.2f} projected goals)"
        x["goalie_faced"] = (f"{gname}, {dashboard.GL_WORDS.get(dashboard.tier('gadj', v(s_, 'gadj')), 'a goalie')}, "
                             f"grade {dashboard.goalie_grade(v(s_, 'gadj'))}" if not pd.isna(v(s_, "gadj")) else gname)
        x["pushing_up"] = [f"{label} {eff:+.2f} ({why})" for eff, label, why in up]
        x["holding_back"] = [f"{label} {eff:+.2f} ({why})" for eff, label, why in down]
        x["players_out"] = _out(getattr(r, f"{s_}_out", None))
        fm, ctx = form.get(t, {}), {}
        for k in ("record", "streak", "last10_record", "last10_goals_for", "last10_goals_against"):
            if fm.get(k) is not None:
                ctx[k] = fm[k]
        if val(f"{s_}_l10_n"):
            ctx["last10_games_with_7_plus_total_goals"] = f"{int(val(f'{s_}_l10_7'))} of {int(val(f'{s_}_l10_n'))}"
            ctx["last10_games_average_total_goals"] = val(f"{s_}_l10_avg")
        w2 = fm.get("last_2_weeks")
        if w2:
            sc = w2["scored_vs_projection_per_game"]
            ctx["last_2_weeks"] = {**w2, "means": "scoring more than the model projected" if sc >= 0.5 else
                                   "scoring less than the model projected" if sc <= -0.5 else "scoring about as projected"}
        g = form.get(opp, {}).get("goalie")  # the goalie this team shoots at = the opponent's starter
        if g and _goalie_means(g, t):
            ctx["goalie_faced_lately"] = {**g, "means": _goalie_means(g, t)}
        x["recent_form"] = ctx
        teams[t] = x
    f = {"game": f"{r.away} @ {r.home}", "call": call,
         "why_this_call": plain(dashboard.reasoning(r, flagged)).split(" At 5-on-5,")[0],
         "projected_total": round(float(r.proj), 2), "chance_of_7_plus_goals": f"{r.p7:.0%}",
         "over_flag_needs": f"both teams {r.cutoff:.2f}+ projected goals and a line of 6 or 6.5",
         "how_calls_like_this_did_2021_26": dashboard.CALL_HISTORY[call], "teams": teams}
    if val("bet_total") is not None:
        f["line"] = f"{val('bet_total'):g}"
        if val("open_total") is not None and val("open_total") != val("bet_total"):
            f["line_moved"] = f"from {val('open_total'):g} to {val('bet_total'):g}"
    if "aren't confirmed" in plain(dashboard.reasoning(r, flagged)):
        f["watch"] = "starting goalies aren't confirmed yet"
    if val("h2h_n"):
        f["head_to_head_since_2020"] = {"games": int(val("h2h_n")), "average_total_goals": val("h2h_avg"),
                                        "games_with_7_plus": int(val("h2h_7")), "last_meetings": val("h2h_last")}
    if not pd.isna(r.final_total):
        f["result"] = {"final": f"{r.away} {int(r.away_score)}, {r.home} {int(r.home_score)}", "total_goals": int(r.final_total),
                       **(debrief or {})}
    return f


def leads(f):
    """[(score, kind, angle)]: what's unusual about this game. run() gives the slate's games different kinds."""
    if "result" in f:
        return [(1.0, "result", "how the goals actually came, compared with what the model expected")]
    c = [(0.5, "call", "the model's call and the matchup behind it")]
    for t, x in f["teams"].items():
        fm = x["recent_form"]
        s = fm.get("streak") or ""
        if s[:1] in ("W", "L") and s[1:].isdigit() and int(s[1:]) >= 3:
            c.append((1.0 + int(s[1:]) / 5, "streak", f"{t}'s {'winning' if s[0] == 'W' else 'losing'} streak ({s})"))
        w = (fm.get("last10_record") or "").split("-")[0]
        if w.isdigit() and (int(w) >= 7 or int(w) <= 3):
            c.append((1.2, "last10", f"{t}'s last 10 games ({fm['last10_record']})"))
        g = fm.get("goalie_faced_lately")
        if g and not g["means"].startswith("about"):
            c.append((1.1, "goalie", f"the goalie {t} faces ({x['goalie_faced']}) and how he has played lately"))
        w2 = fm.get("last_2_weeks")
        if w2 and not w2["means"].endswith("as projected"):
            c.append((1.0 + abs(w2["scored_vs_projection_per_game"]) / 2, "scoring", f"{t}'s scoring over the last two weeks"))
        for z in x["pushing_up"][:1] + x["holding_back"][:1]:
            m = re.search(r" ([+-]\d+\.\d\d) ", z)
            if m and abs(float(m.group(1))) >= 0.2:
                c.append((0.9 + abs(float(m.group(1))), "factor", f"the biggest factor in the model's projection: {t}'s {z.split(' (')[0]}"))
        if x["players_out"]:
            c.append((0.7, "injuries", f"who {t} is missing"))
    if f.get("line_moved"):
        c.append((0.8, "line", f"the line move ({f['line_moved']})"))
    return c


# ---- Gemini ----

def ask(model, system, prompt):
    """(text, finish reason) from one model."""
    key = os.environ.get("GEMINI_API_KEY")
    body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 1.0, "maxOutputTokens": 8192}}  # room for a thinking model's thoughts + the note
    req = urllib.request.Request(API.format(model), data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})  # key in a header, never the URL
    with urllib.request.urlopen(req, timeout=90) as f:
        out = json.load(f)
    c = out["candidates"][0]
    return "".join(p.get("text", "") for p in c["content"]["parts"] if not p.get("thought")).strip(), c.get("finishReason", "")


def gemini(system, prompt):
    """(text, finish reason, model) from the first model in MODELS that answers."""
    last = None
    for model in MODELS:
        try:
            return (*ask(model, system, prompt), model)
        except urllib.error.HTTPError as e:
            if e.code not in (404, 429, 500, 503):
                raise
            print(f"  ({model}: {e.code}, trying the next model)")
            last = e
            time.sleep(2)
    raise last


NUM = re.compile(r"(?<![\w.])[+\-−]?\d+(?:\.\d+)?(?:-\d+){0,2}%?")


def numbers(s):
    """Every number in a text, normalized ('−0.14' -> '-0.14'; '5-on-5' etc. are not numbers here)."""
    s = re.sub(r"\b\d-on-\d\b", " ", str(s).replace("−", "-"))
    return {m.group(0) for m in NUM.finditer(s)}


ALWAYS_OK = {"5", "10"}  # "last 5" / "last 10" games, whether or not the facts spell it out


def allowed(f):
    """Numbers a note may use: every number in its facts (with and without sign / percent sign), and the final score
    either way round ('5-4')."""
    out, s = set(ALWAYS_OK), json.dumps(f, ensure_ascii=False)
    for n in numbers(s) | set(re.findall(r"\d+(?:\.\d+)?", s)):  # the 2nd: digits inside codes ('W4' -> 4 straight, '#2')
        out |= {n, n.lstrip("+-"), n.rstrip("%"), n.lstrip("+-").rstrip("%")}
    score = re.findall(r"\d+", (f.get("result") or {}).get("final", ""))
    if len(score) == 2:
        out |= {f"{score[0]}-{score[1]}", f"{score[1]}-{score[0]}"}
    return out


def check(text, f, finish="STOP"):
    """'' when the note is usable, else why not (sent back to Gemini on the retry)."""
    words = len(text.split())
    if finish not in ("STOP", "") or not re.search(r"[.?]['\")”’]?$", text.strip()):
        return "it stops mid-sentence; write the whole note, ending with a full stop"
    if not WORDS[0] <= words <= WORDS[1]:
        return f"it is {words} words; write 60-110"
    if "\n" in text.strip() or re.search(r"\*\*|!|^\s*(?:#|[-•*] )", text, re.M):  # (a '#' rank like '#2 defense' is fine)
        return "use one plain paragraph: no line breaks, markdown, lists or exclamation marks"
    if f["call"] not in text:
        return f"say the model's call, {f['call']}, by name"
    other = [c for c in CALLS if c != f["call"] and re.search(rf"\b{c}\b", text)]
    if other:
        return f"only the model's call ({f['call']}) may be named, not {', '.join(other)}"
    ok = allowed(f)
    bad = sorted(n for n in numbers(text) if n not in ok and n.lstrip("+-").rstrip("%") not in ok)
    if bad:
        return f"these numbers are not in the facts: {', '.join(bad)}. Use only numbers copied from the facts"
    return ""


def opening(text):
    return " ".join(text.split()[:8])


def write_note(f, used, lead):
    """(text, '', model) or (None, why, model) after up to 2 tries."""
    prompt = (f"Facts:\n{json.dumps({**f, 'lead_with': lead, 'openings_used_today': used}, ensure_ascii=False)}\n\n"
              "Write the note.")
    why, model = "", None
    for _ in range(2):
        text, finish, model = gemini(SYSTEM, prompt if not why else prompt + f"\n\nYour last version can't be used: {why}. Rewrite it.")
        why = check(text, f, finish)
        if not why:
            return text, "", model
        time.sleep(PAUSE)
    return None, why, model


# ---- colors (applied when the dashboard renders a note) ----

def colors(f):
    """{number as written: css classes}, from the model's numbers: goal effects, team projections, 5-on-5 / power-play
    projections and the chance of 7+ by what they mean for tonight's goals (the breakdown table's tiers, green = more);
    last-10 records hot / cold (form, not goals)."""
    out = {}
    lvl = lambda v: "t-great" if v >= 0.10 else "t-good" if v >= 0.03 else "t-trash" if v <= -0.10 else "t-bad" if v <= -0.03 else "t-mid"
    cut = re.search(r"(\d+\.\d\d)\+", f.get("over_flag_needs", ""))
    for t, x in f["teams"].items():
        for z in x["pushing_up"] + x["holding_back"] + [x.get("vs_an_average_team") or ""]:
            m = re.search(r"([+-]\d+\.\d\d)\b", z)
            if m:
                out[m.group(1)] = lvl(float(m.group(1)))
        if cut:
            out[f"{x['projected_goals']:.2f}"] = "t-good" if x["projected_goals"] >= float(cut.group(1)) else "t-bad"
        for k in ("five_on_five", "power_play"):
            m = re.match(r"(great|good|mid|bad|trash) \((\d+\.\d\d)", x.get(k, ""))
            if m:
                out[m.group(2)] = f"t-{m.group(1)}"
        rec = x["recent_form"].get("last10_record") or ""
        w = rec.split("-")[0]
        if w.isdigit():
            out[rec] = "hot" if int(w) >= 7 else "cold" if int(w) <= 3 else "even"
    p = f.get("chance_of_7_plus_goals", "")
    if p.rstrip("%").isdigit():
        out[p] = "t-good" if int(p.rstrip("%")) >= 50 else "t-bad" if int(p.rstrip("%")) <= 42 else "t-mid"
    return out


def colorize(text, cls):
    """HTML for a note: escaped, with each known number wrapped in its color chip."""
    s = html.escape(text).replace("−", "-")
    if not cls:
        return s
    pat = re.compile(r"(?<![\w.])(?:" + "|".join(sorted((re.escape(k) for k in cls), key=len, reverse=True)) + r")(?![\w.]*\d)")
    return pat.sub(lambda m: f"<span class='nv {cls[m.group(0)]}'>{m.group(0)}</span>", s)


# ---- the run ----

def signature(f):
    """What a note depends on: a new note only when one of these changes (not on every hundredth of a goal or price)."""
    t = {k: {"proj": round(v["projected_goals"] * 20) / 20, "out": v.get("players_out"), "goalie": v.get("goalie_faced"),
             "form": [v["recent_form"].get("streak"), v["recent_form"].get("last10_record")]} for k, v in f["teams"].items()}
    return json.dumps({"call": f["call"], "teams": t, "line": f.get("line"), "watch": f.get("watch"), "result": f.get("result")},
                      sort_keys=True, default=str)


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
            print("(models this key can use: " + ", ".join(m for m in models() if "flash" in m or "pro" in m) + ")")
        except Exception as e:
            print(f"(couldn't list the models: {type(e).__name__}: {str(e)[:120]})")
        print(f"(trying, in order: {', '.join(MODELS)})")
    today = date.today().isoformat()
    log = dashboard.current(paper.read_log())
    days = [d for d in (today, (date.today() - timedelta(days=1)).isoformat()) if (log.date == d).any()]  # tonight's first
    calls, made, kept, failed = 0, 0, 0, []
    now = pd.Timestamp.now(tz="UTC")
    for day in days:
        d = load(day)
        notes, form, dbr = d.get("notes", {}), d.get("form", {}), d.get("debrief", {})
        g = log[log.date == day]
        used = [opening(n["text"]) for n in notes.values() if n.get("text")]
        kinds = Counter(n.get("lead_kind") for n in notes.values() if n.get("lead_kind"))
        todo = []
        for r in g.itertuples():
            key = f"{r.away}@{r.home}"
            if isinstance(r.start_utc, str) and pd.Timestamp(r.start_utc) <= now and pd.isna(r.final_total):
                continue  # under way: keep the pre-game note until it's final
            if not pd.isna(r.final_total) and key not in dbr:
                try:
                    dbr[key] = debrief(r.game_id)
                except Exception as e:
                    print(f"(game notes: no scoring summary for {key} yet: {type(e).__name__})")
            f = facts(r, dashboard._is(r.flag), form, dbr.get(key))
            if f is None:
                continue
            sig = signature(f)
            if notes.get(key, {}).get("sig") == sig:
                kept += 1
            else:
                todo.append((key, f, sig))
        # the slate's most unusual games pick their angle first; a kind already used today counts less
        todo.sort(key=lambda z: -max(c[0] for c in leads(z[1])))
        for key, f, sig in todo:
            if calls >= MAX_CALLS:
                break
            score, kind, lead = max(leads(f), key=lambda c: c[0] - 0.6 * kinds[c[1]])
            try:
                text, why, model = write_note(f, used, lead)
                calls += 1
            except urllib.error.HTTPError as e:
                print(f"(game notes: Gemini answered {e.code}: {e.read().decode()[:160]})")
                if e.code in (429, 403, 404, 503):
                    calls = MAX_CALLS  # out of free requests, no access, no model or every model overloaded: try next run
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
            kinds[kind] += 1
            notes[key] = {"text": text, "colors": colors(f), "sig": sig, "model": model, "lead_kind": kind,
                          "at": pd.Timestamp.now(tz="America/New_York").strftime("%-I:%M %p"), "kind": "debrief" if "result" in f else "preview"}
            used.append(opening(text))
            made += 1
            if preview:
                print(f"\n=== {key} ({f['call']}, lead: {lead}) ===\n{text}")
            time.sleep(PAUSE)
        d.update(notes=notes, debrief=dbr)
        save(day, d)  # (--preview runs in a checkout that is never committed)
        if preview and day == today:  # exactly what the dashboard will show, for a look before it goes live
            dashboard._NOTES.clear()
            for r in g.itertuples():
                print("PREVIEW_HTML " + json.dumps({"key": f"{r.away}@{r.home}", "html": dashboard.game_notes(r, dashboard._is(r.flag))}))
    print(f"(game notes: {made} written, {kept} unchanged, {len(failed)} kept the template, {calls} notes asked for)")
    health.note(f"✓ Game notes (Gemini): {made} written, {kept} unchanged" + (f"; {len(failed)} kept the template ({', '.join(failed)})" if failed else ""))


if __name__ == "__main__":
    run(preview="--preview" in sys.argv)
