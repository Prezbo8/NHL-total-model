"""NHL over/under 6 goals model.

Rates each team's offense (goals created) and defense (goals allowed) from
MoneyPuck game data, blending real goals with expected goals (xG), then
projects a game total and the chance it goes OVER 6 (7+ goals; 6 = push).
Each team's starting goalie (DailyFaceoff) adjusts the goals they'll allow,
based on goals saved above expected (MoneyPuck).

  python3 src/model.py backtest        # test on past seasons
  python3 src/model.py today [DATE]    # 5v5/PP split model projections + OVER flags (default today)
"""
import json
import re
import sys
import urllib.request
from datetime import date, timedelta

import numpy as np
import pandas as pd

import goalies
import players
import paths

DATA = paths.data("moneypuck_games.csv")
DATA_URL = "https://moneypuck.com/moneypuck/playerData/careers/gameByGame/all_teams.csv"

K = 15          # games of "last season" weight before this season's games take over
W_GOALS = 0.5   # offense/defense metric = W_GOALS*goals + (1-W_GOALS)*xG
REGRESS = 0.33  # pull last season's rating this far back to league average
G_SHRINK = 200  # xG faced before a goalie's own record counts as much as "average goalie" (calibrated: ratings match actual play)
G_DECAY = 0.7   # how much of a goalie's past seasons carries into the next one
# back-to-backs (team played yesterday), measured on 2022-24 seasons vs projections
B2B_TIRED = 0.92     # tired team scores ~8% fewer goals than projected
B2B_VS_TIRED = 1.065  # its opponent scores ~6.5% more
# team skating speed (previous season's 20+ mph bursts per game, z-score), fitted on 2022-26 (5,248 games)
SPEED_OWN = 0.020    # +2.0% own scoring per SD of own speed (±0.6%)
SPEED_OPP = -0.017   # -1.7% to the opponent's scoring per SD (±0.6%); net on a total +0.4% per SD


def load_goalies():
    """(starter per (gameId, team), goalie game rows by gameId, goalie rows before 2021)"""
    st = pd.read_csv(goalies.STARTS)
    st = st[st.started == 1]
    starter = {(g, t): p for g, t, p in zip(st.gameId, st.team, st.playerId)}
    gg = pd.read_csv(goalies.GOALIE_GAMES).drop_duplicates(["playerId", "gameId"])
    gg = gg[gg.gameId.astype(str).str[4:6] == "02"]
    by_game = {g: list(zip(d.playerId, d.xGoals, d.goals)) for g, d in gg.groupby("gameId")}
    return starter, by_game, gg


class GoalieSkill:
    """Goals saved above expected per xG faced, shrunk toward 0 (average)."""
    def __init__(self, history, shrink=G_SHRINK, decay=G_DECAY):
        self.shrink, self.decay, self.c = shrink, decay, {}
        for season, d in history.sort_values("season").groupby("season"):
            self.new_season()
            for p, xg, g in zip(d.playerId, d.xGoals, d.goals):
                self.add(p, xg, g)

    def new_season(self):
        self.c = {p: (xg * self.decay, gsax * self.decay) for p, (xg, gsax) in self.c.items()}

    def add(self, p, xg, g):
        xg0, s0 = self.c.get(p, (0.0, 0.0))
        self.c[p] = (xg0 + xg, s0 + xg - g)

    def skill(self, p):
        xg, gsax = self.c.get(p, (0.0, 0.0))
        return gsax / (xg + self.shrink)


MP_ABBR = {"L.A": "LAK", "N.J": "NJD", "S.J": "SJS", "T.B": "TBL"}


def fetch(url):
    return urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})


def refresh_data(tries=3):
    """Download MoneyPuck's game file to a temp file and swap it in only if it looks complete,
    so a dropped connection can never wipe the existing data."""
    import os
    import time
    tmp = DATA + ".part"
    for i in range(tries):
        try:
            with urllib.request.urlopen(fetch(DATA_URL), timeout=300) as f, open(tmp, "wb") as out:
                while chunk := f.read(1 << 20):
                    out.write(chunk)
            with open(tmp) as f:
                ok = f.readline().startswith("team,season") and os.path.getsize(tmp) > 50_000_000
            if ok:
                os.replace(tmp, DATA)
                return True
            print(f"(MoneyPuck download looked incomplete, attempt {i + 1}/{tries})")
        except Exception as e:
            print(f"(MoneyPuck download failed, attempt {i + 1}/{tries}: {e})")
        time.sleep(30 * (i + 1))
    if os.path.exists(tmp):
        os.remove(tmp)
    print("(using the previously downloaded MoneyPuck data)")
    return False


def load_games(refresh=False, xg="xGoals"):
    if refresh:
        refresh_data()
    d = pd.read_csv(DATA, usecols=["season", "gameId", "playerTeam", "opposingTeam", "home_or_away",
                                   "gameDate", "situation", "goalsFor", "goalsAgainst",
                                   f"{xg}For", f"{xg}Against", "playoffGame"])
    d = d[(d.situation == "all") & (d.playoffGame == 0) & (d.home_or_away == "HOME")]
    # older MoneyPuck seasons use "L.A" etc.; match the NHL API's abbreviations
    d = d.replace({"playerTeam": MP_ABBR, "opposingTeam": MP_ABBR})
    g = d.rename(columns={"playerTeam": "home", "opposingTeam": "away", "goalsFor": "hg",
                          "goalsAgainst": "ag", f"{xg}For": "hxg", f"{xg}Against": "axg"})
    g = g.drop_duplicates("gameId").sort_values(["gameDate", "gameId"]).reset_index(drop=True)
    # MoneyPuck excludes shootouts; a tie after OT means the shootout winner got +1 on the scoreboard
    g["total"] = g.hg + g.ag + (g.hg == g.ag).astype(int)
    # back-to-back: team also played the day before
    d = pd.to_datetime(g.gameDate.astype(str))
    last = {}
    g["h_b2b"], g["a_b2b"] = False, False
    for i, day, h, a in zip(g.index, d, g.home, g.away):
        g.at[i, "h_b2b"] = (day - last.get(h, day)).days == 1
        g.at[i, "a_b2b"] = (day - last.get(a, day)).days == 1
        last[h] = last[a] = day
    return g[["season", "gameId", "gameDate", "home", "away", "hg", "ag", "hxg", "axg", "total", "h_b2b", "a_b2b"]]


def b2b_factors(h_b2b, a_b2b):
    """Multipliers for (home goals, away goals)."""
    fh = (B2B_TIRED if h_b2b else 1) * (B2B_VS_TIRED if a_b2b else 1)
    fa = (B2B_TIRED if a_b2b else 1) * (B2B_VS_TIRED if h_b2b else 1)
    return fh, fa


def walk(games, k=K, w=W_GOALS, regress=REGRESS, use_goalies=True, shrink=G_SHRINK, decay=G_DECAY, use_b2b=True,
         recency=1.0, roster_w=0.0, known_starters=True):
    """Go through games in date order; for each one, record the projection made
    using ONLY games played before it. Returns (per-game projections, final ratings, goalie skills).

    With goalies on, a team's defense rating is built from xG against only (shot
    quality allowed by the skaters) and the opposing starter's skill scales it."""
    rows, prior, ratings = [], {}, {}
    wd = 0.0 if use_goalies else w  # defense blend weight on real goals
    starter, by_game, gg = load_goalies()
    gs = GoalieSkill(gg[gg.season < games.season.min()], shrink, decay)
    recent = {}  # team -> its last 10 starters, for when the real starter isn't known yet

    def pick(gid, team):
        if known_starters:
            return starter.get((gid, team))
        r = recent.get(team)
        return max(set(r), key=r.count) if r else None
    for season, sg in games.groupby("season", sort=True):
        gs.new_season()
        tot = {}  # team -> [gf, ga, n]
        league_n, league_g = 0, 0.0
        L = np.mean([v for p in prior.values() for v in p]) if prior else 3.05
        if roster_w and season >= 2022:
            # blend last season's team rating with this season's roster (player-based)
            for t, (f, a) in players.roster_ratings(season).items():
                po, pd_ = prior.get(t, (L, L))
                prior[t] = ((1 - roster_w) * po + roster_w * L * f, (1 - roster_w) * pd_ + roster_w * L * a)
        for r in sg.itertuples():
            def rating(t):
                po, pd_ = prior.get(t, (L, L))
                gf, ga, n, _ = tot.get(t, (0.0, 0.0, 0, 0))
                return (k * po + gf) / (k + n), (k * pd_ + ga) / (k + n)
            Lnow = (k * 10 * L + league_g) / (k * 10 + league_n)  # league goals per team-game
            ho, hd = rating(r.home)
            ao, ad = rating(r.away)
            lam_h = ho * ad / Lnow
            lam_a = ao * hd / Lnow
            if use_goalies:
                lam_h *= 1 - gs.skill(pick(r.gameId, r.away))
                lam_a *= 1 - gs.skill(pick(r.gameId, r.home))
            if use_b2b:
                fh, fa = b2b_factors(r.h_b2b, r.a_b2b)
                lam_h *= fh; lam_a *= fa
            rows.append((r.gameId, season, r.gameDate, r.home, r.away, lam_h + lam_a, r.total, lam_h, lam_a))
            # update with this game's result: offense = blend of real goals and xG,
            # defense = same blend, or xG only when goalies are modeled separately
            hf, af = w * r.hg + (1 - w) * r.hxg, w * r.ag + (1 - w) * r.axg
            hd_, ad_ = wd * r.ag + (1 - wd) * r.axg, wd * r.hg + (1 - wd) * r.hxg
            for t, f, a in ((r.home, hf, hd_), (r.away, af, ad_)):
                x = tot.setdefault(t, [0.0, 0.0, 0, 0])
                x[3] += 1  # games played (unweighted)
                # recency < 1 fades older games (1.0 = every game counts the same)
                x[0] = x[0] * recency + f; x[1] = x[1] * recency + a; x[2] = x[2] * recency + 1
            league_n += 2; league_g += hf + af
            for p, xg, g in by_game.get(r.gameId, ()):
                gs.add(p, xg, g)
            for t in (r.home, r.away):
                if (r.gameId, t) in starter:
                    recent[t] = (recent.get(t, []) + [starter[(r.gameId, t)]])[-10:]
        Lend = league_g / league_n
        ratings = {t: ((k * prior.get(t, (L, L))[0] + v[0]) / (k + v[2]),
                       (k * prior.get(t, (L, L))[1] + v[1]) / (k + v[2])) for t, v in tot.items()}
        for t in set(prior) - set(ratings):
            ratings[t] = prior[t]
        # next season's prior: this season's full-season rate, pulled toward league average
        prior = {t: (Lend + (1 - regress) * (v[0] / v[2] - Lend), Lend + (1 - regress) * (v[1] / v[2] - Lend))
                 for t, v in tot.items() if v[3] >= 20} or prior
        ratings["_L"] = (Lend, Lend)
    proj = pd.DataFrame(rows, columns=["gameId", "season", "gameDate", "home", "away", "proj", "total", "lam_h", "lam_a"])
    return proj, ratings, gs


def logit_fit(X, y):
    """Logistic regression by Newton's method. X: (n, k) without intercept."""
    X = np.column_stack([np.ones(len(X)), X])
    beta = np.zeros(X.shape[1])
    with np.errstate(all="ignore"):  # numpy 2.x on Apple Silicon raises false matmul warnings
        for _ in range(50):
            p = 1 / (1 + np.exp(-X @ beta))
            H = X.T @ (X * (p * (1 - p))[:, None])
            beta += np.linalg.solve(H, X.T @ (y - p))
    return beta


def fit_calibration(proj):
    """Logistic fit: P(total >= k) as a function of projected total and closeness, for each k.
    Real NHL totals bunch together more than a Poisson curve assumes, so we fit
    the probabilities directly from history instead. Closeness = |home - away projection|: evenly matched
    games go 7+ a bit more often at the same total (overtime, shootout goal, late empty-netters;
    research/close_p7_seasons.py)."""
    X = np.column_stack([proj.proj.values, (proj.lam_h - proj.lam_a).abs().values])
    out = {k: tuple(logit_fit(X, (proj.total >= k).values.astype(float))) for k in range(4, 10)}
    out["over"], out["under"] = out[7], tuple(-v for v in out[6])  # over 6 = 7+, under 6 = 5 or less
    return out


def p_from(cal, name, x, gap):
    """P(total >= name) for projected total x and closeness gap = |home - away projection|."""
    a, b, c = cal[name]
    return 1 / (1 + np.exp(-(a + b * x + c * gap)))


def backtest():
    games = load_games()
    proj, _, _ = walk(games)
    proj = proj[proj.season >= 2022]  # 2021 only serves as the starting prior
    train, test = proj[proj.season <= 2023], proj[proj.season.isin([2024, 2025])]
    cal = fit_calibration(train)

    y = (test.total >= 7).astype(float).values
    gap = (test.lam_h - test.lam_a).abs().values
    p = p_from(cal, "over", test.proj.values, gap)
    base = (train.total >= 7).mean()
    brier, brier0 = np.mean((p - y) ** 2), np.mean((base - y) ** 2)
    print(f"Fit on 2022-23 + 2023-24, tested on 2024-25 + 2025-26 ({len(test)} games)")
    print(f"  over 6 happened in {y.mean():.1%} of test games, push (exactly 6) {(test.total == 6).mean():.1%}")
    print(f"  Brier score  model {brier:.4f}  vs  always-guess-base-rate {brier0:.4f}  "
          f"({(brier0 - brier) / brier0:+.1%} skill)")
    print(f"  correlation of projected total with actual total: {np.corrcoef(test.proj, test.total)[0, 1]:.3f}")

    print("\n  Calibration (does a 55% call actually hit ~55%?):")
    test = test.assign(p=p, over=y, under=(test.total <= 5).astype(float))
    test["bucket"] = pd.cut(test.p, [0, .38, .42, .46, .50, .54, .58, 1])
    t = test.groupby("bucket", observed=True).agg(games=("p", "size"), model_p=("p", "mean"),
                                                 actual_over=("over", "mean"), actual_under=("under", "mean"))
    print(t.to_string(float_format=lambda v: f"{v:.3f}"))

    print("\n  If you only bet games where the model is confident (decisions exclude pushes):")
    pu = p_from(cal, "under", test.proj.values, gap)
    for edge in (0.05, 0.08, 0.10):
        over = test[test.p - pu >= edge]
        under = test[pu - test.p >= edge]
        for lbl, s, win in (("OVER ", over, over.total >= 7), ("UNDER", under, under.total <= 5)):
            dec = (s.total != 6).sum()
            if dec:
                print(f"    {lbl} edge>={edge:.2f}: {len(s):4d} games, won {win.sum() / dec:.1%} of decided")
    print("    (at -110 odds you need 52.4% to break even)")

    print("\n  6.5 line (no pushes: 6 goals = UNDER wins):")
    o = test.total >= 7
    r = pd.Series(test.p.values).rank().values
    auc = (r[o.values].sum() - o.sum() * (o.sum() + 1) / 2) / (o.sum() * (~o).sum())
    print(f"    AUC {auc:.3f}  (0.500 = coin flip; how well it ranks over games above under games)")
    q = pd.qcut(test.p, 5, labels=["lowest 20%", "2nd", "3rd", "4th", "highest 20%"])
    t = test.assign(over65=o, q=q).groupby("q", observed=True).agg(
        games=("p", "size"), model_p=("p", "mean"), actual_over65=("over65", "mean"), avg_total=("total", "mean"))
    print(t.to_string(float_format=lambda v: f"{v:.3f}"))
    for lbl, s in (("OVER  (p>=0.50)", test[test.p >= 0.50]), ("UNDER (p<=0.40)", test[test.p <= 0.40])):
        win = (s.total >= 7) if lbl.startswith("OVER") else (s.total <= 6)
        print(f"    {lbl}: {len(s):4d} games, won {win.mean():.1%}")
    print("    break-even: +120 needs 45.5%, -110 needs 52.4%, -140 needs 58.3%")


def norm_name(s):
    """Compare team names safely: 'Montréal' == 'Montreal', 'St. Louis' == 'St Louis'."""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return " ".join(s.replace(".", "").lower().split())


def dailyfaceoff(day):
    """Projected/confirmed starters: {normalized team name: (goalie name, status)}"""
    html = urllib.request.urlopen(fetch(f"https://www.dailyfaceoff.com/starting-goalies/{day}")).read().decode()
    data = json.loads(re.search(r'__NEXT_DATA__" type="application/json">(.*?)</script>', html).group(1))
    out = {}
    for g in data["props"]["pageProps"]["data"]:
        for side in ("home", "away"):
            out[norm_name(g[f"{side}TeamName"])] = (g[f"{side}GoalieName"], g[f"{side}NewsStrengthName"] or "Unconfirmed")
    return out


def lineup_label(info):
    """'Last game (Oct 1)' or 'Walt Ruff, 6:40 PM' - where the projected lineup came from and when."""
    if not info:
        return None
    src = info["source"]
    if src.lower().startswith("last game"):
        return src.replace("Last Game", "last game's lineup")
    try:
        t = pd.Timestamp(info["updated"]).tz_convert("America/New_York").strftime("%b %-d %-I:%M %p")
    except Exception:
        t = ""
    return f"{src} {t}".strip()


HIGH_Q = 0.60  # "high-scoring" = team's projected goals in the top 40% of last season's team projections


def today(day=None):
    """Daily projections from the 5v5 / power-play split model (2020-21 onward data only), with the
    overs flag: OVER only, line 6 or 6.5, both teams high-scoring."""
    import grade
    import odds
    import split_model as sm
    import trends
    import health  # every source is retried until it works (health.attempt); failures re-run the job
    day = day or date.today().isoformat()
    health.attempt("MoneyPuck stats", lambda: refresh_data() or (_ for _ in ()).throw(RuntimeError("download failed")),
                   waits=[60, 180])  # on failure the previous download is still used
    load_games()
    games = sm.load_split()
    season = sm.season_of(date.fromisoformat(day))  # from the date, not the data (opening day has no games yet)
    health.attempt("Goalie data", lambda: goalies.refresh([season]) or True)
    import speed  # team skating speed: this season uses LAST season's numbers (fetched once per season)
    health.attempt("NHL EDGE speed", lambda: speed.refresh(season - 1) or True)
    proj, project = sm.walk_split(games, known_starters=False, with_projector=True, live_season=season)
    cal = fit_calibration(proj[proj.season.between(2022, season - 1)])
    prev = proj[proj.season == season - 1]
    cutoff = np.quantile(np.r_[prev.lam_h, prev.lam_a], HIGH_Q)

    def schedule(d):
        with urllib.request.urlopen(fetch(f"https://api-web.nhle.com/v1/schedule/{d}")) as f:
            return [g for wk in json.load(f)["gameWeek"] if wk["date"] == d for g in wk["games"]]
    sched = health.attempt("NHL schedule", lambda: schedule(day))
    if sched is None:
        health.finish()
        raise RuntimeError("NHL schedule unavailable after retries")
    todays = [g for g in sched if g["gameType"] == 2]
    yday = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    # back-to-back = played a real game yesterday (the effect was measured on regular-season games;
    # preseason and postponed games don't count)
    tired = {g[s]["abbrev"] for g in (health.attempt("NHL schedule (yesterday)", lambda: schedule(yday)) or [])
             if g["gameType"] in (2, 3) and g.get("gameScheduleState", "OK") == "OK"
             for s in ("homeTeam", "awayTeam")}
    if not todays:
        print(f"No regular-season games on {day}.")
        health.finish()
        return
    dfo = health.attempt("DailyFaceoff goalies", lambda: dailyfaceoff(day), {}, must=True)
    lines = {}
    for book, label in ((30, "open"), (15, "now")):
        rows = health.attempt(f"Action Network {label} lines",
                              lambda b=book: odds.day_games(date.fromisoformat(day), b, completed_only=False), [], must=True)
        for r in rows:
            key = (grade.ABBR.get(r["home"], r["home"]), grade.ABBR.get(r["away"], r["away"]))
            lines.setdefault(key, {})[label] = r
    shop = {}  # (home, away) -> [(book name, total, over, under)] for real sportsbooks
    import books

    def all_books():
        names = books.book_names()
        return [(r, names) for r in books.day_all_books(date.fromisoformat(day), completed_only=False)]
    for r, names in health.attempt("Sportsbook lines", all_books, [], must=True):
        if r["book"] in books.NOT_BOOKS:
            continue
        key = (grade.ABBR.get(r["home"], r["home"]), grade.ABBR.get(r["away"], r["away"]))
        shop.setdefault(key, []).append((names.get(r["book"], str(r["book"])), r["total"], int(r["over"]), int(r["under"])))
    import confirm  # second and third sources for starting goalies (+ Rotowire injuries)
    rw_goalies, rw_injuries = health.attempt("Rotowire", confirm.rotowire, ({}, {}), must=True)
    gp_goalies = health.attempt("GoaliePost", confirm.goaliepost, {}, must=True)
    # starting goalies: DailyFaceoff + Rotowire + GoaliePost combined (confirm.combine)
    dfo_by_team = {t["abbrev"]: dfo.get(norm_name(f'{t["placeName"]["default"]} {t["commonName"]["default"]}'), (None, None))
                   for g in todays for t in (g["homeTeam"], g["awayTeam"])}
    goalie_calls = {t: confirm.combine(r) for t, r in confirm.gather(dfo_by_team, rw_goalies, gp_goalies).items()}
    import injuries
    injured = health.attempt("ESPN injuries", injuries.fetch, [], must=True)
    injured = confirm.add_rotowire_injuries(injured, rw_injuries)
    import lineups  # projected lineups (DailyFaceoff) vs official NHL rosters: healthy scratches, late changes
    playing = [t["abbrev"] for g in todays for t in (g["homeTeam"], g["awayTeam"])]
    lineup_info = health.attempt("DailyFaceoff lineups", lambda: lineups.outs(day, playing), {}, must=True)
    injured = injuries.merge_lineups(injured, lineup_info)
    try:  # remove missing regulars, replace with replacement-level players
        inj = injuries.adjustments(injured, season, injuries.team_games_this_season(games, season))
    except Exception as e:
        print(f"(couldn't compute injury adjustments: {e}; projecting without them)")
        inj = {}
    no_inj = {"off": 1.0, "def": 1.0, "out": [], "dtd": []}
    st = pd.read_csv(goalies.STARTS)
    ids = {n.lower(): p for n, p in zip(st.name, st.playerId)}
    recent = st[(st.started == 1) & (st.season >= st.season.max() - 1)].sort_values("gameId")

    def starter(team_abbrev, team_name):
        name, status, _, pid = goalie_calls.get(team_abbrev, (None, None, "", None))
        if name:
            pid = pid or ids.get(name.lower()) or next((p for n, p in ids.items() if confirm.same(n, name)), None)
            return name, pid, status  # no id = no history in the goalie file: rated as an average goalie
        # fallback: whoever started most of the team's last 10 games
        r = recent[recent.team == team_abbrev].tail(10)
        if not len(r):
            return "unknown", None, "-"
        p = r.playerId.mode()[0]
        return r[r.playerId == p].name.iloc[0], p, "guess: usual starter"

    def over_ev(total, over, x, gap):
        """Model expected profit per 1 unit on the OVER (a 6 can push; a 6.5 can't)."""
        p_win = p_from(cal, int(np.floor(total)) + 1, x, gap)
        p_push = p_from(cal, 6, x, gap) - p_from(cal, 7, x, gap) if total == 6 else 0.0
        return p_win * float(grade.payout(over)) - (1 - p_win - p_push)

    def best_over(key, x, gap):
        """Best OVER at 6 or 6.5 across sportsbooks, by model expected value."""
        opts = [(over_ev(t, o, x, gap), b, t, o, u) for b, t, o, u in shop.get(key, []) if t in (6.0, 6.5)]
        return max(opts) if opts else None

    def fmt(ln):
        return f"{ln['total']:g} o{ln['over']:+d}/u{ln['under']:+d}" if ln else "-"

    flagged, log_rows = [], []
    print(f"{day}  (high-scoring = projected {cutoff:.2f}+ goals for that team)\n")
    for g in todays:
        h, a = g["homeTeam"]["abbrev"], g["awayTeam"]["abbrev"]
        hname = f'{g["homeTeam"]["placeName"]["default"]} {g["homeTeam"]["commonName"]["default"]}'
        aname = f'{g["awayTeam"]["placeName"]["default"]} {g["awayTeam"]["commonName"]["default"]}'
        hg, hp, hs = starter(h, hname)
        ag, ap, as_ = starter(a, aname)
        lh, la, det = project(h, a, hp, ap, h in tired, a in tired, detail=True, season=season)
        ih, ia = inj.get(h, no_inj), inj.get(a, no_inj)
        fh_inj, fa_inj = ih["off"] * ia["def"], ia["off"] * ih["def"]  # own injuries + opponent's injured defenders
        lh, la = lh * fh_inj, la * fa_inj
        det["home"]["inj"], det["away"]["inj"] = fh_inj - 1, fa_inj - 1
        x, gap = lh + la, abs(lh - la)
        p7 = p_from(cal, 7, x, gap)
        ln = lines.get((h, a), {})
        cur = ln.get("now") or ln.get("open")
        high_h, high_a = lh >= cutoff, la >= cutoff
        flag = high_h and high_a and cur is not None and cur["total"] in (6.0, 6.5)
        star = "  *** OVER FLAG ***" if flag else ""
        print(f"{a:>3} @ {h:<3}  proj {x:4.2f} ({a} {la:.2f}{'+' if high_a else ''}, {h} {lh:.2f}{'+' if high_h else ''})"
              f"   P(7+) {p7:5.1%}{star}")
        line_txt = f"open {fmt(ln.get('open'))}   now {fmt(ln.get('now'))}"
        if cur:
            k = int(np.floor(cur["total"])) + 1  # smallest total that wins the over
            line_txt += f"   model P(over {cur['total']:g}) {p_from(cal, k, x, gap):.1%}"
        print(f"     {line_txt}")
        best = best_over((h, a), x, gap)
        if best:
            ev, bk, bt, bo, bu = best
            others = ", ".join(f"{b} {t:g} {o:+d}" for b, t, o, u in sorted(shop[(h, a)]) if b != bk)
            print(f"     best over 6/6.5: {bk} o{bt:g} {bo:+d}   others: {others}")
        print(f"     G: {ag} ({as_}, {project.goalie_skill(ap):+.1%}) vs {hg} ({hs}, {project.goalie_skill(hp):+.1%})"
              + (f"   back-to-back: {', '.join(sorted(tired & {h, a}))}" if tired & {h, a} else ""))
        for t, ii in ((a, ia), (h, ih)):
            if ii["out"] or ii["dtd"]:
                print(f"     injuries {t}: " + ", ".join(
                    f"{n} out ({-o * 100:+.1f}% GF)" if abs(o) >= abs(d) else f"{n} out ({d * 100:+.1f}% GA)" for n, o, d in ii["out"])
                      + (" | day-to-day: " + ", ".join(ii["dtd"]) if ii["dtd"] else ""))
        if flag:
            flagged.append(f"{a} @ {h} OVER {cur['total']:g} ({cur['over']:+d})"
                           + (f" -> best: {best[1]} o{best[2]:g} {best[3]:+d}" if best else ""))
        op = ln.get("open")
        tr = trends.compute(games, day, h, a)  # recent form + head-to-head (context only, not in the projection)
        log_rows.append({"start_utc": g["startTimeUTC"], "game_id": g.get("id"), "date": day, "away": a, "home": h, "proj": round(x, 3), "proj_away": round(la, 3),
                         "proj_home": round(lh, 3), "cutoff": round(cutoff, 3), "flag": bool(flag), "p7": round(p7, 4),
                         "away_goalie": f"{ag} ({as_})", "home_goalie": f"{hg} ({hs})",
                         "open_total": op["total"] if op else None, "open_over": op["over"] if op else None,
                         "bet_total": cur["total"] if cur else None, "bet_over": cur["over"] if cur else None,
                         "bet_under": cur["under"] if cur else None,
                         "best_book": best[1] if best else None, "best_total": best[2] if best else None,
                         "best_over": best[3] if best else None, "best_under": best[4] if best else None,
                         "logged_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
                         "away_b2b": a in tired, "home_b2b": h in tired,
                         "away_goalie_now": f"{ag} ({as_})", "home_goalie_now": f"{hg} ({hs})",
                         "away_goalie_src": goalie_calls.get(a, (None, None, None))[2] or None,
                         "home_goalie_src": goalie_calls.get(h, (None, None, None))[2] or None,
                         "updated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
                         "away_out": "; ".join(f"{n}|{o:.4f}|{d:.4f}" for n, o, d in ia["out"]) or None,
                         "home_out": "; ".join(f"{n}|{o:.4f}|{d:.4f}" for n, o, d in ih["out"]) or None,
                         "away_dtd": ", ".join(ia["dtd"]) or None, "home_dtd": ", ".join(ih["dtd"]) or None,
                         "away_lineup": lineup_label(lineup_info.get(a)), "home_lineup": lineup_label(lineup_info.get(h)),
                         **tr,
                         **{f"{s}_{c}": round(v, 4) for s in ("away", "home") for c, v in det[s].items()}})
    print("\n(goalie % = share of expected goals stopped beyond average; higher = better)")
    print("OVER FLAG = both teams high-scoring (marked +) and the line is 6 or 6.5. Overs only, never 5.5.")
    print("Always bet the 'best over' book: line shopping added ~+2 pts ROI in the backtest.")
    print("Model uses 2020-21 onward only. Tested 2021-26: +1.3% ROI at open, +2.4% at close, 53-55% wins"
          " (+2 pts more with line shopping). Small, unproven edge: judge it on live paper trading.")
    print("\nTODAY'S FLAGS: " + ("; ".join(flagged) if flagged else "none"))
    if day == date.today().isoformat():  # never log past dates: that would be hindsight
        with open(paths.data("last_run.txt"), "w") as f:  # shown on the dashboard
            f.write(pd.Timestamp.now(tz="America/New_York").strftime("%Y-%m-%d %H:%M %Z") + "\n")
        import paper
        added, upgraded = paper.log_games(log_rows)
        import store  # run history in Supabase (skipped when not configured; never stops the run)
        store.record_run(day, log_rows, sources={"dailyfaceoff": bool(dfo), "lines": bool(lines), "sportsbooks": bool(shop),
                                                 "lineups": bool(lineup_info), "injuries": bool(inj)})
        try:  # team rankings for the dashboard (each team vs a league-average opponent)
            rk = sm.team_rankings(project, set(games[games.season >= season - 1].home), season, games)
            rk.to_csv(paths.data("team_rankings.csv"), index=False)
            sm.save_rankings_day(rk, day)
        except Exception as e:
            print(f"(team rankings not saved: {e})")
        try:  # games already under way: record who actually started (NHL box score)
            paper.update_actual_starters()
        except Exception as e:
            print(f"(couldn't record actual starters: {e})")
        store.sync_log(paper.read_log())
        print(f"(paper log: {added} new games, {upgraded} newly flagged, in {paper.LOG})")
    bad = health.finish()
    print("(all data sources OK)" if not bad else f"(still failing after retries: {', '.join(bad)})")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "today"
    backtest() if cmd == "backtest" else today(sys.argv[2] if len(sys.argv) > 2 else None)
