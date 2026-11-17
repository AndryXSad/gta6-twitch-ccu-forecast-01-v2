# DESIGN.md — gta6-twitch-ccu-forecast-01 v2

## The problem

Forecast Grand Theft Auto VI's launch-day Twitch viewers, hour by hour
(hours 2–24), as five quantiles each. Score: pinball loss on the log
scale, averaged over hours × levels. The program gets one case: the
release day's hour-1 print, the category's hourly history, and ~38
comparable past launches with their hourly series. GTA VI is a
mega-launch: its hour-1 print will very likely exceed every comparable's,
so the model must extrapolate in size while keeping the shape honest.

## Where v1 stood

v1 ("Limber Obelisk") was a 50/50 log-space blend of (a) per-hour OLS on
`[lnV1, lnPREM]` in a ±2.5 log window, residual spread ×0.8, and (b) a
one-factor shape model (median log-ratio curve, per-launch level +
amplitude regressed on `[lnV1, lnPREM]`, amplitude clamped [0, 2]).
Practice 0.1544 (p00 0.122, p01 0.200, p02 0.123, p03 0.173); judge loss
0.154426, rank #181/2,673. The top-10 bar has since moved to ~0.123 and
the top-20 bar to ~0.130, so v1 needed a real ~0.025 improvement, not a
tweak.

## What the data actually looks like

- Log-ratio curves have huge spread (sd up to 2.17). The OLS slope of
  `ln(V_h/V_1)` on lnV1 is strongly negative for late hours (down to
  −0.94): later-hour viewers are almost independent of hour-1 size; the
  level comes mostly from the intercept + lnPREM.
- The four practice cases are outliers, each in a different way: p00's
  ramp `ln(V18/V1) = +2.09` is bigger than almost all comparables; p01's
  +1.15 is above all its neighbours' max (+0.96); p03 has deep troughs
  (h3 −0.84, h4 −0.86, h12 −1.00 — at the extreme low end of its
  neighbours). v1's median errors are systematic: it overpredicts h2–h4
  (−0.25 to −0.31), underpredicts h5–h7 (+0.19 to +0.26), overpredicts
  h11–h16 (−0.11 to −0.40), underpredicts h18 (+0.19).
- Leave-one-out over the 38 comparables is dominated by small launches
  (0.428 for v1); the informative slices are large (lnV1 ≥ 11: 0.225)
  and mega (lnV1 ≥ 11.5: 0.233), because GTA VI is a mega-launch.
- SullyGnome peak/avg ratios are 1.03–1.15 (except one p00 h9 spike):
  the troughs are real viewer behaviour, not sampling artefacts.
- The pre-release diurnal profile is too noisy to be the main signal
  (p00 and p03 have near-identical diurnal shares but very different
  ramps). Last-hours trajectory features correlate only weakly with the
  ramp (max +0.21). Unlock texts are mostly "unverified" — no structured
  US-unlock-hour feature exists.

## The two changes that actually moved the number

### 1. g12 — unlock momentum (the biggest single gain)

`g12 = lnV1 − log(viewers 12 h before release day)`. At release, the
rolling-midnight wave is already underway: how much the category grew in
the 12 hours before midnight tells the model how steep the ramp is.
Adding g12 as a third OLS predictor (and as a shape regressor) took the
practice loss from 0.1544 to 0.1382 in a 50/50 OLS/shape blend, with
LOO-large improving 0.225 → 0.219. It helps p01 most (0.200 → 0.128)
and p02 (0.123 → 0.105).

### 2. Console-only shape + no early-access in the shape libraries

Console-only launches share a shape bias (the console-LARGE LOO shows
the same early-hours pattern as the practice cases: negative h2–h4,
positive h5+; non-console LARGE shows the opposite). Fitting the shape
component on console-only launches and mixing it with the all-launch
shape took the blend to 0.1331. Excluding early-access-contaminated
launches from the shape libraries is principled, not tuned: their
"release day" is really day 3 of early access, so their shape is
distorted; it also improved LOO-large/mega (0.216 → 0.211 / 0.219 →
0.214).

## Final model

- **OLS view**: per hour, ln(viewers) on `[lnV1, lnPREM, g12]`, local
  window ±2.5 in lnV1 (≥10 launches, else whole library), centre
  recentered on the median residual, spread = residual sd × 0.8.
- **Console-shape view**: one-factor shape model on console-only,
  non-early-access launches, spread = per-hour residual sd × 1.0.
- **All-shape view**: same, on all non-early-access launches.
- **Mix**: 50% OLS + 20% console-shape + 30% all-shape (OLS weight 0.6
  inside the console blend, 0.4 inside the all blend, blends mixed
  50/50). All blending is a geometric mean in log space.
- **Extrapolation guard**: the size fed to the regressions is clamped to
  the library's observed lnV1 range plus 0.5 log units of headroom.
  The level anchor stays the true hour-1 print.
- **Fallbacks**: g12 falls back to the library median when the target's
  history has no point ~12 h before release; a per-hour OLS with <8
  rows falls back to the persistence baseline; a shape model with <6
  full curves falls back to the empirical fan; any malformed output row
  falls back to the persistence baseline.

## Results

| metric | v1 | v2 |
| ------ | -- | -- |
| practice overall | 0.1544 | **0.1283** |
| p00 / p01 / p02 / p03 | 0.122 / 0.200 / 0.123 / 0.173 | 0.122 / 0.130 / 0.091 / 0.171 |
| LOO large (lnV1 ≥ 11) | 0.2252 | **0.2113** |
| LOO mega (lnV1 ≥ 11.5) | 0.2332 | **0.2137** |
| LOO all 38 | 0.4283 | 0.4689 |
| LOO console | 0.2905 | 0.3212 |

Practice 0.1283 is below the 0.129 submit bar (the top-10 bar at build
time) but above the ≤0.120 aim. The exact top-10 bar has since moved to
0.123 and the top-20 bar to 0.130, so this entry would sit around the
top-20 edge on practice-equivalent performance — a genuine improvement
over v1's #181, not a prize lock.

## Honest caveats

- **Practice is 4 launches.** The mix-weight tuning (0.127–0.130 across
  neighbouring weights) is at the 4th decimal — that band is noise, not
  signal. The final weights were chosen as the first principled
  structure that crossed below 0.129, not the minimum of a grid.
- **LOO-all and LOO-console are worse than v1's** (0.469 vs 0.428;
  0.321 vs 0.291). Both are dominated by small launches, which GTA VI
  is not; the large/mega slices — the ones that matter for a
  mega-launch — are better. If the final behaves like a small launch,
  v2 could lose to v1; that is not the expected regime.
- **p03 (Spider-Man 2) is still the weak case** (0.171): its deep
  troughs are at the extreme low end of every neighbour set, and no
  feature in the case file predicts them.

## Tried and rejected

- lnCH1 (channels) as a third predictor: practice 0.153, LOO-large
  worse. OLS spread 0.7: 0.154. Shape weight 0.55: 0.154. All three
  combined: 0.152. Kernel-weighted log-log: 0.20–0.23. A "fan"
  (empirical ratio quantiles) alone: 0.254. Peak-anchored model: 0.219.
  Diurnal-profile features: +0.001 at best. Year as a predictor: worse.
  Console indicator inside the OLS: practice worse. 2-D local window
  (lnV1 + lnPREM): 0.130–0.135, LOO-large much worse. Wider spreads:
  help LOO, hurt practice. Three-model ensembles: better LOO-large
  (0.209) but practice 0.143. Tier filters on the OLS: LOO-large better
  but practice worse.
