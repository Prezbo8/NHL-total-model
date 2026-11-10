"""Game notes: a short paragraph for each of today's games, written by a template that follows the structure of the
AI (Gemini) notes used Nov 5-9 2026 (user's choice, Nov 9 2026: instant, every number exact, current at every run, no
free-tier limits). Today's slate only: the Tomorrow preview tab, finished games and past days keep the breakdown
template (dashboard.game_notes).

The paragraph is built from the model's own numbers (facts()): it opens on the game's most unusual fact (leads(): a
streak, a hot or cold last 10, the goalie, a Form move, the biggest factor, injuries or a line move), then the call with
the projected total, the line, the chance of 7+ and why, then for each team its record, last 10, total offense /
defense ranks, 5-on-5 and power-play rating and projected goals with the attack's rank vs the opposing defense's, and
the goalie it shoots at. Wording rotates between a few phrasings per game so the slate doesn't read the same. Numbers
are colored like the rest of the dashboard (colors(), colorize()). Built when the dashboard is built: nothing is saved
except each team's form (form_snapshot, data/notes/<day>.json, frozen at puck drop).
"""
import html
import json
import os
import re

import pandas as pd

import paths

CALLS = ("SLAM", "1U", "PASS", "AVOID")
WINDOWS = (("season", "season"), ("30", "last_30_days"), ("14", "last_14_days"), ("7", "last_7_days"))


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
         "how_calls_like_this_did_2021_26": dashboard.CALL_HISTORY[call], "teams": teams}
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


# ---- the template (the AI notes' structure: hook, call, then each team) ----

def _pick(options, key):
    """One phrasing per game, the same every build (so a note doesn't change wording between runs)."""
    return options[sum(map(ord, key)) % len(options)]


TWO_WORD = ("Blue Jackets", "Red Wings", "Maple Leafs", "Golden Knights")  # nicknames of two words


def _name(t):
    """The city: 'Buffalo Sabres' -> 'Buffalo', 'Toronto Maple Leafs' -> 'Toronto', 'New York Rangers' -> 'New York'."""
    from teams import TEAMS
    full = TEAMS.get(t, t)
    cut = 2 if full.endswith(TWO_WORD) else 1
    return " ".join(full.split()[:-cut]) or t


def hook(f):
    """The opening sentence: the game's most unusual fact (leads()), or None when nothing stands out."""
    score, kind, topic = max(leads(f))
    if kind == "call":
        return None
    found = {t: topic.find(t) for t in f["teams"] if t in topic}
    lead_team = min(found, key=found.get) if found else None  # the team the topic is about (named first)
    for t, x in f["teams"].items():
        if t != lead_team:
            continue
        n, opp = _name(t), next(k for k in f["teams"] if k != t)
        s = x.get("streak") or ""
        if kind == "streak" and s[:1] in ("W", "L") and s[1:].isdigit() and int(s[1:]) >= 3:
            won = s[0] == "W"
            return _pick([f"{n} has {'won' if won else 'lost'} {s[1:]} straight.",
                          f"{n} comes in on a {s[1:]}-game {'winning' if won else 'losing'} streak."], f["game"])
        w = (x.get("last10_record") or "").split("-")[0]
        if kind == "last10" and w.isdigit() and (int(w) >= 7 or int(w) <= 3):
            return f"{n} is {x['last10_record']} over its last 10 games."
        g = x.get("goalie_faced_numbers", {}).get("means")
        if kind == "goalie" and g and not g.startswith("about"):
            return f"{x['goalie_faced'].split(' (')[0]} is in {_name(opp)}'s net, and {g.split(':')[0]}."
        fw = x.get("form_by_window", {})
        late = next(((k, fw[k]) for k in ("last_7_days", "last_14_days", "last_30_days") if isinstance(fw.get(k), dict)), None)
        if kind == "form" and isinstance(fw.get("season"), dict) and late and abs(fw["season"]["rank"] - late[1]["rank"]) >= 10:
            up = late[1]["rank"] < fw["season"]["rank"]
            return (f"{n} has {'climbed' if up else 'slipped'} in the Form view, from #{fw['season']['rank']} over the season "
                    f"to #{late[1]['rank']} over the {late[0].replace('_', ' ')}.")
        for z in x["pushing_up"][:1] + x["holding_back"][:1]:
            m = re.search(r"^(.*) ([+-]\d+\.\d\d) ", z)
            if kind == "factor" and m and abs(float(m.group(2))) >= 0.2 and abs(score - 0.9 - abs(float(m.group(2)))) < 1e-9:
                return f"The biggest single factor here is {m.group(1)} for {n}, worth {m.group(2)} goals."
        if kind == "injuries" and x["players_out"]:
            return f"{n} is without {', '.join(x['players_out'])}."
    if kind == "line" and f.get("line_moved"):
        return f"The line has moved {f['line_moved']}."
    return None


def _team(t, x, opp):
    """Record, ranks, 5-on-5, power play and the goalie it shoots at: one or two sentences per team."""
    n, out = _name(t), []
    rec = ", ".join(v for v in (x.get("record"), f"{x['last10_record']} in its last 10" if x.get("last10_record") else None) if v)
    tr = x.get("team_rankings", {})
    ranks = (f" ranks #{tr['total_offense_rank']} in total offense and #{tr['total_defense_rank']} in total defense"
             if "total_offense_rank" in tr else "")
    head = f"{n} ({rec})" if rec else n
    out.append(f"{head}{ranks}." if ranks else f"{head}:")  # its projected goals are in the call sentence
    parts = []
    for key, label, against, unit in (("five_on_five", "5-on-5", "opponent_defense", "defense"),
                                      ("power_play", "power play", "opponent_penalty_kill", "penalty kill")):
        z = x.get(key)
        if not z:
            continue
        m = f" (its #{z['attack']['rank']} attack vs {opp}'s #{z[against]['rank']} {unit})" if "attack" in z else ""
        parts.append(f"its {label} is {z['rating']} at {z['projected_goals']}{m}")
    if parts:
        out.append(parts[0][0].upper() + parts[0][1:] + (", and " + parts[1] if len(parts) > 1 else "") + ".")
    gname, _, gdesc = x.get("goalie_faced", "").partition("): ")
    if gname:
        gname = gname.split(" (")[0]
        g = f"It shoots at {gname}" + (f", {gdesc}" if gdesc else "")
        l5 = x.get("goalie_faced_numbers", {}).get("last_5_games")
        if l5:
            g += f"; over his last 5 games he allowed {l5.split(', ', 1)[1].split(':')[0].replace(' goals allowed on', ' goals on')}"
        out.append(g + ".")
    return " ".join(out)


def write(f):
    """The note for one game (facts() -> plain text)."""
    (a, xa), (h, xh) = f["teams"].items()
    why = re.sub(r"^(?:🔨\s*)?\w+:\s*", "", f["why_this_call"]).strip()  # drop the call label ('PASS:', '🔨 SLAM:')
    why = why[0].upper() + why[1:] if why else ""
    line = f" on the {f['line']} line" if f.get("line") else " (no line yet)"
    call = _pick([f"The call is {f['call']}{line}: the model projects {f['projected_total']} goals ({a} {xa['projected_goals']}, "
                  f"{h} {xh['projected_goals']}) with a {f['chance_of_7_plus_goals']} chance of 7 or more.",
                  f"The model has this one as {f['call']}{line}, projecting {f['projected_total']} goals ({a} {xa['projected_goals']}, "
                  f"{h} {xh['projected_goals']}) and a {f['chance_of_7_plus_goals']} chance of 7 or more."], f["game"])
    parts = [hook(f), call, why if why.endswith(".") else why + "." if why else None, _team(a, xa, h), _team(h, xh, a)]
    if f.get("watch"):
        parts.append(f"Watch: {f['watch']}.")
    return " ".join(p for p in parts if p)
