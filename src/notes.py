"""AI-written game notes (Google Gemini, free tier): a short paragraph for each of today's games, before it starts, that
reads like it was written for that game, in place of the fixed template. Today's slate only: the Tomorrow preview tab,
finished games and past days keep the template (dashboard.game_notes).

Facts in, writing out. The AI gets only the model's and the dashboard's own numbers (facts()): the call and why (the
template's reason in plain words: plain_reason), the projected total vs the line and the chance of 7+, and per team its
record, last-10 record and streak (NHL standings, saved by the model run: form_snapshot), projected goals, 5-on-5 /
power-play rating and projected goals with the attack's rank vs the opposing defense's (the matchup table), the goalie
it faces (tag, grade, his numbers this season and over his last 5 games), the model's factors pushing its goals up or
holding them back (dashboard.team_reasons), its Team rankings (total offense / defense ranks, the nine stats) and Form
over the season and the last 30 / 14 / 7 days (form_windows), with a legend (READ). The note must cover all of it for
both teams; each game on a slate opens on a different kind of topic (leads(), assigned in run()). A check rejects a note
that leaves out a team's record, last-10 record or projected goals or the projected total, uses a number not in the
facts, names another call, leaves out the call, stops mid-sentence, says 'cutoff', copies its opening topic's wording or
leaks the fact sheet's field names (one retry, then the template stays). New notes only at the 12:17, 3:17, 6:17 and
8:17 PM runs (ai_run), and there only for games whose facts changed since their last note (signature()); in between,
the last note stays up until the game is final, with a one-line notice when the call has changed since
(dashboard.game_notes). Saved in data/notes/<day>.json. No GEMINI_API_KEY (GitHub secret), or Gemini failing / out
of free requests = the template, as before.

  python3 src/notes.py             # after projecting: writes only at the 12:17 / 3:17 / 6:17 / 8:17 PM runs
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
from datetime import date

import pandas as pd

import paths

# tried in order: an overloaded / unavailable / out-of-free-requests model hands over to the next (each has its own free
# allowance; Flash first, the Lite models last). Nov 4 2026: 2.5-flash 404s for new keys, the newest Flash answered 503
# "high demand" all afternoon, and by midnight flash-latest and 3.6-flash were out of free requests (429).
MODELS = list(dict.fromkeys(m for m in (os.environ.get("GEMINI_MODEL"), "gemini-flash-latest", "gemini-3.8-flash",
                                        "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-flash-lite-latest",
                                        "gemini-3.5-flash-lite", "gemini-3.1-flash-lite") if m))
API = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
MAX_CALLS = 16   # notes per run (a full slate): the free tier allows a limited number of requests a day (per Google project)
PAUSE = 6        # seconds between notes (the free tier allows ~10 requests a minute)
BUDGET = 600     # seconds of writing per run (~30 s a note), so a slow Gemini can't hold the run's commit up for long
NOTE_WAIT = 240  # seconds of trying models for one note, both tries, before giving up on it (a request times out after 90 s)
PREVIEW_BUDGET = 1200  # a preview's writing time, so it ends (and prints) inside its workflow's time limit
NOTE_HOURS = (12, 15, 18, 20)                    # new notes only at the 12:17, 3:17, 6:17 and 8:17 PM runs (user's choice)
NOTE_TRIGGERS = ("hourly", "schedule", "retry")  # the keeper's hourly slot, GitHub's backup schedule, or a retry of one
WORDS = (120, 300)  # asked for 150-230; the Lite models run long (281-370 words on Nov 5)
CALLS = ("SLAM", "1U", "PASS", "AVOID")
WINDOWS = (("season", "season"), ("30", "last_30_days"), ("14", "last_14_days"), ("7", "last_7_days"))

SYSTEM = """You write the note for one of tonight's NHL games on a hockey model's dashboard, before the game starts. The
reader owns the model, bets overs (lines of 6 or 6.5 only) and knows hockey. Every fact comes from the model and its
dashboard: use them and nothing else ("how_to_read" explains them).
1. Explain the model's call ("call": SLAM, 1U, PASS or AVOID) with the model's numbers. Say the call by name. Never
   suggest a different call or a different bet.
2. Cover all of this, for both teams, in whatever order reads best:
   - each team's record and last-10 record, copied exactly as written (like 9-6-1);
   - the projection: each team's projected goals, the projected total against the line, the chance of 7 or more goals;
   - 5-on-5 and the power play: the rating and projected goals, and the attack's rank against the opposing defense's or
     penalty kill's rank;
   - the goalie each team faces, who is the OTHER team's goalie (the facts say whose): his tag and grade, and his
     numbers this season and over his last 5 games;
   - the rankings: total offense and total defense ranks (a standout stat or two), and the Form ranks over the season
     and the last 30, 14 and 7 days, saying how they moved (skip a window that has the same games as the season).
3. Use only the facts. Copy every number exactly as written: never round, add, or invent numbers, players, results or
   history. Write ranks like #9. The "means" fields tell you what a number means: follow them.
4. 150-230 words, one paragraph of complete sentences, plain text: no headings, lists, markdown, emojis or exclamation
   marks.
5. The first sentence is about "opening_topic", in your own words: start it with a capital letter and don't reuse the
   topic's wording. Don't open the way any of "openings_used_today" open, and don't start with a player's name unless
   opening_topic is about that player.
6. Records, streaks, Form ranks and a goalie's recent games are context: the model already counts every game, and form
   alone hasn't predicted totals. Use them to make the note specific to this game, never as the reason to bet.
7. Plain words, like a sharp hockey writer. Never write "cutoff" or "threshold" (say what it means: both teams need to
   project at least that many goals) or the fact sheet's field names. Specific, varied sentences, no cliches, no hype."""
JARGON = re.compile(r"\bcut-?offs?\b|\bthresholds?\b", re.I)
READ = {  # sent with every game's facts (the dashboard's own explanations, shortened)
    "ranks": "#1 = best of the 32 teams at that thing; for a defense or penalty kill #1 = fewest goals allowed",
    "rating": "the model's tier for that part of tonight's projected goals: great, good, mid, bad or trash",
    "five_on_five / power_play": "attack = goals a game the team scores against an average opponent; opponent's "
                                 "defense / penalty kill = goals a game it allows; both as of today, with their ranks",
    "team_rankings": "the Team rankings tab: nine stats per game (offense: made; defense: allowed), combined into a total "
                     "offense rank and a total defense rank. xG = expected goals, SOG = shots on goal, Att = shot attempts, "
                     "HD = high-danger shots, HD xG = expected goals from them, PPG = power-play goals, Reb = rebound "
                     "shots, Reb G = rebound goals",
    "form_by_window": "the Team rankings tab's Form view, per game, over the season and the last 30 / 14 / 7 days: "
                      "scoring + = scored more than the model projected; allowing + = allowed fewer than projected; "
                      "net = both together; finishing + = scored more than its expected goals; goaltending + = its "
                      "goalies stopped more than expected (both vs the league average); rank by net, #1 = best",
    "goalie_faced": "the OTHER team's starter, the goalie this team shoots at (named with his team): tag and grade "
                    "(1-100, higher = better goalie), and what he does to this "
                    "team's projected goals"}


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

def goalie_games(gid, season, n=None):
    """{'games', 'goals_allowed', 'expected_goals_against'} over a goalie's regular-season games this season (the
    last n when given; MoneyPuck, data/goalie_games.csv)."""
    import goalies
    if gid is None or pd.isna(gid):
        return None
    if not hasattr(goalie_games, "gg"):
        goalie_games.gg = pd.read_csv(goalies.GOALIE_GAMES)
    g = goalie_games.gg
    g = g[(g.playerId == gid) & (g.season == season) & (g.gameId.astype(int).astype(str).str[4:6] == "02")].sort_values("gameId")
    g = g.tail(n) if n else g
    if not len(g):
        return None
    return {"games": int(len(g)), "goals_allowed": int(g.goals.sum()), "expected_goals_against": round(float(g.xGoals.sum()), 1)}


def form_snapshot(day, standings, starters, started, season):
    """Each playing team's record, last 10 and streak (NHL standings) and its starter's numbers this season and over
    his last 5 games, saved in data/notes/<day>.json under 'form' and frozen at puck drop (also the form strip).
    standings: NHL standings rows (elimination.standings); starters: {team: (goalie name, NHL id or None)};
    started: teams whose game began."""
    d = load(day)
    old = d.get("form", {})
    rows = {r["teamAbbrev"]["default"]: r for r in standings or []}
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
        g = {k: goalie_games(gid, season, n) for k, n in (("this_season", None), ("last_5_games", 5))}
        if gname and g["this_season"]:
            t["goalie"] = {"name": gname, **g}
        out[team] = t
    d["form"] = {**old, **out}
    save(day, d)


# ---- the fact sheet: the model's numbers, then form as context ----

def plain(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(s))).split())


def plain_reason(s):
    """The template's reason for the call without the dashboard's shorthand ('cutoff', 'high-scoring'), so the AI
    doesn't copy it: 'both teams project at least 3.10 goals (OTT 3.30, BUF 3.38)'. Same numbers, same meaning."""
    s = re.sub(r"project as high-scoring \((\w+) (\d+\.\d\d), (\w+) (\d+\.\d\d); cutoff (\d+\.\d\d)\)",
               r"project at least \5 goals (\1 \2, \3 \4)", s)
    s = re.sub(r"under the (\d+\.\d\d)-goal high-scoring cutoff", r"under the \1 goals both teams need for an over", s)
    s = re.sub(r"just misses the cutoff \(by (\d+\.\d\d)\), and the rule needs both teams over it",
               r"falls \1 goals short, and the over rule needs both teams there", s)
    return s.replace("an over but not a slam", "an over, but not the model's strongest kind")


def _out(v):
    """'Tyler Kleven|-0.0158|0.0105; ...' -> ['Tyler Kleven']"""
    return [x.split("|")[0].strip() for x in str(v or "").split(";") if x.strip() and x.strip() != "nan"]


def _goalie_line(n):
    """'8 games, 25 goals allowed on 21.3 expected: 3.7 more than expected (worse)' (goalie_games)."""
    d = round(n["expected_goals_against"] - n["goals_allowed"], 1)
    return (f"{n['games']} games, {n['goals_allowed']} goals allowed on {n['expected_goals_against']} expected: "
            + (f"{d:.1f} fewer than expected (better)" if d > 0 else f"{-d:.1f} more than expected (worse)" if d < 0 else "as expected"))


def _goalie_means(g, team):
    """What a goalie's last 5 games mean for the team shooting at him (g = form_snapshot's 'goalie')."""
    x = g.get("last_5_games")
    if not x:
        return None
    d = round(x["expected_goals_against"] - x["goals_allowed"], 1)
    return (f"he has been better than expected, stopping {d:.1f} more goals than expected: harder for {team} to score" if d >= 1.5
            else f"he has been worse than expected, allowing {-d:.1f} more goals than expected: easier for {team} to score" if d <= -1.5
            else "about as expected")


def form_windows():
    """{team: {window: the Form view's numbers}} over the season and the last 30 / 14 / 7 days (dashboard.form_frame):
    rank by net (#1 = best), net, scoring, allowing, finishing, goaltending (per game) and games; 'same games as the
    season' for a window that adds nothing (early in the season). Cached per run."""
    import dashboard
    if not hasattr(form_windows, "out"):
        f, out = dashboard.form_frame(), {}
        if f is not None:
            f = f.assign(window=f.window.astype(str))
            season_gp = f[f.window == "season"].set_index("team").gp
            for win, name in WINDOWS:
                x = f[f.window == win].sort_values("net", ascending=False).reset_index(drop=True)
                for i, w in x.iterrows():
                    out.setdefault(w.team, {})[name] = (
                        "same games as the season" if win != "season" and season_gp.get(w.team) == w.gp else
                        {"rank": i + 1, **{c: f"{w[c]:+.2f}" for c in ("net", "scoring", "allowing", "finishing", "goaltending")
                                           if pd.notna(w[c])}, "games": int(w.gp)})
        form_windows.out = out
    return form_windows.out


def facts(r, flagged, form):
    """What the note may say about one game (a dashboard.current row): the model's numbers first, form as context.
    None when the game has no breakdown (the template explains it)."""
    import dashboard
    v = lambda s_, k: getattr(r, f"{s_}_{k}", float("nan"))
    val = lambda c: None if pd.isna(getattr(r, c, None)) else getattr(r, c)
    if pd.isna(v("away", "ev")) or pd.isna(r.cutoff):
        return None
    call, rk = dashboard.call(r, flagged), dashboard.rank_lookup(r.date)
    windows = form_windows()
    S = (("away", r.away), ("home", r.home))
    teams = {}
    for (s_, t), (o_, opp) in ((S[0], S[1]), (S[1], S[0])):
        proj, avg, up, down = dashboard.team_reasons(r, s_, t, o_, opp, rk, v)
        fm, me, them = form.get(t, {}), rk.get(t), rk.get(opp)
        x = {k: fm[k] for k in ("record", "last10_record", "streak") if fm.get(k)}  # NHL standings (form_snapshot)
        x["projected_goals"] = f"{proj:.2f}"
        if avg is not None:
            x["vs_an_average_team"] = f"{proj - avg:+.2f}"
        for key, unit, against in (("five_on_five", "ev", "opponent_defense"), ("power_play", "pp", "opponent_penalty_kill")):
            if pd.isna(v(s_, unit)):
                continue
            z = {"rating": dashboard.tier(unit, v(s_, unit)), "projected_goals": f"{v(s_, unit):.2f}"}
            if me is not None and them is not None and f"r_gf_{unit}" in me and f"r_ga_{unit}" in them:  # = the matchup table
                z["attack"] = {"goals_a_game": f"{me[f'gf_{unit}']:.2f}", "rank": int(me[f"r_gf_{unit}"])}
                z[against] = {"goals_allowed_a_game": f"{them[f'ga_{unit}']:.2f}", "rank": int(them[f"r_ga_{unit}"])}
            x[key] = z
        gname = dashboard.goalie_parts(getattr(r, f"{o_}_goalie", ""))[0]
        x["goalie_faced"] = (f"{gname} ({opp}'s goalie): {dashboard.GL_WORDS.get(dashboard.tier('gadj', v(s_, 'gadj')), 'a goalie')}, "
                             f"grade {dashboard.goalie_grade(v(s_, 'gadj'))}, {v(s_, 'gadj') * 100:+.1f}% to {t}'s goals"
                             if not pd.isna(v(s_, "gadj")) else f"{gname} ({opp}'s goalie)")  # whose goalie: the AI once flipped them
        g = form.get(opp, {}).get("goalie")  # the goalie this team shoots at = the opponent's starter
        if g:
            x["goalie_faced_numbers"] = {k: _goalie_line(g[k]) for k in ("this_season", "last_5_games") if g.get(k)}
            if _goalie_means(g, t):
                x["goalie_faced_numbers"]["means"] = _goalie_means(g, t)
        x["pushing_up"] = [f"{label} {eff:+.2f} ({why})" for eff, label, why in up]
        x["holding_back"] = [f"{label} {eff:+.2f} ({why})" for eff, label, why in down]
        x["players_out"] = _out(getattr(r, f"{s_}_out", None))
        if me is not None and "r_score_off" in me and "r_score_def" in me:  # the Team rankings tab
            x["team_rankings"] = {
                "total_offense_rank": int(me["r_score_off"]), "total_defense_rank": int(me["r_score_def"]),
                **{f"{side}_stats": ", ".join(f"{h} {me[f'{k}{c}']:.{dec}f} (#{int(me[f'r_{k}{c}'])})"
                                              for k, h, dec, _ in dashboard.RANK_STATS if f"r_{k}{c}" in me)
                   for side, c in (("offense", "F"), ("defense_allowed", "A"))}}
        if windows.get(t):
            x["form_by_window"] = windows[t]
        for k in ("last10_goals_for", "last10_goals_against"):
            if fm.get(k) is not None:
                x[k] = fm[k]
        if val(f"{s_}_l10_n"):
            x["last10_games_with_7_plus_total_goals"] = f"{int(val(f'{s_}_l10_7'))} of {int(val(f'{s_}_l10_n'))}"
            x["last10_games_average_total_goals"] = val(f"{s_}_l10_avg")
        teams[t] = x
    reason = plain(dashboard.reasoning(r, flagged))
    f = {"game": f"{r.away} @ {r.home}", "call": call, "why_this_call": plain_reason(reason.split(" At 5-on-5,")[0]),
         "projected_total": f"{r.proj:.2f}", "chance_of_7_plus_goals": f"{r.p7:.0%}",
         "over_flag_needs": f"both teams {r.cutoff:.2f}+ projected goals and a line of 6 or 6.5",
         "how_calls_like_this_did_2021_26": dashboard.CALL_HISTORY[call], "how_to_read": READ, "teams": teams}
    if val("bet_total") is not None:
        f["line"] = f"{val('bet_total'):g}"
        if val("open_total") is not None and val("open_total") != val("bet_total"):
            f["line_moved"] = f"from {val('open_total'):g} to {val('bet_total'):g}"
    if "aren't confirmed" in reason:
        f["watch"] = "starting goalies aren't confirmed yet"
    if val("h2h_n"):
        f["head_to_head_since_2020"] = {"games": int(val("h2h_n")), "average_total_goals": val("h2h_avg"),
                                        "games_with_7_plus": int(val("h2h_7")), "last_meetings": val("h2h_last")}
    return f


def leads(f):
    """[(score, kind, topic)]: what's unusual about this game. run() gives the slate's games different kinds."""
    c = [(0.5, "call", "the model's call and the matchup behind it")]
    for t, x in f["teams"].items():
        s = x.get("streak") or ""
        if s[:1] in ("W", "L") and s[1:].isdigit() and int(s[1:]) >= 3:
            c.append((1.0 + int(s[1:]) / 5, "streak", f"{t}'s {'winning' if s[0] == 'W' else 'losing'} streak ({s})"))
        w = (x.get("last10_record") or "").split("-")[0]
        if w.isdigit() and (int(w) >= 7 or int(w) <= 3):
            c.append((1.2, "last10", f"{t}'s last 10 games ({x['last10_record']})"))
        g = x.get("goalie_faced_numbers", {}).get("means")
        if g and not g.startswith("about"):
            name = x["goalie_faced"].split(" (")[0]
            opp = next(k for k in f["teams"] if k != t)
            c.append((1.1, "goalie", f"the goalie {t} faces ({name}, {opp}'s goalie) and how he has played lately"))
        fw = x.get("form_by_window", {})
        late = next(((k, fw[k]) for k in ("last_7_days", "last_14_days", "last_30_days") if isinstance(fw.get(k), dict)), None)
        if isinstance(fw.get("season"), dict) and late and abs(fw["season"]["rank"] - late[1]["rank"]) >= 10:
            move = abs(fw["season"]["rank"] - late[1]["rank"])
            c.append((1.0 + move / 20, "form", f"how {t}'s Form rank has moved (#{fw['season']['rank']} over the season, "
                                               f"#{late[1]['rank']} over the {late[0].replace('_', ' ')})"))
        for z in x["pushing_up"][:1] + x["holding_back"][:1]:
            m = re.search(r" ([+-]\d+\.\d\d) ", z)
            if m and abs(float(m.group(1))) >= 0.2:
                c.append((0.9 + abs(float(m.group(1))), "factor", f"the biggest factor in the model's projection ({t}: {z.split(' (')[0]})"))
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
            "generationConfig": {"temperature": 1.0, "maxOutputTokens": 16384}}  # room for a thinking model's thoughts + the
    # note (8192 ran out: a 3.6-flash note was cut off by MAX_TOKENS on Nov 5)
    req = urllib.request.Request(API.format(model), data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})  # key in a header, never the URL
    with urllib.request.urlopen(req, timeout=90) as f:
        out = json.load(f)
    c = out["candidates"][0]
    return "".join(p.get("text", "") for p in c["content"]["parts"] if not p.get("thought")).strip(), c.get("finishReason", "")


def quota(body):
    """'(out of free requests: per-day limit 20)' from a 429's error body (which free limit, so the log says whether
    waiting a minute helps); '(overloaded)' for a 503; '' otherwise."""
    if "UNAVAILABLE" in body or "overloaded" in body.lower() or "high demand" in body.lower():
        return "(overloaded)"
    per = re.search(r"Per(Day|Minute)", body)
    lim = re.search(r"limit: (\d+)", body)
    if per or lim or "RESOURCE_EXHAUSTED" in body:
        return ("(out of free requests" + (f": per-{per.group(1).lower()}" if per else "")
                + (f" limit {lim.group(1)}" if lim else "") + ")")
    return ""


def gemini(system, prompt, deadline=None):
    """(text, finish reason, model) from the first model in MODELS that answers; when none does, one more pass after a
    pause (an overload usually clears in seconds). A model that doesn't answer in time (or drops the connection) hands
    over to the next one and isn't asked again for this note; past the deadline (write_note: NOTE_WAIT seconds for the
    whole note) no new model is tried. Every answer and failure is logged with how long it took."""
    last, slow = None, set()
    deadline = deadline or time.time() + NOTE_WAIT
    for attempt in range(2):
        for model in MODELS:
            if model in slow or time.time() > deadline:
                continue
            t = time.time()
            try:
                out = ask(model, system, prompt)
                print(f"  ({model} answered in {time.time() - t:.0f} s)")
                return (*out, model)
            except urllib.error.HTTPError as e:
                if e.code not in (404, 429, 500, 503):
                    raise
                e.detail = quota(e.read().decode(errors="replace"))
                print(f"  ({model}: {e.code}{' ' + e.detail if e.detail else ''} after {time.time() - t:.0f} s, trying the next model)")
                last = e
                time.sleep(2)
            except (TimeoutError, urllib.error.URLError) as e:  # (HTTPError, a URLError, is caught above)
                print(f"  ({model}: no answer after {time.time() - t:.0f} s ({type(e).__name__}), trying the next model)")
                last = e
                slow.add(model)
        if not attempt and time.time() < deadline:
            print("  (no model answered: one more pass in 30 s)")
            time.sleep(30)
    raise last or TimeoutError("no time left for this note")


NUM = re.compile(r"(?<![\w.])[+\-−]?\d+(?:\.\d+)?(?:-\d+){0,2}%?")


def numbers(s):
    """Every number in a text, normalized ('−0.14' -> '-0.14'; '5-on-5' etc. are not numbers here)."""
    s = re.sub(r"\b\d-on-\d\b", " ", str(s).replace("−", "-"))
    return {m.group(0) for m in NUM.finditer(s)}


ALWAYS_OK = {"5", "10"}  # "last 5" / "last 10" games, whether or not the facts spell it out


def allowed(f):
    """Numbers a note may use: every number in its facts (with and without sign / percent sign)."""
    out, s = set(ALWAYS_OK), json.dumps(f, ensure_ascii=False)
    for n in numbers(s) | set(re.findall(r"\d+(?:\.\d+)?", s)):  # the 2nd: digits inside codes ('W4' -> 4 straight, '#2')
        out |= {n, n.lstrip("+-"), n.rstrip("%"), n.lstrip("+-").rstrip("%")}
    return out


def copied(text, topic, n=4):
    """The first n-word run of the note's first sentence that repeats the opening topic's own wording (the AI copying
    its brief instead of writing), else ''. The facts in the topic's brackets (names, records) may be repeated."""
    words = lambda s: re.findall(r"[\w'#+-]+(?:\.\d+)?", s.lower())
    t = words(re.sub(r"\([^)]*\)", " ", topic))
    first = words(re.split(r"(?<=[.?])\s", text.strip(), maxsplit=1)[0])
    runs = {tuple(t[i:i + n]) for i in range(len(t) - n + 1)}
    return next((" ".join(first[i:i + n]) for i in range(len(first) - n + 1) if tuple(first[i:i + n]) in runs), "")


def check(text, f, finish="STOP", topic=""):
    """'' when the note is usable, else why not (sent back to Gemini on the retry). topic = its opening topic."""
    words = len(text.split())
    if finish not in ("STOP", "") or not re.search(r"[.?]['\")”’]?$", text.strip()):
        return (f"it stops mid-sentence (Gemini's finish reason: {finish or 'none'}); write the whole note, ending with "
                "a full stop")
    if words > WORDS[1]:
        return (f"it is {words} words, far too long: cut it to under 230 words. Keep every part, but give only the key "
                "number or rank for each, not every number")
    if words < WORDS[0]:
        return f"it is {words} words: write 150-230, covering every part for both teams"
    if "\n" in text.strip() or re.search(r"\*\*|!|^\s*(?:#|[-•*] )", text, re.M):  # (a '#' rank like '#2 defense' is fine)
        return "use one plain paragraph: no line breaks, markdown, lists or exclamation marks"
    if not re.match(r"[\"'“‘(]?[A-Z0-9]", text.strip()):
        return "start with a capital letter: a whole sentence in your own words"
    if f["call"] not in text:
        return f"say the model's call, {f['call']}, by name"
    other = [c for c in CALLS if c != f["call"] and re.search(rf"\b{c}\b", text)]
    if other:
        return f"only the model's call ({f['call']}) may be named, not {', '.join(other)}"
    need = [x[k] for x in f["teams"].values() for k in ("record", "last10_record", "projected_goals") if x.get(k)] + [f["projected_total"]]
    miss = [n for n in need if not re.search(rf"(?<![\w.]){re.escape(n)}(?![\w.]*\d)", text)]
    if miss:
        return (f"include these exactly as written: {', '.join(miss)} (each team's record, last-10 record and projected "
                "goals, and the projected total)")
    if JARGON.search(text):
        return f"don't say '{JARGON.search(text).group(0)}': say what it means (both teams need to project at least that many goals)"
    if "_" in text or re.search(r"\b(?:the facts|fact sheet|JSON|opening topic)\b", text, re.I):
        return "write for the reader: no field names or mentions of the facts / topic you were given"
    rep = copied(text, topic)
    if rep:
        return f"the first sentence copies the opening topic's wording ('{rep}'): say it in your own words"
    ok = allowed(f)
    bad = sorted(n for n in numbers(text) if n not in ok and n.lstrip("+-").rstrip("%") not in ok)
    if bad:
        return f"these numbers are not in the facts: {', '.join(bad)}. Use only numbers copied from the facts"
    return ""


def opening(text):
    return " ".join(text.split()[:8])


def write_note(f, used, topic):
    """(text, '', model) or (None, why, model) after up to 2 tries, all within NOTE_WAIT seconds."""
    prompt = (f"Facts:\n{json.dumps({**f, 'opening_topic': topic, 'openings_used_today': used}, ensure_ascii=False)}\n\n"
              "Write the note.")
    why, model, deadline = "", None, time.time() + NOTE_WAIT
    for _ in range(2):
        if time.time() > deadline:
            break
        text, finish, model = gemini(SYSTEM, prompt if not why else prompt + f"\n\nYour last version can't be used: {why}. Rewrite it.",
                                     deadline)
        why = check(text, f, finish, topic)
        if not why:
            return text, "", model
        print(f"  ({model}'s note can't be used: {why})")
        time.sleep(PAUSE)
    return None, why, model


# ---- colors (applied when the dashboard renders a note) ----

def colors(f):
    """{number as written: css class}, each colored the way the dashboard colors it: goal effects, team projections,
    5-on-5 / power-play projections and the chance of 7+ by what they mean for tonight's goals (the breakdown table's
    tiers, green = more); 5-on-5 / power-play ranks like the matchup table (green = good for that team's scoring); total
    offense / defense, stat and Form ranks and Form numbers like the Team rankings tab (green = strong); last-10 records
    hot / cold. A number that would get two different colors (a rank meaning different things) gets none."""
    out, clash = {}, set()

    def put(k, c):
        if out.get(k, c) != c:
            clash.add(k)
        out[k] = c
    lvl = lambda v: "t-great" if v >= 0.10 else "t-good" if v >= 0.03 else "t-trash" if v <= -0.10 else "t-bad" if v <= -0.03 else "t-mid"
    fifth = lambda good: "t-" + ("trash", "bad", "mid", "good", "great")[4 - min(4, (good - 1) * 5 // 32)]  # 1 = best of 32
    form = lambda v: "t-" + ("great" if v >= 0.5 else "good" if v >= 0.2 else "mid" if v > -0.2 else "bad" if v > -0.5 else "trash")
    cut = re.search(r"(\d+\.\d\d)\+", f.get("over_flag_needs", ""))
    for t, x in f["teams"].items():
        for z in x["pushing_up"] + x["holding_back"] + [x.get("vs_an_average_team") or ""]:
            m = re.search(r"([+-]\d+\.\d\d)\b", z)
            if m:
                put(m.group(1), lvl(float(m.group(1))))
        if cut:
            put(x["projected_goals"], "t-good" if float(x["projected_goals"]) >= float(cut.group(1)) else "t-bad")
        for k, against in (("five_on_five", "opponent_defense"), ("power_play", "opponent_penalty_kill")):
            z = x.get(k, {})
            if z.get("rating"):
                put(z["projected_goals"], f"t-{z['rating']}")
            if "attack" in z:
                put(f"#{z['attack']['rank']}", fifth(z["attack"]["rank"]))
                put(f"#{z[against]['rank']}", fifth(33 - z[against]["rank"]))  # a weak defense = good for this team's scoring
        tr = x.get("team_rankings", {})
        for k in ("total_offense_rank", "total_defense_rank"):
            if k in tr:
                put(f"#{tr[k]}", fifth(tr[k]))
        for k in ("offense_stats", "defense_allowed_stats"):
            for n in re.findall(r"\(#(\d+)\)", tr.get(k, "")):
                put(f"#{n}", fifth(int(n)))
        for w in x.get("form_by_window", {}).values():
            if isinstance(w, dict):
                put(f"#{w['rank']}", fifth(w["rank"]))
                for c in ("net", "scoring", "allowing", "finishing", "goaltending"):
                    if c in w:
                        put(w[c], form(float(w[c])))
        if x.get("record"):
            put(x["record"], "")  # a season record that matches a last-10 record stays plain
        rec = x.get("last10_record") or ""
        if rec.split("-")[0].isdigit():
            put(rec, "hot" if int(rec.split("-")[0]) >= 7 else "cold" if int(rec.split("-")[0]) <= 3 else "even")
    p = f.get("chance_of_7_plus_goals", "")
    if p.rstrip("%").isdigit():
        put(p, "t-good" if int(p.rstrip("%")) >= 50 else "t-bad" if int(p.rstrip("%")) <= 42 else "t-mid")
    return {k: c for k, c in out.items() if c and k not in clash}


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
    t = {k: {"proj": round(float(v["projected_goals"]) * 20) / 20, "out": v.get("players_out"), "goalie": v.get("goalie_faced"),
             "form": [v.get("record"), v.get("streak"), v.get("last10_record")],
             "ranks": [w["rank"] if isinstance(w, dict) else w for w in v.get("form_by_window", {}).values()]
                      + [v.get("team_rankings", {}).get(r) for r in ("total_offense_rank", "total_defense_rank")]}
         for k, v in f["teams"].items()}
    return json.dumps({"call": f["call"], "teams": t, "line": f.get("line"), "watch": f.get("watch")}, sort_keys=True, default=str)


def models():
    """Names of the Gemini models this key can call (printed by --preview, to pick GEMINI_MODEL)."""
    req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                                 headers={"x-goog-api-key": os.environ.get("GEMINI_API_KEY", "")})
    with urllib.request.urlopen(req, timeout=30) as f:
        return [m["name"].split("/")[-1] for m in json.load(f).get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])]


def ai_run(now, trigger):
    """'3:17 PM' when this run writes new notes (the hourly run in one of the NOTE_HOURS, or its retry), else None: in
    between, the last notes stay up (pre-game, stats-started, 12:01 AM and manual runs never write). now = Eastern time;
    trigger = what started the run (daily.yml's NHL_TRIGGER)."""
    if now.hour in NOTE_HOURS and trigger in NOTE_TRIGGERS:
        return f"{now.hour % 12 or 12}:17 {'PM' if now.hour >= 12 else 'AM'}"
    return None


def run(preview=False):
    import dashboard
    import health
    import paper
    if not os.environ.get("GEMINI_API_KEY"):
        print("(game notes: no GEMINI_API_KEY secret: the dashboard keeps the template)")
        return
    now_et = pd.Timestamp.now(tz="America/New_York")
    slot = now_et.strftime("%-I:%M %p") if preview else ai_run(now_et, os.environ.get("NHL_TRIGGER", ""))
    if slot is None:
        print("(game notes: new ones only at the 12:17, 3:17, 6:17 and 8:17 PM runs; the last ones stay up until then)")
        health.note("• Game notes: the last AI paragraphs stay up (new ones at the 12:17, 3:17, 6:17 and 8:17 PM runs)")
        return
    if preview:
        try:
            print("(models this key can use: " + ", ".join(m for m in models() if "flash" in m or "pro" in m) + ")")
        except Exception as e:
            print(f"(couldn't list the models: {type(e).__name__}: {str(e)[:120]})")
        print(f"(trying, in order: {', '.join(MODELS)})")
    day = date.today().isoformat()  # today's slate only: past days and the Tomorrow preview keep the template
    g = dashboard.current(paper.read_log())
    g = g[g.date == day]
    d = load(day)
    notes, form = d.get("notes", {}), d.get("form", {})
    used = [opening(n["text"]) for n in notes.values() if n.get("text")]
    kinds = Counter(n.get("lead_kind") for n in notes.values() if n.get("lead_kind"))
    calls, made, kept, failed, todo = 0, 0, 0, [], []
    now = pd.Timestamp.now(tz="UTC")
    for r in g.itertuples():
        if not pd.isna(r.final_total) or (isinstance(r.start_utc, str) and pd.Timestamp(r.start_utc) <= now):
            continue  # started: its note stays as written before puck drop (the dashboard shows the template once it's final)
        f = facts(r, dashboard._is(r.flag), form)
        if f is None:
            continue
        key, sig = f"{r.away}@{r.home}", signature(f)
        if notes.get(key, {}).get("sig") == sig:
            kept += 1
        else:
            todo.append((key, f, sig))
    # the slate's most unusual games pick their topic first; a kind already used today counts less
    todo.sort(key=lambda z: -max(c[0] for c in leads(z[1])))
    t0 = time.time()
    for key, f, sig in todo:
        if calls >= MAX_CALLS or time.time() - t0 > (PREVIEW_BUDGET if preview else BUDGET):
            print(f"(game notes: stopping here; {len(todo) - made - len(failed)} left for the next AI run)")
            break
        score, kind, topic = max(leads(f), key=lambda c: c[0] - 0.6 * kinds[c[1]])
        try:
            text, why, model = write_note(f, used, topic)
            calls += 1
        except urllib.error.HTTPError as e:
            print(f"(game notes: Gemini answered {e.code} {getattr(e, 'detail', '')}: stopping for this run)")
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
        notes[key] = {"text": text, "colors": colors(f), "sig": sig, "model": model, "lead_kind": kind, "call": f["call"],
                      "run": slot, "at": pd.Timestamp.now(tz="America/New_York").strftime("%-I:%M %p")}
        used.append(opening(text))
        made += 1
        if preview:
            print(f"\n=== {key} ({f['call']}, opening topic: {topic}) ===\n{text}")
        time.sleep(PAUSE)
    if made:
        d["notes"] = notes
        save(day, d)  # (--preview runs in a checkout that is never committed)
    if preview:  # exactly what the dashboard will show, for a look before it goes live
        dashboard._NOTES.clear()
        for r in g.itertuples():
            print("PREVIEW_HTML " + json.dumps({"key": f"{r.away}@{r.home}", "html": dashboard.game_notes(r, dashboard._is(r.flag))}))
    print(f"(game notes: {made} written, {kept} unchanged, {len(failed)} kept the template, {calls} notes asked for)")
    health.note(f"✓ Game notes (Gemini): {made} written, {kept} unchanged" + (f"; {len(failed)} kept the template ({', '.join(failed)})" if failed else ""))


if __name__ == "__main__":
    run(preview="--preview" in sys.argv)
