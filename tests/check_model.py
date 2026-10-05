"""Component checks for the model, run against scratch copies (real data is never modified).

  python3 tests/check_model.py     # exits 1 if any check fails
"""
import os, re, json, shutil, sys, datetime, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import pandas as pd
import paper, goalies, injuries, model as m, split_model as sm, odds, grade, dashboard
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
paper.settle()
s = paper.read_log()
fs = s[s.flag].iloc[0]
check("Oct 1 re-settles: all 8 finals", s.final_total.notna().sum() == 8)
check("Oct 1 totals match the real scores", list(s.final_total.astype(int)) == list(real[real.date == "2026-10-01"].final_total.astype(int)))
check("flagged FLA@SJS: W +1.02 at consensus, best-book scored too", fs.result == "W" and abs(fs.profit - 1.02) < 1e-9 and not pd.isna(fs.profit_best))
check("unflagged games not scored as bets", s[~s.flag].result.isna().all())
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
goalies.refresh([2026])
check("MoneyPuck outage keeps goalie history", (pd.read_csv(goalies.GOALIE_GAMES).playerId == shes).sum() == n0 - 1)
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
ps = [m.p_from(cal, 7, x) for x in (5.0, 6.0, 7.0)]
check("P(7+) rises with projection", ps[0] < ps[1] < ps[2], ", ".join(f"{p:.0%}" for p in ps))

print("injuries")
inj = injuries.fetch()
check("ESPN injury feed reads", len(inj) > 20, f"{len(inj)} skaters")
tg = injuries.team_games_this_season(g, 2026)
mc = injuries.adjustments([{"team": "EDM", "name": "Connor McDavid", "pos": "C", "status": "Out"}], 2026, tg)["EDM"]
check("McDavid out lowers EDM scoring ~5-8%", 0.92 < mc["off"] < 0.95, f"x{mc['off']:.3f}")
dtd = injuries.adjustments([{"team": "EDM", "name": "Connor McDavid", "pos": "C", "status": "Day-To-Day"}], 2026, tg)["EDM"]
check("day-to-day is not adjusted", dtd["off"] == 1.0 and dtd["dtd"] == ["Connor McDavid"])
gone = injuries.adjustments([{"team": "EDM", "name": "Connor McDavid", "pos": "C", "status": "Out"}], 2026, {"EDM": 82})["EDM"]
check("no double counting for long absences", gone["off"] > mc["off"], f"82 games without him -> x{gone['off']:.3f}")

print("odds")
rows = odds.day_games(datetime.date(2026, 10, 1), 15)
check("closing lines parse", len(rows) == 8, f"{len(rows)} games")
abbrs = {grade.ABBR.get(x, x) for r in rows for x in (r["home"], r["away"])}
check("sportsbook team codes match NHL codes", abbrs <= set(g.home), str(sorted(abbrs - set(g.home))))

print("source retries + alerts (fake sources, nothing real is called)")
import health
health.STATE, health.RETRY_FLAG = SP + "health.json", SP + ".retry"
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
      and st["Flaky"]["consecutive_failures"] == 0 and (os.path.exists(health.RETRY_FLAG) or datetime.datetime.now().hour >= 23))
health._results.clear(); health.attempt("Dead", lambda: 1 / 0, waits=[]); health.attempt("Empty", lambda: 5, waits=[]); health.finish()
made, closed = [], []
health._gh = lambda *a: (made.append(a[a.index("--title") + 1]) if a[:2] == ("issue", "create") else closed.append(a[2]) if a[:2] == ("issue", "close") else None,
                         type("R", (), {"returncode": 0, "stdout": '[{"title": "Data source failing: Empty", "number": 7}]' if a[:2] == ("issue", "list") else ""})())[1]
health.alert()
check("alert after 2 failed runs in a row; closes when the source recovers",
      made == ["Data source failing: Dead"] and closed == ["7"])
health._results.clear()

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
check("every field sent exists in supabase/schema.sql", not unknown and len(cols) == 4, ", ".join(sorted(unknown)))
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
        dict(home_goalie="Ty D'<b>Amour (Confirmed)")]
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

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
