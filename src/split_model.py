"""Variant: project goals separately for 5-on-5 and power play / penalty kill.

home goals = 5v5 (home 5v5 offense x away 5v5 defense x 5v5 minutes)
           + PP  (home PP x away PK x [home penalties drawn x away penalties taken])
           + other (4v4, 3v3 OT, empty nets...: league average)
then scaled by the opposing starter's goalie skill and back-to-backs, as in model.py.
"""
import pandas as pd

import model as m
import paths
import players
import speed

SITS = {"5on5": "ev", "5on4": "pp", "4on5": "pk", "other": "o"}
FIRST_SEASON = 2020  # use nothing (games, goalie history) from before the 2020-21 season


def load_split(xg="xGoals", first_season=FIRST_SEASON):
    d = pd.read_csv(m.DATA, usecols=["season", "gameId", "home_or_away", "gameDate", "situation", "iceTime",
                                     f"{xg}For", f"{xg}Against", "goalsFor", "goalsAgainst", "playoffGame"])
    d = d[(d.playoffGame == 0) & (d.home_or_away == "HOME") & d.situation.isin(SITS)]
    d = d.drop_duplicates(["gameId", "situation"])
    w = d.pivot(index="gameId", columns="situation", values=["iceTime", f"{xg}For", f"{xg}Against", "goalsFor", "goalsAgainst"])
    w.columns = [f"{SITS[s]}_{c.replace(xg, 'x')}" for c, s in w.columns]
    base = m.load_games(xg=xg)
    base = base[base.season >= (first_season or 0)]
    return base.join(w.fillna(0), on="gameId").dropna(subset=["ev_iceTime"]).reset_index(drop=True)


class Rate:
    """Per-team rate = (shrink * prior + sum of numerator) / (shrink + sum of denominator)."""
    def __init__(self, shrink):
        self.shrink, self.sum, self.prior, self.lg = shrink, {}, {}, None

    def get(self, t):
        p = self.prior.get(t, self.lg)
        n, dnm = self.sum.get(t, (0.0, 0.0))
        return (self.shrink * p + n) / (self.shrink + dnm)

    def add(self, t, num, den):
        n, dnm = self.sum.get(t, (0.0, 0.0))
        self.sum[t] = (n + num, dnm + den)

    def end_season(self, regress):
        tot_n = sum(v[0] for v in self.sum.values())
        tot_d = sum(v[1] for v in self.sum.values())
        self.lg = tot_n / tot_d if tot_d else self.lg
        self.prior = {t: self.lg + (1 - regress) * (n / dnm - self.lg) for t, (n, dnm) in self.sum.items() if dnm}
        self.sum = {}


def team_rankings(project, teams, season, games=None):
    """Each team vs a league-average opponent ('AVG' falls back to league rates; no goalie or back-to-back):
    goals scored (offense) and goals allowed by its skaters (defense), with the 5v5 and power-play parts.
    With games: strength of schedule too. opp_d / opp_o = how much more (+) or less (-) than average the
    defenses / offenses faced this season allow / score; gf_adj / ga_adj = the totals corrected for the
    schedule behind the rating (last season's opponents count K*(1-REGRESS) games, this season's 1 each)."""
    rows = []
    for t in sorted(teams):
        gf, ga, det = project(t, "AVG", None, None, detail=True, season=season)
        o, d = det["home"], det["away"]
        rows.append({"team": t, "gf": round(gf, 3), "gf_ev": round(o["ev"], 3), "gf_pp": round(o["pp"], 3),
                     "ga": round(ga, 3), "ga_ev": round(d["ev"], 3), "ga_pp": round(d["pp"], 3)})
    r = pd.DataFrame(rows)
    if games is None:
        return r
    lg = r.gf.mean()
    leak, punch = dict(zip(r.team, r.ga / lg - 1)), dict(zip(r.team, r.gf / lg - 1))

    def faced(g, t):
        opp = pd.concat([g[g.home == t].away, g[g.away == t].home])
        opp = [x for x in opp if x in leak]
        return (len(opp), sum(leak[x] for x in opp) / len(opp), sum(punch[x] for x in opp) / len(opp)) if opp else (0, 0.0, 0.0)
    prior = m.K * (1 - m.REGRESS)
    cur_g, last_g = games[games.season == season], games[games.season == season - 1]
    sos = []
    for t in r.team:
        n, d_now, o_now = faced(cur_g, t)
        _, d_last, o_last = faced(last_g, t)
        d_eff = (prior * d_last + n * d_now) / (m.K + n)
        o_eff = (prior * o_last + n * o_now) / (m.K + n)
        sos.append({"games": n, "opp_d": round(d_now, 4), "opp_o": round(o_now, 4), "gf_adj": round(r.gf[r.team == t].iloc[0] / (1 + d_eff), 3),
                    "ga_adj": round(r.ga[r.team == t].iloc[0] / (1 + o_eff), 3)})
    return pd.concat([r, pd.DataFrame(sos)], axis=1)


RANKINGS_HISTORY = paths.data("team_rankings_history.csv")


def save_rankings_day(rk, day):
    """Keep the day's latest rankings in data/team_rankings_history.csv, so results pages show the ranks
    teams had on game day."""
    import os
    old = pd.read_csv(RANKINGS_HISTORY) if os.path.exists(RANKINGS_HISTORY) else pd.DataFrame()
    if len(old):
        old = old[old.date != day]
    pd.concat([old, rk.assign(date=day)], ignore_index=True).to_csv(RANKINGS_HISTORY, index=False)


def season_of(day):
    """NHL season (start year) a date belongs to: Aug-Dec -> that year, Jan-Jul -> the year before."""
    return day.year if day.month >= 8 else day.year - 1


def walk_split(games, k=m.K, w=m.W_GOALS, regress=m.REGRESS, known_starters=True, with_projector=False, roster_w=0.0,
               live_season=None, use_speed=True, record_detail=False):
    """live_season: the season being projected. If it's newer than the data (e.g. opening day, before any
    of its games exist), last season's ratings are rolled over into this season's starting ratings."""
    starter, by_game, gg = m.load_goalies()
    # goalie history only from seasons that are part of this run (nothing before games' first season)
    gs = m.GoalieSkill(gg.iloc[0:0])
    recent = {}
    first = games[games.season == games.season.min()]
    avg = lambda c: first[c].mean()
    # shrink sizes = k games' worth of each denominator
    t5, tpp = avg("ev_iceTime"), (avg("pp_iceTime") + avg("pk_iceTime")) / 2
    R = {"off5": Rate(k * t5), "def5": Rate(k * t5), "pp": Rate(k * tpp), "pk": Rate(k * tpp),
         "drawn": Rate(k), "taken": Rate(k)}
    lg_init = {"off5": avg("ev_xFor") / t5, "def5": avg("ev_xFor") / t5,
               "pp": avg("pp_xFor") / avg("pp_iceTime"), "pk": avg("pp_xFor") / avg("pp_iceTime"),
               "drawn": tpp, "taken": tpp}
    for key, r in R.items():
        r.lg = lg_init[key]
    other = avg("o_goalsFor") + avg("o_goalsAgainst")
    T5 = t5  # league 5v5 seconds per game, updated as games come in
    rows, details = [], []
    zspeed = speed.z_prev(games) if use_speed else {}

    def project(home, away, home_goalie, away_goalie, h_b2b=False, a_b2b=False, detail=False, season=None):
        """Projected (home goals, away goals) from the ratings as they stand right now.
        detail=True also returns each side's parts: 5v5, power play, other situations,
        and the opposing goalie / back-to-back adjustments (as fractions, e.g. -0.05)."""
        g = {key: {t: R[key].get(t) for t in (home, away)} for key in R}
        def parts(att, dfn):
            ev = g["off5"][att] * g["def5"][dfn] / R["def5"].lg * T5
            pp_time = g["drawn"][att] * g["taken"][dfn] / R["taken"].lg
            pp = g["pp"][att] * g["pk"][dfn] / R["pk"].lg * pp_time
            return ev, pp, other / 2
        fh, fa = m.b2b_factors(h_b2b, a_b2b)
        s_ = season if season is not None else last
        zh, za = zspeed.get((s_, home), 0.0), zspeed.get((s_, away), 0.0)
        sh, sa = 1 + m.SPEED_OWN * zh + m.SPEED_OPP * za, 1 + m.SPEED_OWN * za + m.SPEED_OPP * zh
        out, det = [], {}
        for side, att, dfn, goalie, f, spd in (("home", home, away, away_goalie, fh, sh), ("away", away, home, home_goalie, fa, sa)):
            ev, pp, oth = parts(att, dfn)
            gadj = -gs.skill(goalie)
            out.append((ev + pp + oth) * (1 + gadj) * f * spd)
            det[side] = {"ev": ev, "pp": pp, "oth": oth, "gadj": gadj, "b2badj": f - 1, "spd": spd - 1}
        return (out[0], out[1], det) if detail else (out[0], out[1])

    last = max(games.season.max(), live_season or 0)
    for season, sg in games.groupby("season", sort=True):
        gs.new_season()
        if roster_w and R["off5"].prior:
            # blend last season's team 5v5 rates with this season's roster (players' past on-ice xG)
            for t, (f, a) in players.roster_ratings(season, min_season=games.season.min()).items():
                for key, ratio in (("off5", f), ("def5", a)):
                    rt = R[key]
                    rt.prior[t] = (1 - roster_w) * rt.prior.get(t, rt.lg) + roster_w * rt.lg * ratio
        for r in sg.itertuples():
            def pick(team):
                if known_starters:
                    return starter.get((r.gameId, team))
                rr = recent.get(team)
                return max(set(rr), key=rr.count) if rr else None
            lam_h, lam_a, det = project(r.home, r.away, pick(r.home), pick(r.away), r.h_b2b, r.a_b2b, detail=True, season=season)
            rows.append((r.gameId, season, r.gameDate, r.home, r.away, lam_h + lam_a, r.total, lam_h, lam_a))
            if record_detail:  # per-team breakdown, for analysis (e.g. tier cutoffs)
                details.append({"gameId": r.gameId, "season": season,
                                 **{f"{sd}_{k}": v for sd in ("home", "away") for k, v in det[sd].items()}})
            # update: offense = blend of goals and xG, defense = xG only (goalie handled separately)
            bl = lambda gl, x: w * gl + (1 - w) * x
            row = r._asdict()
            R["off5"].add(r.home, bl(row["ev_goalsFor"], row["ev_xFor"]), row["ev_iceTime"])
            R["off5"].add(r.away, bl(row["ev_goalsAgainst"], row["ev_xAgainst"]), row["ev_iceTime"])
            R["def5"].add(r.home, row["ev_xAgainst"], row["ev_iceTime"])
            R["def5"].add(r.away, row["ev_xFor"], row["ev_iceTime"])
            # home 5on4 row = home power play; home 4on5 row = away power play
            R["pp"].add(r.home, bl(row["pp_goalsFor"], row["pp_xFor"]), row["pp_iceTime"])
            R["pp"].add(r.away, bl(row["pk_goalsAgainst"], row["pk_xAgainst"]), row["pk_iceTime"])
            R["pk"].add(r.home, row["pk_xAgainst"], row["pk_iceTime"])
            R["pk"].add(r.away, row["pp_xFor"], row["pp_iceTime"])
            R["drawn"].add(r.home, row["pp_iceTime"], 1); R["drawn"].add(r.away, row["pk_iceTime"], 1)
            R["taken"].add(r.home, row["pk_iceTime"], 1); R["taken"].add(r.away, row["pp_iceTime"], 1)
            other = 0.995 * other + 0.005 * (row["o_goalsFor"] + row["o_goalsAgainst"])
            T5 = 0.995 * T5 + 0.005 * row["ev_iceTime"]
            for p, xg, gl in by_game.get(r.gameId, ()):
                gs.add(p, xg, gl)
            for t in (r.home, r.away):
                if (r.gameId, t) in starter:
                    recent[t] = (recent.get(t, []) + [starter[(r.gameId, t)]])[-10:]
        if season != last:  # keep the current season's ratings live for today's games
            for rate in R.values():
                rate.end_season(regress)
    if last > games.season.max():  # new season with no games yet: start it like any other season
        gs.new_season()
    proj = pd.DataFrame(rows, columns=["gameId", "season", "gameDate", "home", "away", "proj", "total", "lam_h", "lam_a"])
    project.goalie_skill = gs.skill
    if record_detail:
        proj = proj.merge(pd.DataFrame(details), on=["gameId", "season"])
    return (proj, project) if with_projector else proj
