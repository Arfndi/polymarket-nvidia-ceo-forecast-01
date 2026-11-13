# Polymarket NVIDIA CEO forecast — entry

Forecasts the Yes price of every trading market of Polymarket's event
"Next CEO of NVIDIA?" at every minute of the 4 hours after a checkpoint,
as five quantiles [0.05, 0.25, 0.5, 0.75, 0.95] per market per minute.
Python 3.13, standard library only, no network, deterministic.

## How it works

For each market, from its own 72 hours of 1-minute Yes prices up to the
checkpoint:

**Spread — robust per-market volatility.** Prices are step-like: only
12.2% of 1-minute returns are nonzero, and the return distribution is
dominated by rare jumps (one market moved 0.3535 → 0.59 in a minute).
Variance-based volatility estimates are dominated by those jumps and come
out far too wide. Instead sigma is the **mean absolute 1-minute return**,
blended 50/50 over a short window (240 min) and a long window (1440 min),
divided by 0.7979 (E|r| for a normal), times 0.80, floored at 0.0002 so a
dead market still gets some spread. Spread at horizon h is
`sigma * sqrt(h)`.

**Median — asymmetric mean reversion plus cross-market deflation.**
Two drift terms, both growing like `h / (h + 12)`:

- Up-spike reversion: `-0.45 * max(price - price 60 min ago, 0)`.
  Up-spikes revert hard — the conditional median of the next-240-minute
  move after a 60-minute rise over 0.10 is about −0.20, and the pooled
  regression slope of the next-240m move on the past-60m return is about
  −0.30, stable across all six practice cases. Down-moves get **no**
  reversion term: crashes persist (a symmetric drift scored worse).
- Cross-market sum: `-0.30 * (S − S_mean) * (x / S)`, where S is the sum
  of the 24 Yes prices at the checkpoint and S_mean its mean over the
  last 240 minutes. When the total sits above its recent norm the prices
  drift down, pro-rata by market size.

**Quantiles.** `median + z_tau * spread` with
`z = [-1.644854, -0.5, 0, 0.5, 1.644854]` — the interquartile z is
narrowed from the normal 0.674 to 0.5 (the middle of the move
distribution is tighter than normal; the 5%/95% z stay normal).
Clamped to [0, 1], non-decreasing per row, rounded to 6 decimals.

## Backtest (practice, 6 cases)

Ground truth for p00–p04 is the next case's input (each case's 240
forecast minutes are inside the next case's history); p05's answers were
fetched from Polymarket's public CLOB price history (`prices-history`,
fidelity 1) and forward-filled onto the 1-minute grid the same way the
house builds it. Mean pinball loss in percentage points:

| case | this entry | house baseline |
|------|-----------|----------------|
| p00  | 0.4476    | 0.5361         |
| p01  | 0.3072    | 0.3804         |
| p02  | 0.3292    | 0.4084         |
| p03  | 0.2569    | 0.3686         |
| p04  | 0.1727    | 0.2988         |
| p05  | 0.0982    | 0.2382         |
| **mean** | **0.2686** | **0.3718** |

(The house's stated practice loss for the baseline is 0.363589; my local
reproduction is 0.3718 — the small gap is my p05 truth fetched from the
live CLOB rather than the house recorder's grid. The comparison above
uses the same ground truth for both, so it is apples-to-apples.)

Median error 0.28–1.36 points per case; 90% coverage 0.85–0.97
(nominal 0.90). Runtime ~0.08 s per case (limit 8 s); two runs produce
byte-identical output; outputs 215–293 KB (limit 1 MiB).

## Ideas the backtest rejected

- **Variance / EWMA volatility** (jump-dominated, intervals far too
  wide): mean loss 0.63 vs 0.40 baseline on 5 cases. Coverage ~1.00.
- **Empirical quantiles of past h-step changes per market**
  (unconditional tails dominated by old regime jumps): 0.43 vs 0.32.
- **Symmetric mean-reversion drift** (reverting down-moves too):
  0.337 vs 0.323 for the asymmetric version.
- **Cross-market sum with a large coefficient** (0.6–1.0): hurts;
  0.30 helps slightly (0.2710 → 0.2685).
- Per-market empirical tails are asymmetric in the pooled data (q05 of
  the 240-minute change is −0.283 vs q95 +0.075), but that is a pooling
  artefact of a few volatile markets; per-market the symmetric-z form
  with a narrowed interquartile range scored best.

## Running it

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads every `*.in` in the input directory and writes
`<id>.out` per case: `{"forecasts": [{"id": <conditionId>, "q": [[5 numbers] x 240]}]}`.

## License

MIT, copyright Arfndi (see LICENSE).
