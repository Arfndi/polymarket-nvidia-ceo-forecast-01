# polymarket-nvidia-ceo-forecast-01 entry: per-market adaptive forecaster.
#
# Model (all constants tuned on the 6-case practice backtest, ground truth =
# the next case's prices, plus p05's answers fetched from Polymarket's public
# price history; see README.md):
#
#   * Spread: each market's own volatility, estimated ROBUSTLY as the mean
#     absolute 1-minute return (prices are step-like: 88% of minutes do not
#     move at all, so variance-based estimates are dominated by rare jumps
#     and come out far too wide). Blend of a short window (240 min) and a
#     long window (1440 min), divided by 0.7979 (E|r| for a normal), times
#     0.80, floored at 0.0002 so a dead market still gets some spread.
#     Spread at horizon h is sigma * sqrt(h).
#   * Median: last price plus drift. Two mean-reversion terms, both growing
#     like h / (h + 12):
#       - up-spike reversion: -0.45 * max(price - price 60 min ago, 0).
#         Up-spikes revert hard (conditional median after a >0.10 rise in
#         60 min is about -0.20 over the next 4 h); crashes down persist,
#         so down-moves get NO reversion term (a symmetric drift scored
#         worse in the backtest).
#       - cross-market sum: -0.30 * (S - S_mean) * (x / S), where S is the
#         sum of the 24 Yes prices at the checkpoint and S_mean its mean
#         over the last 240 min. When the total is above its recent norm
#         the prices drift down, pro-rata by market size.
#   * Quantiles: median + z_tau * spread with z = [-1.644854, -0.5, 0,
#     0.5, 1.644854]. The interquartile z is narrowed from the normal
#     0.674 to 0.5 (the middle of the move distribution is tighter than
#     normal; the 5%/95% z stay normal), clamped to [0, 1], non-decreasing,
#     rounded to 6 decimals.
#
# Rejected by the backtest (kept out deliberately):
#   * variance / EWMA volatility (jump-dominated, intervals far too wide:
#     mean loss 0.63 vs 0.40 baseline on 5 cases);
#   * empirical quantiles of past h-step changes per market (unconditional
#     tails dominated by old regime jumps: 0.43 vs 0.32);
#   * symmetric mean-reversion drift (0.337 vs 0.323);
#   * cross-market sum with a large coefficient (0.6-1.0 hurts).
#
# Pure stdlib, deterministic (no randomness, no dict-order dependence),
# no network. Reads every *.in in $MAKEFUN_INPUT_DIR (else /input/) and
# writes /output/<id>.out (or $MAKEFUN_OUTPUT_DIR).

import json
import math
import os

INPUT_DIR = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
OUTPUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")

QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]
# Normal 5%/95% z, narrowed interquartile z (see header).
Z = [-1.644854, -0.5, 0.0, 0.5, 1.644854]

SIGMA_FLOOR = 0.0002
SIGMA_MULT = 0.80
# Mean |N(0, sigma)| = sigma * sqrt(2/pi) = sigma * 0.79788456.
MEANABS_TO_SIGMA = 1.0 / 0.79788456

A_UP = 0.45      # up-spike reversion coefficient
SUM_COEF = 0.30  # cross-market sum-deflation coefficient


def price6(x):
    """Clamp to [0, 1] and round to 6 decimals (0, never -0)."""
    return round(min(1.0, max(0.0, x)) * 1e6) / 1e6 + 0.0


def mean_abs_return(prices, window):
    """Mean absolute 1-minute return over the last `window` minutes."""
    n = len(prices)
    if n < 2:
        return 0.0
    start = max(0, n - window - 1)
    total = 0.0
    count = 0
    for i in range(start, n - 1):
        total += abs(prices[i + 1] - prices[i])
        count += 1
    return total / count if count else 0.0


def market_sigma(prices):
    """Per-market 1-minute volatility from robust mean absolute returns."""
    short = mean_abs_return(prices, 240)
    long_ = mean_abs_return(prices, 1440)
    sigma = (0.5 * short + 0.5 * long_) * MEANABS_TO_SIGMA * SIGMA_MULT
    if sigma < SIGMA_FLOOR:
        sigma = SIGMA_FLOOR
    return sigma


def forecast_market(prices, horizon, sum_dev, sum_total):
    """240 rows x 5 quantiles for one market.

    sum_dev: S - S_mean for this case (0 if unknown); sum_total: S.
    """
    x = prices[-1]
    n = len(prices)
    up = x - prices[max(0, n - 61)]
    if up < 0.0:
        up = 0.0
    share = (x / sum_total) if sum_total > 0.0 else 0.0
    sigma = market_sigma(prices)
    rows = []
    for h in range(1, horizon + 1):
        f = h / (h + 12.0)
        med = x - A_UP * f * up - SUM_COEF * f * sum_dev * share
        s = sigma * math.sqrt(h)
        row = [price6(med + z * s) for z in Z]
        for j in range(1, 5):
            if row[j] < row[j - 1]:
                row[j] = row[j - 1]
        rows.append(row)
    return rows


def case_sum_stats(markets):
    """S = sum of last prices; S_mean = its mean over the last 240 min."""
    total = 0.0
    for m in markets:
        total += m["prices"][-1]
    shortest = min(len(m["prices"]) for m in markets)
    window = shortest if shortest < 240 else 240
    s_sum = 0.0
    for lag in range(window):
        s_sum += sum(m["prices"][-1 - lag] for m in markets)
    mean = s_sum / window if window else total
    return total, total - mean


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    inputs = sorted(f for f in os.listdir(INPUT_DIR) if f.endswith(".in"))
    for fname in inputs:
        cid = fname[: -len(".in")]
        with open(os.path.join(INPUT_DIR, fname), "r", encoding="utf-8") as fh:
            case = json.load(fh)
        horizon = case["horizon_minutes"]
        total, dev = case_sum_stats(case["markets"])
        forecasts = []
        for m in case["markets"]:
            forecasts.append(
                {
                    "id": m["id"],
                    "q": forecast_market(m["prices"], horizon, dev, total),
                }
            )
        out_path = os.path.join(OUTPUT_DIR, cid + ".out")
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"forecasts": forecasts}) + "\n")


if __name__ == "__main__":
    main()
