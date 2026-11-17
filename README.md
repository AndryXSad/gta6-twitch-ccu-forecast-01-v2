# GTA VI launch-day Twitch CCU forecaster — v2

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/AndryXSad/gta6-twitch-ccu-forecast-01-v2/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/AndryXSad/gta6-twitch-ccu-forecast-01-v2/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

A make.fun `gta6-twitch-ccu-forecast-01` entry. It forecasts, for each of
hours 2–24 of Grand Theft Auto VI's release day (2026-11-19 UTC), five
quantiles (5%, 25%, 50%, 75%, 95%) of the concurrent Twitch viewers in the
"Grand Theft Auto VI" category, from the first hour's print and the
launch-day curves of past big game launches shipped inside each case.

## How it works

`main.py` (Python 3.13, standard library only, no network) blends three
views of the same curve in log space (geometric mean of quantiles):

1. **Local OLS** — per hour, least squares of log viewers on
   `[lnV1, lnPREM, g12]` over the comparable launches whose hour-1 size is
   within 2.5 log units of the target's (at least 10 launches, else the
   whole library), centre recentered on the median residual, spread =
   residual sd × 0.8. `g12` is the new "unlock momentum" feature: lnV1
   minus log viewers 12 hours before release day — the rolling-midnight
   wave already underway when the release day starts.
2. **Console shape** — a one-factor shape model (launch-day log-ratio
   curve = level + amplitude × the library's median log-ratio curve)
   fitted on console-only launches only, with early-access-contaminated
   launches excluded (their "release day" is really day 3 of early
   access, so their shape is distorted).
3. **All shape** — the same one-factor shape model fitted on all launches
   except early-access-contaminated ones.

Final mix: 50% OLS + 20% console-shape + 30% all-shape. An extrapolation
guard clamps the size fed to the regressions to the library's observed
lnV1 range plus half a log unit of headroom (the level anchor stays the
true hour-1 print), and any malformed output row falls back to the
persistence baseline.

Full reasoning, the numbers behind every choice, and what was tried and
dropped: [DESIGN.md](DESIGN.md).

## Local results (practice cases, scored with the exact pinball loss from RULES.txt)

| case | launch | loss |
| ---- | ------ | ---- |
| p00 | Marvel's Wolverine (2026-09-15) | 0.122 |
| p01 | Red Dead Redemption 2 (2018-10-26) | 0.130 |
| p02 | God of War Ragnarök (2022-11-09) | 0.091 |
| p03 | Marvel's Spider-Man 2 (2023-10-20) | 0.171 |
| **overall** | | **0.128** |

For reference: the house baseline scores 0.387 on the same cases, and v1
of this entry scored 0.154 (judge loss 0.154426, rank #181). Leave-one-out
over the comparable library: large launches (lnV1 ≥ 11) 0.211, mega
launches (lnV1 ≥ 11.5) 0.214 — both better than v1's 0.225 / 0.233.

## Usage

```sh
MAKEFUN_INPUT_DIR=/input MAKEFUN_OUTPUT_DIR=/output python3 main.py
```

Reads every `*.in` in the input directory, writes `<id>.out` (23 rows,
hours 2–24, five quantiles each) to the output directory. Deterministic,
~0.1 s per case.
