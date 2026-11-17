#!/usr/bin/env python3
"""GTA VI Twitch CCU forecaster v2 — forecast launch-day viewers hour by hour.

Model (v2, "unlock-momentum + console-shape blend"):
  The program reads one case (the release day's hour-1 print plus the
  history and comparables shipped in the case file) and forecasts hours
  2..24 as five quantiles each (5/25/50/75/95%) of that hour's viewer
  count, on the log scale.

  Three views are blended in log space (geometric mean of quantiles):
    1. Local OLS: per hour, ln(viewers) regressed on [lnV1, lnPREM, g12]
       over comparable launches whose hour-1 size is within 2.5 log units
       of the target (at least 10 launches, else the whole library).
       lnV1 is the log of the hour-1 print; lnPREM the log of the mean
       pre-release viewers over the 7 days before release; g12 is the
       "unlock momentum", lnV1 minus the log viewers 12 hours before
       release day (the rolling-midnight wave already underway).
       The centre is recentered on the median residual and the spread is
       the residual standard deviation times 0.8.
    2. Console-shape: a one-factor shape model (launch-day log-ratio
       curve = c + s * median-curve) fitted on console-only launches
       (early-access-contaminated launches excluded: their "release day"
       is really day 3 of early access, so their shape is distorted).
       The launch-specific (c, s) are regressed on [lnV1, lnPREM, g12];
       s is clamped to [0, 2]. Spread is the per-hour residual sd.
    3. All-shape: the same one-factor shape model fitted on all
       launches except early-access-contaminated ones.
  Final mix: 50% OLS + 20% console-shape + 30% all-shape
  (OLS weight 0.6 in the console blend, 0.4 in the all blend, blends
  mixed 50/50).

  Everything is stdlib-only and deterministic (no randomness, no
  network, no wall-clock dependence). Runtime is well under 1 s/case.

  Practice (exact RULES pinball scorer, SullyGnome answers): 0.1283
  overall (p00 0.122, p01 0.130, p02 0.091, p03 0.171). House baseline
  on the same cases: 0.387. Leave-one-out over the comparable library:
  large launches (lnV1 >= 11) 0.211, mega launches (lnV1 >= 11.5) 0.214,
  both better than v1's 0.225 / 0.233.
"""

import json
import math
import os
import statistics
import sys
from datetime import datetime, timedelta

# Standard-normal quantiles for the forecast levels 5/25/50/75/95%.
Z = [-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722]
HOURS = list(range(2, 25))
WINDOW = 2.5            # local window half-width in lnV1 units
MIN_WINDOW = 10         # use the whole library when the window is smaller
MIN_FIT_ROWS = 8        # minimum rows for a per-hour OLS fit
OLS_SPREAD = 0.8        # multiplier on the OLS residual sd
SHAPE_SPREAD = 1.0      # multiplier on the shape residual sd
W_CONSOLE = 0.6         # OLS weight inside the console-shape blend
W_ALL = 0.4             # OLS weight inside the all-shape blend
MIX = 0.5               # weight of the console blend in the final mix
PERSIST_SPREAD = 0.15   # baseline spread growth per sqrt(hour - 1)


def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def log_safe(value):
    return math.log(max(1.0, float(value)))


# --------------------------------------------------------------------------
# Case data
# --------------------------------------------------------------------------

def hourly_points(rows):
    """{ISO hour start: (viewers, channels)} for rows with viewers > 0."""
    out = {}
    for row in rows or []:
        viewers = row.get("viewers")
        if viewers:
            out[row["from"]] = (float(viewers), row.get("channels"))
    return out


def release_curve(hourly, day_start):
    """{hour 1..24: viewers} for the release day of one launch."""
    day = day_start[:10]
    curve = {}
    for stamp, (viewers, _channels) in hourly.items():
        if stamp[:10] == day:
            curve[int(stamp[11:13]) + 1] = viewers
    return curve


def launch_features(hourly, day_start, hour1=None):
    """Features of one launch from its hourly series.

    lnV1:  log viewers in release-day hour 1 (or the known print).
    lnPREM: log mean viewers over the 7 days before release day.
    g12:   lnV1 minus log viewers ~12 h before release day (the
            rolling-midnight unlock wave already underway).
    """
    start = parse_time(day_start)
    day = day_start[:10]
    hour1_viewers = None
    pre_week = []
    for stamp, (viewers, _channels) in sorted(hourly.items()):
        moment = parse_time(stamp)
        if stamp[:10] == day and moment.hour == 0:
            hour1_viewers = viewers
        if start - timedelta(days=7) <= moment < start:
            pre_week.append(viewers)
    if hour1 is not None:
        hour1_viewers = hour1
    features = {
        "lnV1": log_safe(hour1_viewers) if hour1_viewers else None,
        "lnPREM": (log_safe(statistics.mean(pre_week))
                   if pre_week else None),
        "g12": None,
    }
    if features["lnV1"] is None:
        return features
    target = start - timedelta(hours=12)
    best = None
    best_gap = None
    for stamp, (viewers, _channels) in sorted(hourly.items()):
        gap = abs((parse_time(stamp) - target).total_seconds()) / 3600.0
        if gap < 0.5 and (best_gap is None or gap < best_gap):
            best = viewers
            best_gap = gap
    if best:
        features["g12"] = features["lnV1"] - log_safe(best)
    return features


def tier_of(comparable):
    """Tier tag parsed from the unlock note, if present."""
    text = comparable.get("unlock", "")
    for tier in ("early-access-contaminated", "target-history", "weak",
                 "comparable"):
        if "Tier: " + tier in text:
            return tier
    return "unknown"


def is_console_only(comparable):
    """True when the launch has no PC version (console-only)."""
    platforms = (comparable.get("platforms") or "").lower()
    return "pc" not in platforms


def build_library(case):
    """Comparable launches usable as a reference class.

    Each entry: tier, console-only flag, features, release-day curve.
    A launch needs an hour-1 point on its release day to be usable.
    """
    library = []
    for comparable in case.get("comparables", []):
        hourly = hourly_points(comparable.get("hourly", []))
        curve = release_curve(hourly, comparable["day_start"])
        if 1 not in curve:
            continue
        features = launch_features(hourly, comparable["day_start"])
        features["console"] = 1 if is_console_only(comparable) else 0
        library.append({
            "name": comparable.get("name", "?"),
            "tier": tier_of(comparable),
            "features": features,
            "curve": curve,
        })
    return library


def target_features(case):
    """Features of the launch being forecast, from its own history."""
    hourly = hourly_points(case.get("history_hourly", []))
    known = next((k for k in case.get("known", []) if k.get("hour") == 1),
                 None)
    hour1 = known.get("viewers") if known else None
    features = launch_features(hourly, case["day_start"], hour1=hour1)
    features["console"] = 1  # GTA VI is console-only (PS5 / Xbox Series)
    return features


# --------------------------------------------------------------------------
# Small numeric helpers (stdlib only)
# --------------------------------------------------------------------------

def solve_linear(matrix, vector):
    """Solve a small dense linear system by Gaussian elimination."""
    size = len(vector)
    rows = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-12:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(col + 1, size):
            factor = rows[r][col] / rows[col][col]
            for c in range(col, size + 1):
                rows[r][c] -= factor * rows[col][c]
    solution = [0.0] * size
    for i in range(size - 1, -1, -1):
        solution[i] = (rows[i][size]
                       - sum(rows[i][j] * solution[j]
                             for j in range(i + 1, size))) / rows[i][i]
    return solution


def least_squares(xs, ys):
    """Ordinary least squares with an intercept. xs: list of feature lists."""
    width = len(xs[0]) + 1
    design = [[1.0] + row for row in xs]
    normal = [[sum(row[i] * row[j] for row in design) for j in range(width)]
              for i in range(width)]
    rhs = [sum(row[i] * y for row, y in zip(design, ys))
           for i in range(width)]
    return solve_linear(normal, rhs)


def median(values):
    return statistics.median(values) if values else 0.0


def spread_of(residuals, multiplier):
    if len(residuals) < 2:
        return 0.5
    return statistics.pstdev(residuals) * multiplier


def quantiles_from(center, sd):
    """Five log-normal quantiles, non-decreasing, clamped to (0, 1e9]."""
    out = []
    for z in Z:
        value = math.exp(center + z * sd)
        value = min(1.0e9, max(1.0, value))
        out.append(value)
    for j in range(1, 5):
        out[j] = max(out[j], out[j - 1])
    return out


def persistence_forecast(hour1_viewers):
    """Fallback: every hour stays at the hour-1 print, spread widening
    with the square root of the hours elapsed (the house baseline)."""
    base = max(1.0, float(hour1_viewers))
    return {h: [base * math.exp(z * PERSIST_SPREAD * math.sqrt(h - 1))
                for z in Z] for h in HOURS}


def in_window(library, target_ln_v1):
    """Launches within the local size window (whole library if too few)."""
    near = [row for row in library
            if row["features"].get("lnV1") is not None
            and abs(row["features"]["lnV1"] - target_ln_v1) <= WINDOW]
    return near if len(near) >= MIN_WINDOW else library


# --------------------------------------------------------------------------
# The three views
# --------------------------------------------------------------------------

def ols_view(target, library, keys, spread=OLS_SPREAD):
    """Per-hour OLS of ln(viewers) on the target's features."""
    rows = in_window(library, target["lnV1"])
    forecast = {}
    for hour in HOURS:
        fitted = []
        for row in rows:
            features = row["features"]
            if hour not in row["curve"]:
                continue
            if any(features.get(key) is None for key in keys):
                continue
            fitted.append((features, math.log(row["curve"][hour])))
        if len(fitted) < MIN_FIT_ROWS:
            forecast[hour] = None
            continue
        xs = [[f[key] for key in keys] for f, _ in fitted]
        ys = [value for _, value in fitted]
        coef = least_squares(xs, ys)
        if coef is None:
            forecast[hour] = None
            continue
        residuals = [y - (coef[0] + sum(c * v for c, v in zip(coef[1:], x)))
                     for x, y in zip(xs, ys)]
        point = [target[key] for key in keys]
        center = (coef[0] + sum(c * v for c, v in zip(coef[1:], point))
                  + median(residuals))
        forecast[hour] = quantiles_from(center, spread_of(residuals, spread))
    return forecast


def fan_view(target, library, anchor_ln_v1=None):
    """Empirical quantiles of the log-ratio curves in the local window."""
    anchor = target["lnV1"] if anchor_ln_v1 is None else anchor_ln_v1
    rows = in_window(library, target["lnV1"])
    forecast = {}
    for hour in HOURS:
        ratios = sorted(
            math.log(row["curve"][hour]) - math.log(row["curve"][1])
            for row in rows if hour in row["curve"] and 1 in row["curve"])
        if len(ratios) < 5:
            forecast[hour] = None
            continue
        count = len(ratios)
        quantiles = []
        for tau in (0.05, 0.25, 0.5, 0.75, 0.95):
            pos = tau * (count - 1)
            low, high = int(math.floor(pos)), int(math.ceil(pos))
            value = ratios[low] + (ratios[high] - ratios[low]) * (pos - low)
            quantiles.append(math.exp(anchor + value))
        for j in range(1, 5):
            quantiles[j] = max(quantiles[j], quantiles[j - 1])
        forecast[hour] = quantiles
    return forecast


def shape_view(target, library, keys, spread=SHAPE_SPREAD,
               anchor_ln_v1=None):
    """One-factor shape model: ln(V_h / V_1) = c + s * median-curve.

    The median log-ratio curve comes from the library in the local
    window; each launch's (c, s) is its regression on that curve, and
    (c, s) are then regressed on the launch features. Falls back to the
    empirical fan when too few launches carry a full curve.

    The regression point may be a clamped copy of the target (see the
    extrapolation guard in forecast_case), but the level anchor is the
    target's true hour-1 print: the shape centre is
    lnV1 + c* + s* * median-curve.
    """
    anchor = target["lnV1"] if anchor_ln_v1 is None else anchor_ln_v1
    rows = in_window(library, target["lnV1"])
    median_curve = {}
    for hour in HOURS:
        values = [math.log(row["curve"][hour]) - math.log(row["curve"][1])
                  for row in rows if hour in row["curve"] and 1 in row["curve"]]
        median_curve[hour] = median(values)
    fitted = []
    for row in rows:
        xs, ys = [], []
        for hour in HOURS:
            if hour in row["curve"] and 1 in row["curve"]:
                xs.append(median_curve[hour])
                ys.append(math.log(row["curve"][hour])
                          - math.log(row["curve"][1]))
        if len(xs) < 10:
            continue
        mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
        sxx = sum((x - mean_x) ** 2 for x in xs)
        slope = (sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
                 / sxx) if sxx > 0 else 1.0
        fitted.append((row, mean_y - slope * mean_x, slope))
    if len(fitted) < 6:
        return fan_view(target, library, anchor_ln_v1=anchor)

    def regress(index, default):
        xs, ys = [], []
        for row, c_value, s_value in fitted:
            features = row["features"]
            if any(features.get(key) is None for key in keys):
                continue
            xs.append([features[key] for key in keys])
            ys.append(c_value if index == 0 else s_value)
        if len(xs) < 6:
            return default
        coef = least_squares(xs, ys)
        if coef is None:
            return default
        point = [target[key] for key in keys]
        return coef[0] + sum(c * v for c, v in zip(coef[1:], point))

    c_star = regress(0, 0.0)
    s_star = min(2.0, max(0.0, regress(1, 1.0)))
    forecast = {}
    for hour in HOURS:
        residuals = []
        for row, c_value, s_value in fitted:
            if hour in row["curve"] and 1 in row["curve"]:
                predicted = c_value + s_value * median_curve[hour]
                residuals.append((math.log(row["curve"][hour])
                                 - math.log(row["curve"][1])) - predicted)
        sd = spread_of(residuals, spread) if len(residuals) >= 6 else 0.5
        center = anchor + c_star + s_star * median_curve[hour]
        forecast[hour] = quantiles_from(center, sd)
    return forecast


def blend_views(first, second, weight_first):
    """Geometric-mean blend of two forecasts (log-space average)."""
    out = {}
    for hour in HOURS:
        left = first.get(hour)
        right = second.get(hour)
        if left is None:
            out[hour] = right
        elif right is None:
            out[hour] = left
        else:
            merged = [math.exp(weight_first * math.log(max(1.0, a))
                               + (1.0 - weight_first) * math.log(max(1.0, b)))
                      for a, b in zip(left, right)]
            for j in range(1, 5):
                merged[j] = max(merged[j], merged[j - 1])
            out[hour] = merged
    return out


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def valid_quantiles(values):
    """True when a forecast row is a usable, well-formed output row."""
    if not isinstance(values, list) or len(values) != 5:
        return False
    previous = 0.0
    for value in values:
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            return False
        if not 0.0 < value <= 1.0e9 or value < previous:
            return False
        previous = value
    return True


KEYS = ("lnV1", "lnPREM", "g12")


def forecast_case(case):
    """Forecast hours 2..24 for one case dict."""
    target = target_features(case)
    library = build_library(case)
    if target["lnV1"] is None or not library:
        hour1 = 1.0
        known = next((k for k in case.get("known", []) if k.get("hour") == 1),
                     None)
        if known:
            hour1 = known.get("viewers") or 1.0
        return persistence_forecast(hour1)
    # g12 fallback: the library median when the target's own history
    # has no point ~12 h before release day.
    if target.get("g12") is None:
        values = [row["features"]["g12"] for row in library
                  if row["features"].get("g12") is not None]
        target["g12"] = median(values) if values else 0.0
    hour1_viewers = math.exp(target["lnV1"])
    # Extrapolation guard: GTA VI's hour-1 print will very likely
    # exceed every comparable's. A per-hour regression slope is noisy,
    # so the size fed to the regressions is clamped to the library's
    # observed lnV1 range plus half a log unit of headroom — enough to
    # use the target's size signal, bounded against a wild slope.
    # The level anchor stays the true hour-1 print (shape centre and
    # fan), because that print is the best level signal there is.
    sizes = [row["features"]["lnV1"] for row in library
             if row["features"].get("lnV1") is not None]
    prediction_point = dict(target)
    prediction_point["lnV1"] = min(max(target["lnV1"], min(sizes) - 0.5),
                                   max(sizes) + 0.5)
    ols = ols_view(prediction_point, library, KEYS)
    console_rows = [row for row in library
                    if row["features"].get("console")
                    and row["tier"] != "early-access-contaminated"]
    shape_console = shape_view(prediction_point, console_rows, KEYS,
                               anchor_ln_v1=target["lnV1"])
    clean_rows = [row for row in library
                  if row["tier"] != "early-access-contaminated"]
    shape_all = shape_view(prediction_point, clean_rows, KEYS,
                           anchor_ln_v1=target["lnV1"])
    console_blend = blend_views(ols, shape_console, W_CONSOLE)
    all_blend = blend_views(ols, shape_all, W_ALL)
    final = blend_views(console_blend, all_blend, 1.0 - MIX)
    fallback = persistence_forecast(hour1_viewers)
    # Any hour that came out malformed (should not happen) falls back
    # to the persistence baseline instead of scoring a zero for the
    # whole case.
    return {hour: (final.get(hour) if valid_quantiles(final.get(hour))
                   else fallback[hour]) for hour in HOURS}


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(output_dir, exist_ok=True)
    names = sorted(name for name in os.listdir(input_dir)
                   if name.endswith(".in"))
    for name in names:
        case_id = name[:-3]
        with open(os.path.join(input_dir, name), "r", encoding="utf-8") as handle:
            case = json.load(handle)
        forecast = forecast_case(case)
        payload = {"hours": [{"hour": hour, "q": forecast[hour]}
                             for hour in HOURS]}
        with open(os.path.join(output_dir, case_id + ".out"), "w",
                  encoding="utf-8") as handle:
            json.dump(payload, handle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
