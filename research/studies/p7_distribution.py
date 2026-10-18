"""Correlated team goals / P(7+) shape (suggestion #9, Oct 18 2026). Live P(7+) is a logistic fit on the projected
total and closeness (model.fit_calibration), so it already learns from history how totals bunch. This asks whether an
explicit distribution does better. All fitted on 2021-23, judged on 2023-26 (log loss and Brier of P(total >= 7),
plus calibration by P(7+) bin):
  live logistic      P(7+) = logit(a + b proj + c gap)                           (live method)
  logistic+          adds proj^2 and gap^2
  Poisson            total ~ Poisson(s x proj)                                    (teams independent, s fixes the level)
  neg. binomial      total ~ NB(mean s x proj, dispersion r)                       (more spread than Poisson)
  bivariate Poisson  home = X1 + X3, away = X2 + X3, X3 = shared goals ~ Pois(rho x min(lam_h, lam_a))  (teams correlated)

  python3 research/studies/p7_distribution.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))

_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
from math import lgamma

import numpy as np

import model as m
import split_model as sm

K = 7
N = 25  # goals counted when summing a distribution


def pois_pmf(k, lam):
    lam = np.asarray(lam, float)
    return np.exp(k * np.log(lam) - lam - lgamma(k + 1))


def pois_sf(k_min, lam):
    """P(X >= k_min)."""
    lam = np.asarray(lam, float)
    k_min = np.broadcast_to(np.asarray(k_min), lam.shape)
    below = sum(np.where(k < k_min, pois_pmf(k, lam), 0.0) for k in range(N))
    return 1 - below


def nb_sf(k_min, mu, r):
    """P(X >= k_min) for a negative binomial with mean mu and dispersion r (variance mu + mu^2 / r)."""
    mu = np.asarray(mu, float)
    below = 0.0
    for k in range(k_min):
        below = below + np.exp(lgamma(k + r) - lgamma(r) - lgamma(k + 1) + r * np.log(r / (r + mu)) + k * np.log(mu / (r + mu)))
    return 1 - below


def grid_min(f, *axes):
    """Best point of f over the grid (a coarse search, then a finer one around the best)."""
    best = min(((f(*v), v) for v in np.array(np.meshgrid(*axes)).reshape(len(axes), -1).T), key=lambda t: t[0])[1]
    fine = [np.linspace(v - (a[1] - a[0]), v + (a[1] - a[0]), 9) for v, a in zip(best, axes)]
    return min(((f(*v), v) for v in np.array(np.meshgrid(*fine)).reshape(len(axes), -1).T), key=lambda t: t[0])[1]


def ll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def logistic(X, y):
    beta = m.logit_fit(X, y)
    return lambda X_: 1 / (1 + np.exp(-(np.column_stack([np.ones(len(X_)), X_]) @ np.asarray(beta))))


def p_biv(lh, la, rho, s):
    """P(home + away >= K) with a shared component X3 (counted in both teams' goals)."""
    lh, la = s * lh, s * la
    l3 = rho * np.minimum(lh, la)
    l1, l2 = lh - l3, la - l3
    out = np.zeros(len(lh))
    for k3 in range(0, 8):  # total = X1 + X2 + 2 X3; X1 + X2 ~ Pois(l1 + l2)
        need = max(K - 2 * k3, 0)
        out += pois_pmf(k3, np.maximum(l3, 1e-9)) * pois_sf(need, l1 + l2)
    return out


def main():
    games = sm.load_split()
    p = sm.walk_split(games, known_starters=False)
    p = p[p.season >= 2021].copy()
    p["gap"] = (p.lam_h - p.lam_a).abs()
    p["y"] = (p.total >= K).astype(float)
    tr, te = p[p.season.between(2021, 2022)], p[p.season.between(2023, 2025)]
    corr = np.corrcoef(*(games.merge(tr[["gameId", "lam_h", "lam_a"]], on="gameId").pipe(lambda x: (x.hg - x.lam_h, x.ag - x.lam_a))))[0, 1]
    print(f"home vs away goals (minus projection), 2021-23: correlation {corr:+.3f}; total variance / mean "
          f"{tr.total.var() / tr.total.mean():.2f} (Poisson = 1, before removing the projection's own spread)\n")
    preds = {}
    X = lambda d: np.column_stack([d.proj, d.gap])
    preds["live logistic"] = logistic(X(tr), tr.y.values)(X(te))
    X2 = lambda d: np.column_stack([d.proj, d.gap, d.proj ** 2, d.gap ** 2])
    preds["logistic+ (squares)"] = logistic(X2(tr), tr.y.values)(X2(te))
    (s,) = grid_min(lambda s: ll(pois_sf(K, s * tr.proj.values), tr.y.values), np.linspace(0.9, 1.15, 26))
    preds[f"Poisson (s {s:.3f})"] = pois_sf(K, s * te.proj.values)
    s2, lr = grid_min(lambda s, lr: ll(nb_sf(K, s * tr.proj.values, np.exp(lr)), tr.y.values),
                      np.linspace(0.9, 1.15, 14), np.linspace(np.log(5), np.log(1000), 14))
    preds[f"neg. binomial (s {s2:.3f}, r {np.exp(lr):.0f})"] = nb_sf(K, s2 * te.proj.values, np.exp(lr))
    rho, s3 = grid_min(lambda rho, s: ll(p_biv(tr.lam_h.values, tr.lam_a.values, max(rho, 0.0), s), tr.y.values),
                       np.linspace(0.0, 0.3, 13), np.linspace(0.9, 1.15, 14))
    rho = max(float(rho), 0.0)
    preds[f"bivariate Poisson (rho {rho:.3f}, s {s3:.3f})"] = p_biv(te.lam_h.values, te.lam_a.values, rho, s3)
    y = te.y.values
    print(f"P(7+) on 2023-26 ({len(te)} games, {y.mean():.1%} went 7+); lower = better")
    print(f"{'method':42s} {'log loss':>9s} {'Brier':>8s}   calibration (predicted -> actual) <42% / 42-47% / 47-52% / 52%+")
    for name, q in preds.items():
        bins = []
        for lo, hi in ((0, 0.42), (0.42, 0.47), (0.47, 0.52), (0.52, 1)):
            mk = (q >= lo) & (q < hi)
            bins.append(f"{q[mk].mean():.0%}->{y[mk].mean():.0%} ({mk.sum()})" if mk.sum() else "-")
        print(f"{name:42s} {ll(q, y):9.5f} {np.mean((q - y) ** 2):8.5f}   " + " / ".join(bins))


if __name__ == "__main__":
    main()
