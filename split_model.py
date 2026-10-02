"""Variant: project goals separately for 5-on-5 and power play / penalty kill.

home goals = 5v5 (home 5v5 offense x away 5v5 defense x 5v5 minutes)
           + PP  (home PP x away PK x [home penalties drawn x away penalties taken])
           + other (4v4, 3v3 OT, empty nets...: league average)
then scaled by the opposing starter's goalie skill and back-to-backs, as in model.py.
"""
import numpy as np
import pandas as pd

import model as m
import players

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


def walk_split(games, k=m.K, w=m.W_GOALS, regress=m.REGRESS, known_starters=True, with_projector=False, roster_w=0.0):
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
    rows = []

    def project(home, away, home_goalie, away_goalie, h_b2b=False, a_b2b=False):
        """Projected (home goals, away goals) from the ratings as they stand right now."""
        g = {key: {t: R[key].get(t) for t in (home, away)} for key in R}
        def goals(att, dfn):
            ev = g["off5"][att] * g["def5"][dfn] / R["def5"].lg * T5
            pp_time = g["drawn"][att] * g["taken"][dfn] / R["taken"].lg
            pp = g["pp"][att] * g["pk"][dfn] / R["pk"].lg * pp_time
            return ev + pp + other / 2
        fh, fa = m.b2b_factors(h_b2b, a_b2b)
        return (goals(home, away) * (1 - gs.skill(away_goalie)) * fh,
                goals(away, home) * (1 - gs.skill(home_goalie)) * fa)

    last = games.season.max()
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
            lam_h, lam_a = project(r.home, r.away, pick(r.home), pick(r.away), r.h_b2b, r.a_b2b)
            rows.append((r.gameId, season, r.gameDate, r.home, r.away, lam_h + lam_a, r.total, lam_h, lam_a))
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
    proj = pd.DataFrame(rows, columns=["gameId", "season", "gameDate", "home", "away", "proj", "total", "lam_h", "lam_a"])
    project.goalie_skill = gs.skill
    return (proj, project) if with_projector else proj
