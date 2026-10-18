"""Two-season prior (suggestion #1, Oct 18 2026). Each season starts every team rating from LAST season only, pulled
REGRESS (0.33) toward league average and worth K games. Here the starting point blends the last two seasons
(weight a on last season, 1 - a on the one before), so a team with one fluky year is steadied by the year before.
Teams without the earlier season (e.g. new names) use last season only. REGRESS is re-gridded too, since averaging two
seasons already pulls toward the middle. Applies to every rating (5v5, PP / PK, penalties drawn / taken).

  python3 research/studies/two_season_prior.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))

from judge import header, row, scorecard  # first: puts src/ on the path
import split_model as sm

LIVE_END = sm.Rate.end_season


def blended_end(a):
    def end_season(self, regress):
        older = getattr(self, "last_rates", {})
        tot_n = sum(v[0] for v in self.sum.values())
        tot_d = sum(v[1] for v in self.sum.values())
        self.lg = tot_n / tot_d if tot_d else self.lg
        now = {t: n / dnm for t, (n, dnm) in self.sum.items() if dnm}
        blend = {t: a * r + (1 - a) * older[t] if t in older else r for t, r in now.items()}
        self.prior = {t: self.lg + (1 - regress) * (r - self.lg) for t, r in blend.items()}
        self.last_rates = now
        self.sum = {}
    return end_season


def main():
    games = sm.load_split()
    base = None
    print(header(34))
    for a, reg in [(1.0, None)] + [(a, r) for a in (0.85, 0.7, 0.6) for r in (0.33, 0.25, 0.15)]:
        sm.Rate.end_season = LIVE_END if a == 1.0 else blended_end(a)
        p = sm.walk_split(games, known_starters=False, record_detail=True, **({"regress": reg} if reg is not None else {}))
        sc = scorecard(p, games)
        base = base or sc
        label = "live (last season only, 0.33)" if a == 1.0 else f"last {a:.0%} / prior {1 - a:.0%}, regress {reg}"
        print(row(label, sc, 34, base))
    sm.Rate.end_season = LIVE_END


if __name__ == "__main__":
    main()
