"""Component checks for the model, run against scratch copies (real data is never modified).

  python3 tests/check_model.py     # exits 1 if any check fails
"""
import os, re, json, shutil, sys, datetime, tempfile, glob, contextlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import pandas as pd
import paper, goalies, injuries, players, model as m, split_model as sm, odds, grade, dashboard
os.environ.pop("RUN_SUMMARY", None)  # the model code these checks call must not write into the Tests run's own summary
SP = tempfile.mkdtemp(prefix="nhl-check-") + "/"
results = []
def check(name, ok, detail=""):
    results.append(ok); print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  -- ' + detail) if detail else ''}")

print("paper log")
real = paper.read_log()
check("real log loads, flags are booleans", real.flag.dtype == bool and real.away_b2b.dtype == bool, f"{len(real)} rows")
paper.LOG = SP + "log.csv"
fut, past = "2099-01-01T00:00:00Z", "2000-01-01T00:00:00Z"
base = dict(date="2026-10-03", proj=6.0, proj_away=3, proj_home=3, p7=.5, cutoff=2.95, away_goalie="A (Unconfirmed)",
            home_goalie="B (Unconfirmed)", open_total=5.5, open_over=-120, away_b2b=False, home_b2b=False,
            away_goalie_now="A (Unconfirmed)", home_goalie_now="B (Unconfirmed)", updated_at="11:00",
            **{c: 0.1 for c in paper.BREAKDOWN})
print_r = paper.log_games([dict(base, start_utc=fut, away="AAA", home="BBB", flag=False, bet_total=5.5, bet_over=-120, bet_under=100, best_book="X", best_total=6.0, best_over=-110, logged_at="11:00"),
                           dict(base, start_utc=fut, away="CCC", home="DDD", flag=True, bet_total=6.5, bet_over=105, bet_under=-125, best_book="Y", best_total=6.5, best_over=110, logged_at="11:00"),
                           dict(base, start_utc=past, away="EEE", home="FFF", flag=True, bet_total=6.5, bet_over=100, bet_under=-120, logged_at="11:00")])
check("adds future games, skips started ones", print_r == (2, 0), str(print_r))
r2 = paper.log_games([dict(base, start_utc=fut, away="AAA", home="BBB", flag=True, bet_total=6.5, bet_over=110, bet_under=-130, best_book="Z", best_total=6.0, best_over=-105, logged_at="17:00", away_goalie_now="Q (Confirmed)", away_out="McDavid|0.06|0.01"),
                      dict(base, start_utc=fut, away="CCC", home="DDD", flag=True, bet_total=6.0, bet_over=-110, bet_under=-110, best_book="W", best_total=6.0, best_over=-100, logged_at="17:00")])
d = paper.read_log().set_index("away")
check("late flag upgrades at the 5 PM line", r2 == (0, 1) and d.at["AAA", "bet_total"] == 6.5 and d.at["AAA", "bet_over"] == 110)
check("latest run's numbers saved, first-logged bet kept", d.at["CCC", "bet_total"] == 6.5 and d.at["CCC", "bet_total_now"] == 6.0
      and paper.was_flagged_now(d.at["AAA", "flag_now"]) and d.at["AAA", "proj_now"] == 6.0)
cur = dashboard.current(paper.read_log()).set_index("away")
check("dashboard reads the latest run (line, flag), paper bet kept separately",
      cur.at["CCC", "bet_total"] == 6.0 and cur.at["CCC", "paper_line"] == 6.5 and bool(cur.at["AAA", "flag"]))
check("early flag keeps its 11 AM bet + best book", d.at["CCC", "bet_total"] == 6.5 and d.at["CCC", "best_book"] == "Y")
check("latest starter + injuries refresh", d.at["AAA", "away_goalie_now"] == "Q (Confirmed)" and "McDavid" in str(d.at["AAA", "away_out"]))

print("settling")
oct1 = real[real.date == "2026-10-01"].copy()
for c in ("away_score", "home_score", "final_total", "close_total", "close_over", "close_under", "result", "profit", "clv", "result_best", "profit_best"):
    oct1[c] = None
oct1.to_csv(paper.LOG, index=False)
os.environ["RUN_SUMMARY"] = SP + "settle_summary.txt"
paper.settle()
os.environ.pop("RUN_SUMMARY")
s = paper.read_log()
fs = s[s.flag].iloc[0]
check("Oct 1 re-settles: all 8 finals", s.final_total.notna().sum() == 8)
settle_note = open(SP + "settle_summary.txt", encoding="utf-8").read().strip()
check("settle: the run's summary says what it settled", settle_note == "✓ Settled 8 finished games; bets: FLA@SJS W", settle_note)
check("Oct 1 totals match the real scores", list(s.final_total.astype(int)) == list(real[real.date == "2026-10-01"].final_total.astype(int)))
check("flagged FLA@SJS: W +1.02 at consensus, best-book scored too", fs.result == "W" and abs(fs.profit - 1.02) < 1e-9 and not pd.isna(fs.profit_best))
check("unflagged games not scored as bets", s[~s.flag].result.isna().all())
# offline: a postponed game leaves the log; a score-feed outage skips that day without failing the step
import io
two = oct1.iloc[:2].copy()
two["date"], two["away"], two["home"] = ["2026-10-05", "2026-10-06"], ["PPA", "OUA"], ["PPH", "OUH"]
two.to_csv(paper.LOG, index=False)
real_open, real_day = paper.urllib.request.urlopen, paper.odds.day_games
def fake_open(req, *a, **k):
    if str(getattr(req, "full_url", req)).endswith("2026-10-06"):
        raise OSError("outage")
    return io.BytesIO(json.dumps({"games": [{"awayTeam": {"abbrev": "PPA", "score": 0}, "homeTeam": {"abbrev": "PPH", "score": 0},
                                             "gameState": "FUT", "gameScheduleState": "PPD"}]}).encode())
paper.urllib.request.urlopen, paper.odds.day_games = fake_open, lambda *a, **k: []
try:
    paper.settle(); crash = ""
except Exception as ex:
    crash = f"{type(ex).__name__}: {ex}"
paper.urllib.request.urlopen, paper.odds.day_games = real_open, real_day
s2 = paper.read_log()
check("settle: postponed game removed, outage day kept for the next run", not crash and list(s2.away) == ["OUA"], crash or str(list(s2.away)))
# offline: a settled game the odds feed skipped gets its closing line on a later run (score and result untouched)
miss = oct1.iloc[:1].copy()
miss["date"], miss["away"], miss["home"] = (datetime.date.today() - datetime.timedelta(days=1)).isoformat(), "CLA", "CLH"
miss[["away_score", "home_score", "final_total", "flag", "bet_total", "bet_over", "bet_under", "result", "profit"]] = [3, 4, 7, True, 6.5, -110, -110, "W", 0.909]
miss.to_csv(paper.LOG, index=False)
paper.urllib.request.urlopen = lambda *a, **k: io.BytesIO(json.dumps({"games": []}).encode())
paper.odds.day_games = lambda *a, **k: [{"away": "CLA", "home": "CLH", "total": 6.5, "over": -130, "under": 110}]
try:
    paper.settle(); crash = ""
except Exception as ex:
    crash = f"{type(ex).__name__}: {ex}"
paper.urllib.request.urlopen, paper.odds.day_games = real_open, real_day
s3 = paper.read_log().iloc[0]
check("settle: missed closing line filled later, score + result kept, CLV scored",
      not crash and s3.close_total == 6.5 and s3.close_over == -130 and s3.final_total == 7 and s3.result == "W" and s3.clv == 1, crash or str(s3[["close_total", "clv"]].to_dict()))
_log = paper.LOG  # on a copy: the Supabase checks below sync this log's settled game
shutil.copy(_log, SP + "ppd_log.csv"); paper.LOG = SP + "ppd_log.csv"
paper.remove_games(s3.date, {("XXX", "YYY")})
kept = len(paper.read_log())
paper.remove_games(s3.date, {("CLA", "CLH")})
check("a game postponed after it was logged leaves the log (others stay)", kept == 1 and paper.read_log().empty)
paper.LOG = _log
c0 = {"total": 6.5, "over": -130, "under": 110}
check("line-move: up a full line = toward over", paper.clv(6.0, -110, -110, {"total": 6.5, "over": 100, "under": -120}) == 1)
check("line-move: same line, over got pricier = toward over", paper.clv(6.5, 100, -120, c0) == 1)
check("line-move: down a line = away", paper.clv(6.5, -110, -110, {"total": 6.0, "over": -110, "under": -110}) == -1)

print("goalies")
shutil.copy(goalies.STARTS, SP + "gs.csv"); shutil.copy(goalies.GOALIE_GAMES, SP + "gg.csv")
goalies.STARTS, goalies.GOALIE_GAMES = SP + "gs.csv", SP + "gg.csv"
gg = pd.read_csv(goalies.GOALIE_GAMES); shes = 8478048; n0 = (gg.playerId == shes).sum()
last = gg[gg.playerId == shes].gameId.max()
gg[~((gg.playerId == shes) & (gg.gameId == last))].to_csv(goalies.GOALIE_GAMES, index=False)
real_get = goalies.get
goalies.get = lambda url, *a, **k: (_ for _ in ()).throw(OSError("outage")) if "moneypuck" in url else real_get(url, *a, **k)
goalies.time.sleep = lambda s: None
got = goalies.refresh([2026])
check("MoneyPuck outage keeps goalie history", (pd.read_csv(goalies.GOALIE_GAMES).playerId == shes).sum() == n0 - 1)
check("goalie refresh reports goalies re-downloaded + still missing a game (outage: all still missing)",
      got[0] >= 1 and got[1] == got[0], str(got))
goalies.get = real_get

print("model pieces")
check("season_of: Oct -> same year, Mar -> year before", sm.season_of(datetime.date(2026, 10, 2)) == 2026 and sm.season_of(datetime.date(2027, 3, 1)) == 2026)
check("team names: Montréal / St. Louis match", m.norm_name("Montréal Canadiens") == m.norm_name("Montreal Canadiens") and m.norm_name("St. Louis Blues") == m.norm_name("St Louis Blues"))
check("back-to-back factors", m.b2b_factors(True, False) == (0.92, 1.065) and m.b2b_factors(False, False) == (1, 1))
g = sm.load_split()
check("only 2020+ data in the model", g.season.min() == 2020, f"seasons {g.season.min()}-{g.season.max()}")
p1, proj1 = sm.walk_split(g, known_starters=False, with_projector=True, live_season=2026)
lh, la, det = proj1("VAN", "EDM", None, None, False, False, detail=True)
recon = all(abs((x["ev"] + x["pp"] + x["oth"]) * (1 + x["gadj"]) * (1 + x["b2badj"]) * (1 + x.get("spd", 0)) - v) < 1e-9 for x, v in ((det["home"], lh), (det["away"], la)))
check("breakdown adds up to the projection", recon)
check("projected totals in a sane range", p1.proj.between(4, 8.5).all(), f"{p1.proj.min():.2f}-{p1.proj.max():.2f}")
cal = m.fit_calibration(p1[p1.season.between(2022, 2025)])
ps = [m.p_from(cal, 7, x, 0.3) for x in (5.0, 6.0, 7.0)]
check("P(7+) rises with projection", ps[0] < ps[1] < ps[2], ", ".join(f"{p:.0%}" for p in ps))
_st = pd.read_csv(goalies.STARTS)
check("goalie by name: the Matt Murray who last played for that team", m.goalie_id(_st, "Matt Murray", "SEA") == 8476899
      and m.goalie_id(_st, "Matt Murray", "NSH") == 8483575 and m.goalie_id(_st, "U. Luukkonen", "BUF") == 8480045)

import elimination
_st = lambda t, d, gp, pts, c="": {"teamAbbrev": {"default": t}, "conferenceAbbrev": "E", "divisionAbbrev": d,
                                   "gamesPlayed": gp, "points": pts, "clinchIndicator": c or None}
_rows = ([_st(f"A{i}", "A", 78, 100) for i in range(3)] + [_st(f"M{i}", "M", 78, 100) for i in range(5)]
         + [_st("OUT", "A", 80, 90), _st("CLOSE", "A", 78, 93), _st("FLAG", "M", 78, 80, "e")])
check("eliminated: on points (8 conference + 3 division above its max) or the NHL 'e' flag",
      elimination.out_teams(_rows) == {"OUT", "FLAG"}, str(sorted(elimination.out_teams(_rows))))
check("eliminated factors: out team x0.99, its opponent x1.044", elimination.factors(True, False) == (0.99, 1.044)
      and elimination.factors(False, False) == (1.0, 1.0) and abs(elimination.factors(True, True)[0] - 0.99 * 1.044) < 1e-12)

print("injuries")
inj = injuries.fetch()
check("ESPN injury feed reads", len(inj) > 20, f"{len(inj)} skaters")
tg = injuries.team_games_this_season(g, 2026)
mc = injuries.adjustments([{"team": "EDM", "name": "Connor McDavid", "pos": "C", "status": "Out"}], 2026, tg)["EDM"]
check("McDavid out lowers EDM scoring ~5-12%", 0.88 < mc["off"] < 0.95, f"x{mc['off']:.3f}")  # ~9-10% once his current-season games count (skaters refreshed hourly; x0.897 on Oct 29)
dtd = injuries.adjustments([{"team": "EDM", "name": "Connor McDavid", "pos": "C", "status": "Day-To-Day"}], 2026, tg)["EDM"]
check("day-to-day is not adjusted", dtd["off"] == 1.0 and dtd["dtd"] == ["Connor McDavid"])
gone = injuries.adjustments([{"team": "EDM", "name": "Connor McDavid", "pos": "C", "status": "Out"}], 2026, {"EDM": 82})["EDM"]
check("no double counting for long absences", gone["off"] > mc["off"], f"82 games without him -> x{gone['off']:.3f}")
ts = injuries.adjustments([{"team": "OTT", "name": "Tim Stützle", "pos": "C", "status": "Out"}], 2026, tg)["OTT"]
check("accented names match MoneyPuck's spelling (Stützle out is adjusted)", ts["off"] < 0.97, f"x{ts['off']:.3f}")
pt = players.player_table(2026)  # the name match itself (a depth player's effect can drop under the listing cutoff)
pt["key"], pt["key2"] = pt.name.map(m.norm_name), pt.name.map(m.squash_name)
lo = [injuries.resolve(pt, {"team": t, "name": n}) for t, n in (("NYR", "Joe Veleno"), ("DAL", "Oskar Back"))]
check("nickname / dropped-letter names match on the same team (Joe = Joseph Veleno, Back = Bck)",
      all(r is not None for r in lo) and [r["name"] for r in lo] == ["Joseph Veleno", "Oskar Bck"], str([None if r is None else r["name"] for r in lo]))
tw = injuries.adjustments([{"team": "VAN", "name": "Elias N. Pettersson", "pos": "D", "status": "Out"}], 2026, tg)["VAN"]
tf = injuries.adjustments([{"team": "VAN", "name": "Elias Pettersson", "pos": "C", "status": "Out"}], 2026, tg)["VAN"]
check("two Elias Petterssons (VAN): the listed position picks the right one", tf["off"] < tw["off"], f"C x{tf['off']:.3f}, D x{tw['off']:.3f}")
import lineups
_lu = (lineups.team_slugs, lineups.projected_lineup, lineups.nhl_roster)
lineups.team_slugs = lambda day: {"EDM": "x"}
lineups.projected_lineup = lambda slug: {"dressed": [(m.norm_name("Matthew Savoie"), 93, "Matthew Savoie")]
                                         + [(f"player {i}", i, f"Player {i}") for i in range(17)], "ir": [], "gtd": [], "source": "", "updated": ""}
lineups.nhl_roster = lambda t: [(1, "Matt Savoie", 22), (2, "Player 3", 3), (3, "Zach Hyman", 18)]
lo2 = lineups.outs("2026-10-15", ["EDM"])["EDM"]["missing"]
lineups.team_slugs, lineups.projected_lineup, lineups.nhl_roster = _lu
check("DailyFaceoff nickname (Matthew = NHL Matt Savoie) is not a scratch", [n for _, n, _ in lo2] == ["Zach Hyman"], str(lo2))
bl = {"COL": [{"name": "A", "status": "in", "impact": 0.05}, {"name": "B", "status": "out", "impact": 0.03}]}
lc = injuries.lineup_changes(bl, {"COL": {"off": [{"name": "A", "status": ""}, {"name": "B", "status": "in"}], "def": []}}, {}, "1:00 PM")
check("lineup flag: no lineup posted is not a change, out -> in is", [c["name"] for c in lc.get("COL", [])] == ["B"])

print("odds")
rows = odds.day_games(datetime.date(2026, 10, 1), 15)
check("closing lines parse", len(rows) == 8, f"{len(rows)} games")
abbrs = {grade.ABBR.get(x, x) for r in rows for x in (r["home"], r["away"])}
check("sportsbook team codes match NHL codes", abbrs <= set(g.home), str(sorted(abbrs - set(g.home))))

print("source retries + alerts (fake sources, nothing real is called)")
import health
health.STATE, health.RETRY_FLAG, health.LAST_STATUS = SP + "health.json", SP + ".retry", SP + "last_run_status.json"
calls = {"n": 0}
def flaky():
    calls["n"] += 1
    if calls["n"] < 3:
        raise ConnectionError("site down")
    return {"ok": 1}
check("a failing source is retried until it works", health.attempt("Flaky", flaky, waits=[0.01] * 4) == {"ok": 1} and calls["n"] == 3)
check("a dead source gives the fallback; empty counts as a failure when required",
      health.attempt("Dead", lambda: 1 / 0, "fallback", waits=[0.01]) == "fallback"
      and health.attempt("Empty", lambda: {}, {}, must=True, waits=[]) == {})
bad = health.finish()
st = json.load(open(health.STATE))
check("failures saved across runs + retry run requested", sorted(bad) == ["Dead", "Empty"] and st["Dead"]["consecutive_failures"] == 1
      and st["Flaky"]["consecutive_failures"] == 0 and (os.path.exists(health.RETRY_FLAG) or not health.RETRY_HOURS[0] <= datetime.datetime.now(health.ET).hour < health.RETRY_HOURS[1]))
health._results.clear(); health.attempt("Dead", lambda: 1 / 0, waits=[]); health.attempt("Empty", lambda: 5, waits=[]); health.finish()
made, closed = [], []
health._gh = lambda *a: (made.append(a[a.index("--title") + 1]) if a[:2] == ("issue", "create") else closed.append(a[2]) if a[:2] == ("issue", "close") else None,
                         type("R", (), {"returncode": 0, "stdout": '[{"title": "Data source failing: Empty", "number": 7}]' if a[:2] == ("issue", "list") else ""})())[1]
health.alert()
check("alert after 2 failed runs in a row; closes when the source recovers",
      made == ["Data source failing: Dead"] and closed == ["7"])
health._results.clear()
import urllib.error
n403 = {"n": 0}
def forbidden():
    n403["n"] += 1
    raise urllib.error.HTTPError("https://example.com", 403, "Forbidden", {}, None)
check("a 403 (site refusing us) is tried once, not retried, and still counts as a failure",
      health.attempt("Blocked", forbidden, "fallback", waits=[0.01] * 4) == "fallback" and n403["n"] == 1
      and "403" in (health._results.get("Blocked") or ""), f"{n403['n']} tries")
health._results.clear()
made, closed, open_alert = [], [], []
health._gh = lambda *a: (made.append(a[a.index("--title") + 1]) if a[:2] == ("issue", "create") else closed.append(a[2]) if a[:2] == ("issue", "close") else None,
                         type("R", (), {"returncode": 0, "stdout": json.dumps(open_alert) if a[:2] == ("issue", "list") else ""})())[1]
json.dump({"at": "2026-11-03 15:58 EST", "failed": []}, open(health.LAST_STATUS, "w"))
health.stale("failure", now=datetime.datetime(2026, 11, 3, 16, 30, tzinfo=health.ET))  # 32 min since the last finished run
health.stale("failure", now=datetime.datetime(2026, 11, 3, 18, 33, tzinfo=health.ET))  # 2.6 h (Nov 3 2026 timeouts)
open_alert.append({"title": health.RUN_ALERT, "number": 9})
health.stale("cancelled", now=datetime.datetime(2026, 11, 3, 19, 0, tzinfo=health.ET))  # already open: no duplicate
health.stale("success")
check("no finished run for 2+ h opens one run alert (not after one bad run); a good run closes it",
      made == [health.RUN_ALERT] and closed == ["9"], f"{made} {closed}")

print("goalie + injury confirmations (offline)")
import confirm
C = confirm.combine
check("3 sources agree -> Confirmed, keeps full name + NHL id",
      C([("DailyFaceoff", "U. Luukkonen", "likely", None), ("Rotowire", "Ukko-Pekka Luukkonen", "confirmed", None),
         ("GoaliePost", "Ukko-Pekka Luukkonen", "confirmed", 8480045)])[::3] == ("Ukko-Pekka Luukkonen", 8480045)
      and C([("GoaliePost", "Igor Shesterkin", "confirmed", 1)])[1] == "Confirmed")
check("sources confirm different goalies -> Conflict, majority wins",
      C([("DailyFaceoff", "Igor Shesterkin", "confirmed"), ("Rotowire", "Jonathan Quick", "confirmed"),
         ("GoaliePost", "Igor Shesterkin", "confirmed")])[:2] == ("Igor Shesterkin", "Conflict"))
check("a confirmation beats a 'likely' for someone else; no sources -> Projected",
      C([("DailyFaceoff", "Igor Shesterkin", "likely"), ("GoaliePost", "Jonathan Quick", "confirmed")])[:2] == ("Jonathan Quick", "Confirmed")
      and C([])[:2] == (None, "Projected") and not confirm.same("Eric Comrie", "Mike Comrie"))
inj = confirm.add_rotowire_injuries([{"team": "CHI", "name": "Bowen Byram", "pos": "D", "status": "Day-To-Day", "ret": None, "note": ""}],
                                    {"CHI": [("Bowen Byram", "D", "OUT"), ("Connor Bedard", "C", "IR-NR"), ("Spencer Knight", "G", "OUT")]})
check("Rotowire injuries merged: day-to-day -> out, new IR added, goalies skipped",
      [(r["name"], r["status"]) for r in inj] == [("Bowen Byram", "Out"), ("Connor Bedard", "Out")])
gc = dashboard.goalie_compact
check("goalie badges: conflict, sources in hover, actual starter on results",
      "gb conflict" in gc("A B (Conflict)", "A B (Conflict)", "DailyFaceoff: ✓ (confirmed)")
      and "Sources: Rotowire" in gc("A B (Confirmed)", "A B (Confirmed)", "Rotowire: ✓ (confirmed)")
      and "gb chg" in gc("Igor Shesterkin (Confirmed)", "Igor Shesterkin (Confirmed)", None, "D. Garand")
      and "gb ok" in gc("Dylan Garand (Likely)", "Dylan Garand (Likely)", None, "D. Garand")
      and "gb chg" in gc("Pyotr Kochetkov (Confirmed)", "Brandon Bussi (Confirmed)", None, "B. Bussi"))  # projection used Kochetkov
_bands = {"trash": (81, 100), "bad": (61, 80), "mid": (41, 60), "good": (21, 40), "great": (1, 20)}
check("goalie grade 1-100 sits inside its tag's band (Strong 81-100 ... Trash 1-20)",
      all(_bands[dashboard.tier("gadj", v)][0] <= dashboard.goalie_grade(v) <= _bands[dashboard.tier("gadj", v)][1]
          for v in [i / 1000 for i in range(-150, 100)]) and "Strong 100" in gc("A B (Confirmed)", None, None, None, -0.2, "X"))

print("supabase run history (fake database, nothing is sent)")
import store
schema = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "supabase", "schema.sql")).read()
cols = {t: set(re.findall(r"(?:^|,)\s*([a-z_0-9]+)\s+(?:uuid|timestamptz|date|text|int|bigint|real|boolean|jsonb)\b",
                          body.replace("\n", ","), re.M))
        for t, body in re.findall(r"create table if not exists (\w+) \((.*?)\n\);", schema, re.S)}
sent = []
store.URL, store.KEY = "https://fake.supabase.co", "fake"
store._send = lambda table, rows, on_conflict=None, tries=3: sent.extend((table, store.clean(r)) for r in rows)
fut2 = "2099-01-01T23:00:00Z"
run_rows = [dict(base, start_utc=fut2, game_id=1, away="AAA", home="BBB", flag=True, bet_total=6.5, bet_over=-110, bet_under=-110,
                 best_book="X", best_total=6.5, best_over=-105, best_under=-115, open_total=6.5, open_over=-110, logged_at="11:00",
                 away_out=None, home_out=None, away_dtd=None, home_dtd=None),
            dict(base, start_utc=past, game_id=2, away="CCC", home="DDD", flag=False, bet_total=6.0, bet_over=-110, bet_under=-110)]
rid = store.record_run("2026-10-03", run_rows, sources={"dailyfaceoff": True})
store.sync_log(paper.read_log())
by = {}
for t, r in sent:
    by.setdefault(t, []).append(r)
check("run saved: 1 run, only not-started games projected", len(by.get("nhl_runs", [])) == 1 and
      [p["away"] for p in by.get("nhl_projections", [])] == ["AAA"] and by["nhl_projections"][0]["run_id"] == rid)
unknown = {f"{t}.{k}" for t, rows in by.items() for r in rows for k in r if k not in cols.get(t, set())}
check("every field sent exists in supabase/schema.sql", not unknown and len(cols) == 8, ", ".join(sorted(unknown)))
check("call saved with each projection, no NaN sent", by["nhl_projections"][0]["call"] in ("SLAM", "1U", "PASS", "AVOID")
      and "NaN" not in json.dumps([r for _, r in sent]))
store._send = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("supabase down"))
check("supabase failure never stops a run", store.record_run("2026-10-03", run_rows) is None)
store.URL = ""
check("skipped when not configured", store.record_run("2026-10-03", run_rows) is None)

print("monthly check-up (sections that don't need the full model run)")
import retune
g_season = retune.season_rows(2026)
cl, _ = retune.calls_section(g_season); gl, _ = retune.goalie_section(g_season); cal, _ = retune.calibration_section(g_season)
check("monthly report sections build from the real log", any("| SLAM |" in x for x in cl) and any("actually started" in x for x in gl)
      and any("finished games" in x or "No finished" in x for x in cal))

print("projection moves")
import moves
_mv_day, _mv_path = "2000-01-01", moves.path("2000-01-01")
_row = lambda proj, pa, ph, ag, hg, a_out, a_gadj, a_inj: {"away": "PIT", "home": "COL", "proj": proj, "proj_away": pa, "proj_home": ph,
    "away_goalie_now": f"{ag} (Confirmed)", "home_goalie_now": f"{hg} (Confirmed)", "away_out": a_out, "home_out": None,
    "away_gadj": a_gadj, "home_gadj": 0.01, "away_inj": a_inj, "home_inj": 0.0, "bet_total": 6.5, "bet_over": -110}
try:
    moves.record(_mv_day, [_row(7.00, 3.00, 4.00, "A", "B", None, 0.0, 0.0)], at="1:00 PM")
    moves.record(_mv_day, [_row(7.00, 3.00, 4.00, "A", "B", None, 0.0, 0.0)], at="2:00 PM")  # nothing changed: still logged
    moves.record(_mv_day, [_row(6.90, 2.90, 4.00, "A", "B", "X Player|0.03|0.0", 0.0, -0.033)], at="3:00 PM")
    moves.record(_mv_day, [_row(7.10, 2.90, 4.20, "A", "C", "X Player (scratch)|0.03|0.0", 0.0, -0.033)], at="4:00 PM")  # tag change only
    moves.record(_mv_day, [{**_row(7.10, 2.90, 4.20, "A", "C", "X Player|0.03|0.0", 0.0, -0.033), "home_goalie_now": "C (Likely)",
                            "away_dtd": "Y Player", "home_lineup": "DailyFaceoff 5:10 PM", "bet_over": -120}], at="5:00 PM")
    h_ = moves.load(_mv_day)["PIT@COL"]
    check("moves: every run logged; changed = projection / goalie / out moved (tags / order ignored)",
          [x["at"] for x in h_] == ["1:00 PM", "2:00 PM", "3:00 PM", "4:00 PM", "5:00 PM"]
          and [moves.moved(a_, b_) for a_, b_ in zip(h_, h_[1:])] == [False, True, True, False]
          and moves.news(h_[0], h_[1], "PIT", "COL") == [])
    nw = moves.news(h_[3], h_[4], "PIT", "COL")
    check("moves: scraper news (goalie status, day-to-day, lineup, line)", nw == [
        "Y Player (PIT) day-to-day", "COL goalie C: Confirmed → Likely", "COL lineup: DailyFaceoff 5:10 PM", "Line 6.5 o-110 → 6.5 o-120"], str(nw))
    h_ = [h_[0], h_[2], h_[3]]
    ex = moves.explain(h_[1], h_[2], "PIT", "COL") + moves.explain(h_[0], h_[1], "PIT", "COL")
    check("moves: causes add up to the move; injury and goalie named", abs(sum(g for _, g in ex) - 0.10) < 0.006
          and any("X Player (PIT) out" in t for t, _ in ex), str([(t, round(g, 3)) for t, g in ex]))
finally:
    if os.path.exists(_mv_path):
        os.remove(_mv_path)

print("dashboard")
dashboard.OUT = SP + "site/index.html"
import paths; paper.LOG = paths.data("paper_trades.csv")
dashboard.build()
html = open(dashboard.OUT).read()
days = os.listdir(SP + "site/days")
visible = re.sub(r"<style>.*?</style>|<[^>]+>", " ", html, flags=re.S)
check("index + a page per logged day", len(days) == real.date.nunique(), f"{len(days)} day pages")
check("no 'nan' / 'None' shown on the page", not re.search(r"\bnan\b|\bNone\b", visible))
check("header: title + last model run time", re.search(r"<header class=\"hero\"><h1>NHL Total Model</h1>(<div class='lastrun'>.*?</div>)?</header>", html) is not None
      and (dashboard.last_run() == "" or dashboard.last_run() in html))
# reasoning text: every logged game plus awkward future cases (no line, missing goalie/rating/scores, push, both tired)
nan = float("nan")
row0 = real[real.away_ev.notna()].iloc[0].to_dict()
edge = [{}, dict(bet_total=nan, open_total=nan, flag=False), dict(away_goalie=nan, home_goalie_now=nan, away_gadj=nan),
        dict(away_spd=nan, home_inj=nan), dict(bet_total=6.0, final_total=6.0, away_score=nan, home_score=nan),
        dict(away_b2badj=-0.02, home_b2badj=-0.02), dict(cutoff=nan), dict(away_ev=nan),
        dict(home_goalie="Ty D'<b>Amour (Confirmed)"), dict(away_elim=-0.01, home_elim=0.044),
        dict(away_elim=0.99 * 1.044 - 1, home_elim=0.99 * 1.044 - 1)]
rows = list(real.itertuples()) + [next(pd.DataFrame([{**row0, **x}]).itertuples()) for x in edge]
texts, crash = [], ""
for r in rows:
    try:
        texts.append(re.sub(r"<[^>]+>", "", dashboard.reasoning(r, dashboard._is(r.flag))))
    except Exception as ex:
        crash = f"{r.away}@{r.home}: {type(ex).__name__}: {ex}"
check("reasoning builds for every game and edge case", not crash, crash or f"{len(rows)} games")
check("reasoning never shows nan / None / raw HTML", not any(re.search(r"\bnan\b|\bNone\b|<b>Amour", t) for t in texts))
check("reasoning matches the call", all(t.split(":")[0].replace("🔨 ", "") == dashboard.call(r, dashboard._is(r.flag))
                                        for t, r in zip(texts, rows)))

print("once-a-day stats (offline: the saved MoneyPuck copy + committed files)")
m.STATS_STATUS = SP + "stats_status.json"
now = datetime.datetime.now().astimezone()
def stats_err(at, failed=()):
    json.dump({"at": at.isoformat(timespec="minutes"), "failed": list(failed)}, open(m.STATS_STATUS, "w"))
    try:
        return m.stats_ok() and None
    except Exception as e:
        return str(e)
check("daily stats: a run 5 h ago is fine; a failed run or none for 30+ h is a failure (hourly runs alert)",
      stats_err(now - datetime.timedelta(hours=5)) is None and "failed: MoneyPuck stats" in (stats_err(now, ["MoneyPuck stats"]) or "")
      and "no stats run since" in (stats_err(now - datetime.timedelta(hours=31)) or ""))
season_now = sm.season_of(datetime.date.today())
d_teams, d_goalies, d_skaters, d_meta = m.daily_results(g, season_now)
import store
check("daily results: every team, the recent goalies and the skaters who matter, in Supabase-ready JSON",
      len(d_teams) >= 32 and len(d_goalies) >= 60 and len(d_skaters) >= 300 and d_meta["season"] == season_now
      and json.dumps([store.clean(r) for r in d_teams + d_goalies + d_skaters + [d_meta]], allow_nan=False) is not None,
      f"{len(d_teams)} teams, {len(d_goalies)} goalies, {len(d_skaters)} skaters")
top = max(d_skaters, key=lambda r: -r["gf_if_out"])
check("daily results: the top skater's 'goals if out' is a 5-12% cost (McDavid test range) and goalie skills stay within +-15%",
      -0.12 <= top["gf_if_out"] <= -0.05 and all(abs(r["skill"]) <= 0.15 for r in d_goalies), f"{top['name']} {top['gf_if_out']:+.3f}")
sent.clear()
store.URL, store.KEY = "https://fake.supabase.co", "fake"  # the fake database again (earlier checks switch it off / break it)
store._send = lambda table, rows, on_conflict=None, tries=3: sent.extend((table, store.clean(r)) for r in rows)
store._go = lambda req, table, tries: None  # the replace step's DELETE: nothing is sent
store.save_daily(d_teams, d_goalies, d_skaters, d_meta)
unknown_d = {f"{t}.{k}" for t, r in sent for k in r if k not in cols.get(t, set())}
check("daily results: every field sent exists in supabase/schema.sql (all 4 nhl_daily_* tables written)",
      not unknown_d and {t for t, _ in sent} == {"nhl_daily_teams", "nhl_daily_goalies", "nhl_daily_skaters", "nhl_daily_meta"},
      ", ".join(sorted(unknown_d)))

st_path = SP + "stats_status_dash.json"
def mp_html(**kw):
    json.dump({"latest_game": "2026-11-02", "failed": [], **kw}, open(st_path, "w"))
    return dashboard.stats_status(st_path)
iso = lambda h: (datetime.datetime.now().astimezone() - datetime.timedelta(hours=h)).isoformat(timespec="minutes")
ok_html = mp_html(at=iso(1))
check("header 'MoneyPuck data': ✓ + games through when current; ⚠ + reason when the run failed or is 30+ h old",
      "runok" in ok_html and "games through Mon, Nov 2" in ok_html
      and "Not working: MoneyPuck stats" in mp_html(at=iso(1), failed=["MoneyPuck stats"])
      and "no update for 31 hours" in mp_html(at=iso(31.5)), ok_html[:80])
posted_html = mp_html(at="2026-11-04T09:16-05:00", posted="2026-11-04T07:29-05:00")
check("header 'MoneyPuck data' shows when MoneyPuck posted the data; the run's own time is 'checked'",
      "Wed, Nov 4 · 7:29 AM EST" in posted_html and "checked 9:16 AM" in posted_html, posted_html[:160])

print("morning MoneyPuck wait (simulated clock: nothing really waits)")
from zoneinfo import ZoneInfo
ET_ = ZoneInfo("America/New_York")
clock, seen = {}, []
def mp_sleep(sec):
    clock["t"] += datetime.timedelta(seconds=sec)
def mp_run(posts_at, want=datetime.date(2026, 11, 3)):
    clock["t"], seen[:] = datetime.datetime(2026, 11, 4, 8, 0, tzinfo=ET_), []
    def mp_check():
        seen.append(clock["t"].strftime("%H:%M"))
        return want if posts_at and clock["t"] >= posts_at else datetime.date(2026, 11, 2)
    return m.wait_for_moneypuck(want, datetime.datetime(2026, 11, 4, 11, 10, tzinfo=ET_), mp_check, lambda: clock["t"], mp_sleep)
got = mp_run(datetime.datetime(2026, 11, 4, 8, 25, tzinfo=ET_))
check("morning run: checks every 10 min until MoneyPuck has last night's games (posted 8:25 -> got them at 8:30)",
      got == datetime.date(2026, 11, 3) and seen == ["08:00", "08:10", "08:20", "08:30"], str(seen))
got = mp_run(None)
check("morning run: MoneyPuck never posts -> last check at 11:10, then keeps the old data (20 checks)",
      got == datetime.date(2026, 11, 2) and seen[-1] == "11:10" and len(seen) == 20, f"{len(seen)} checks, last {seen[-1]}")
got = mp_run(None, want=None)
check("morning run: no games last night -> one check, no waiting", seen == ["08:00"])
check("MoneyPuck's Last-Modified shown in Eastern time (the download's log line)",
      m.posted("Wed, 04 Nov 2026 12:29:03 GMT") == "Wed, Nov 4 7:29 AM EST" and m.posted(None) == "at an unknown time",
      m.posted("Wed, 04 Nov 2026 12:29:03 GMT"))

print("run summaries (the last step of every workflow)")
import importlib.util
notes = SP + "run_summary.txt"
os.environ["RUN_SUMMARY"] = notes
health.note("✓ one")
health.note("✗ two")
os.environ.pop("RUN_SUMMARY")
health.note("not written")
check("notes go to $RUN_SUMMARY, only when the workflow sets it; counts read '1 goalie' / '31 goalies'",
      open(notes, encoding="utf-8").read() == "✓ one\n✗ two\n" and health.plural(1, "goalie") == "1 goalie" and health.plural(31, "goalie") == "31 goalies")
_spec = importlib.util.spec_from_file_location("summary", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".github", "scripts", "summary.py"))
summary = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(summary)
env = {"RUN_SUMMARY": notes, "JOB_STATUS": "success", "STARTED_BY": "hourly",
       "STEPS": json.dumps({"rebuild-dashboard": {"outcome": "success", "conclusion": "success"}})}
text, md = summary.summary("Model run", env)
ok = ("Job:        Model run" in text and "the keeper (hourly slot)" in text and "  ✓ one" in text and "  ✗ two" in text
      and "FINISHED, WITH PROBLEMS" in text and "- ✗ two" in md and "FINISHED, WITH PROBLEMS" in md)
check("summary: the job, what started it, every line, and the result (a ✗ line -> finished, with problems)",
      ok, "" if ok else text)  # the sample summary only when the check fails: it must never look like this run's own result
env.update(JOB_STATUS="failure", STARTED_BY="manual", GITHUB_TRIGGERING_ACTOR="Prezbo8", STEPS=json.dumps({
    "rebuild-dashboard": {"outcome": "failure", "conclusion": "failure"},
    "save-moneypuck-copy": {"outcome": "failure", "conclusion": "success"}, "settle-bets": {"outcome": "skipped", "conclusion": "skipped"}}))
text, md = summary.summary("Model run", env)
ok = "✗ FAILED" in text and "Failed step: rebuild dashboard, save moneypuck copy (ignored)" in text and "a manual run (Prezbo8)" in text
check("summary: a failed run names its failed steps (continue-on-error ones 'ignored'); a manual run says who",
      ok, "" if ok else text)

print("paper record + network calls")
cb = dashboard.closing_bets(real)
check("record tiles cover every flagged pick (SLAM + 1U + PASS + AVOID = the record)",
      {dashboard.call(r, True) for r in cb.itertuples()} <= set(dashboard.RECORD_CALLS), str(dashboard.RECORD_CALLS))
shutil.copy(paths.data("paper_trades.csv"), SP + "real_log.csv")
paper.LOG, os.environ["RUN_SUMMARY"] = SP + "real_log.csv", SP + "report_summary.txt"
with contextlib.redirect_stdout(io.StringIO()):
    paper.report()
os.environ.pop("RUN_SUMMARY")
rep = open(SP + "report_summary.txt", encoding="utf-8").read()
want = f"{(cb.res == 'W').sum()}-{(cb.res == 'L').sum()}-{(cb.res == 'P').sum()}"
check("the daily Report's paper record is the dashboard's (closing line), not the first-logged bets",
      f"Paper record (closing line, as on the dashboard): {want} " in rep and f"{cb.units.sum():+.2f}u" in rep, rep.strip())
def no_timeout(path):
    """'file:line' of every urlopen( call whose arguments have no timeout= (it would wait forever on a stuck server)."""
    s_, out, i = open(path, encoding="utf-8").read(), [], 0
    while (i := s_.find("urlopen(", i)) >= 0:
        j, depth = i + len("urlopen("), 1
        while depth and j < len(s_):
            depth += {"(": 1, ")": -1}.get(s_[j], 0)
            j += 1
        if "timeout" not in s_[i:j]:
            out.append(f"{os.path.basename(path)}:{s_.count(chr(10), 0, i) + 1}")
        i = j
    return out
_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
hung = [x for f in sorted(glob.glob(_root + "/src/*.py") + glob.glob(_root + "/.github/scripts/*.py")) for x in no_timeout(f)]
check("every network call has a timeout (one without can hang a run until GitHub stops it at 45 min)", not hung, ", ".join(hung))

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
