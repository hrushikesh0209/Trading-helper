# Screener backtest report (21 October 2026)

How the screener's rules were chosen, and the evidence for and against them.
Reproduce with `backtest_screener.py`, `backtest_screener.py --v2` and `factor_ic.py`.

## Method

- **Data:** today's Nifty 500 (495 stocks), daily prices Oct 2021 to Oct 2026, split-adjusted; stocks with a flagged data jump are skipped while it is in the lookback.
- **Signals:** every 5 trading days. Train: Dec 2022 to Mar 2025 (112 dates). Test: Apr 2025 to Sep 2026 (73 dates).
- **Trades:** the regime's pick count per date (10 / 6 / 3); entry at the next day's open; a day that touches both stop and target counts as a stop; gaps fill at the open; 0.25% round-trip costs.
- **Bar to beat:** the median eligible stock over the same windows (train +0.49%, test −0.14% per 15 days).

## Formula verification

18 indicators matched TA-Lib to floating-point precision over the last 250 bars of RELIANCE, TCS and HDFCBANK:
SMA, EMA, WMA, RSI, ATR, MACD and signal, +DI, −DI, ADX, Bollinger upper and lower, Stochastic %K and %D, CCI,
Williams %R, Ultimate Oscillator and Momentum. Supertrend (no TA-Lib version) passed its consistency checks.
One apparent Bollinger failure was a bug in the test (TA-Lib returns the bands upper-first), not in the formula.

## Results

| Config | Train trades | Train PF | Train avg | Test trades | Test PF | Test avg | Test alpha |
|---|---|---|---|---|---|---|---|
| v1 playbook (all setups, fixed stop and target) | 718 | 1.18 | +0.51% | 339 | 0.91 | −0.27% | +0.13% |
| Momentum score, v1 exits | 717 | 1.24 | +0.69% | 340 | 0.97 | −0.08% | +0.38% |
| **v2: momentum, 2 ATR stop trailing 2 ATR** (adopted) | 715 | **1.41** | +1.33% | 340 | **1.13** | +0.39% | +0.83% |
| Momentum, 3 ATR stop trailing 3 ATR | 708 | 1.41 | +1.48% | 339 | 1.02 | +0.07% | +0.52% |
| Momentum, pullback entry (rejected: overfit) | 667 | 1.61 | +2.02% | 322 | 0.96 | −0.11% | +0.53% |

PF = gross gains / gross losses; alpha = trade return minus the Nifty 50 over the same days.
The 12 v1 tweaks (wider or tighter stops, 2R or 4R targets, heavier RS or sector weights, no TV rating, setup subsets,
sector caps) all stayed between PF 0.85 and 0.98 on the test period.

**v2 by year:** 2023 PF 2.47, 2024 0.81, 2025 0.73, 2026 1.40; all years 1.34; at 0.5% costs 1.25.
Momentum earns in trends and gives some back in corrections (late 2024 to 2025). Expect losing years.

## Factor study (forward 15-day rank IC, all eligible stocks)

| Factor | Train IC (t) | Test IC (t) | Used in v2 |
|---|---|---|---|
| 12-month return skipping the last month | 0.025 (1.7) | 0.064 (4.7) | 35% |
| Nearness to 52-week high | 0.019 (1.8) | 0.044 (2.2) | 25% |
| RS percentile (3–12 month) | 0.026 (1.7) | 0.032 (2.0) | 20% |
| Above SMA200 | 0.021 (1.5) | 0.023 (1.4) | 10% |
| Sector strength | 0.034 (2.8) | −0.014 (−1.0) | 10% (unstable) |
| TV Technical Rating, RSI, volume ratio | ≈ 0.00 | ≈ 0.00 | no |
| OBV slope, up/down volume, tight base, low volatility | negative | negative | no |

Weights follow the training-period evidence and published momentum research (for example NSE's Nifty200 Momentum 30
index). Because the test IC was also seen, the test period is no longer fully unseen: forward tracking of live picks
(Phase 4) is the real check.

## Market regime

Regime buckets flipped between periods (risk-on train PF 1.93, test 0.67; risk-off 0.56 and 1.62), so regime is not
used to time entries beyond the existing pick counts. Breadth above 60% (share of stocks above SMA50) was positive in
both periods (1.65 and 1.24), so it sets position size: risk 1% of capital per trade above 60% breadth, 0.5% otherwise.

## Positional (up to 60 trading days, 10 picks)

| Setting | Train PF | Test PF |
|---|---|---|
| 3 ATR stop, trail 3 ATR, hold ≤ 60 (adopted, provisional) | 1.51 | 1.74 |
| 3.5 ATR stop, trail 4 ATR, hold ≤ 60 | 1.55 | 1.13 |
| 3.5 ATR stop, trail 4 ATR, hold ≤ 120 | 1.79 | 0.95 |

The training-best setting failed on test; the adopted one is the only setting profitable in both, chosen after seeing
both, so treat it as provisional until forward tracking confirms it.

## Targets (half booked at a target, the rest trailed)

| Exit plan | Swing PF train / test | Positional PF train / test | Target reached |
|---|---|---|---|
| Trailing stop only | 1.41 / 1.14 | 1.51 / 1.74 | — |
| Half at 2R, trail the rest | 1.37 / 1.11 | 1.42 / 1.68 | 18–26% of trades |
| Half at 3R, trail the rest | 1.38 / 1.12 | 1.51 / 1.70 | 7–14% |
| Half at 1.5R, trail the rest | 1.32 / 1.07 | 1.37 / 1.60 | 25–35% |

Trailing everything earns slightly more, but half at 2R costs little and locks gains, so picks show Target 1 (2R),
Target 2 (3R) and the trailing rule, and the user chooses.

## Technical levels (support / resistance) vs ATR

`levels.py`: stop 0.5 ATR below the highest support at least 1 ATR under entry (confirmed swing lows, EMA20, SMA50,
prior week's pivot S1/S2, breakout level), 2 ATR fallback, 10% cap. T1 / T2 at the next resistances at least 1.5R up
(swing highs, 52-week high, weekly R1/R2, Fibonacci 1.272 / 1.618 extensions near highs), 2R / 3R with no overhead.
Same picks and dates (`backtest_screener.py --levels`):

| Exit plan | Train PF | Test PF | Win % train / test |
|---|---|---|---|
| ATR stop 2x, trail 2 ATR | 1.41 | 1.13 | 42.9 / 37.1 |
| **Technical stop, trail 2 ATR** (adopted) | 1.41 | 1.14 | 42.7 / 36.9 |
| Technical stop, half at technical T1, trail the rest | 1.38 | 1.09 | 43.5 / 37.2 |
| ATR stop, half at technical T1, trail the rest | 1.38 | 1.09 | 43.8 / 37.4 |
| Technical stop, half at T1, rest at T2 | 1.37 | 1.08 | 43.5 / 37.2 |
| Technical stop, all out at T1 | 1.40 | 1.08 | 49.8 / 43.7 |

Technical stops match ATR stops and can be shown on a chart, so they replace them. Targets sit on named resistance;
trailing everything still edges booking at T1, while selling all at T1 raises the win rate by about 7 points for a
similar profit factor, so the choice is left to the user.

## Chart and candlestick patterns (`pattern_study.py`)

100,254 look-ahead-free events from 495 stocks: 10 chart patterns read from a 2-ATR zigzag, and 12 TA-Lib candles.
Each event's 15-day return is compared like for like with the same day's stocks (mean with mean, median with median).
An earlier mean-vs-median comparison made every pattern look good, bearish ones included, and was discarded.

- **No pattern predicts in its expected direction in both periods.** Chart patterns run from −1.2% to +0.9% excess,
  most with |t| < 2. Every candle is within ±0.3%, with signs that flip between periods.
- **Inverse head & shoulders did the opposite** of the textbook: −0.37% train (t −1.6), −1.23% test (t −4.7).
- **Bullish patterns below SMA200 lost in both periods** (chart −0.46% / −0.50%; at support −0.97% / −0.83%), which
  supports the screener's existing rule of buying above SMA200 only.
- **Measured-move targets reached first within 20 days:** double bottom 32% / 30%, ascending triangle 35% / 26%,
  inverse H&S 29% / 18%, bull flag 21% / 12%, falling wedge 8% / 10%.

**Use:** patterns are context and target candidates, never buy or sell signals.

## Level calibration and adaptive targets (`calibrate_levels.py`, training period only)

29,846 eligible uptrend stock-days. Each level type's 20-day outcome was compared with an ordinary price at the same
ATR distance, separately for stocks at their 52-week high and below it.

- **Supports:** no type (swing low, EMA20, SMA50, pivots, breakout level, pattern low) held more than about 3 points
  better than an ordinary price at the same distance. A stop's distance matters, not the line it sits on.
- **Resistances:** Fibonacci 1.272 was reached 5–9 points more often than baseline at 3–4 ATR; measured moves about
  6 points more at around 5 ATR (at highs); swing highs and pivot R1 were reached slightly less often (price stalls).
- **Adaptive choice:** stop = the support type that beat its baseline by at least 2 points, else fixed. T1 / T2 = the
  resistance with the highest hit rate × distance in R.

| Exit plan | Fixed train / test PF | Adaptive train / test PF |
|---|---|---|
| Stop + trail 2 ATR | 1.41 / 1.14 | 1.40 / 1.13 |
| Half at T1, trail the rest | 1.38 / 1.09 | 1.38 / 1.07 |
| All out at T1 | 1.41 / 1.08 | **1.44 / 1.10** (test alpha +0.98% vs +0.79%) |
| Half T1, rest T2 | 1.37 / 1.07 | 1.35 / 1.05 |

**Adopted:** fixed technical stops and adaptive targets, each with its historical hit rate shown. The gain is small;
recalibrate when a year of new data is in.

## Review 2026-10-22: why zero picks, and the risk-off sector rule (`diagnose.py`)

- **Data and code:** all 495 stocks had the day's bar; regime and sector RS recomputed independently matched the code exactly.
- **Funnel:** 495 → 418 after data, liquidity and price checks → **211 after "below falling SMA200"** (the market: 69% of
  stocks below SMA200) → 52 with setup A/E → 39 with a stop within 10% → **1 after the risk-off sector rule**
  (Leading/Improving = IT and Telecom only). The rule cut LAURUSLABS (score 96.7), DIVISLAB, GLAND and IPCALAB, in
  Healthcare, a sector still beating the Nifty but "Weakening".
- **History:** the old rules gave zero picks on 3 of 185 signal dates, so this day was unusual, not systematic.

| Risk-off sector rule | Train PF all / risk-off | Test PF all / risk-off |
|---|---|---|
| Leading + Improving (old) | 1.41 / 0.56 | 1.13 / 1.58 |
| **Leading + Weakening = sector RS > 0 (adopted)** | **1.46 / 0.86** | 1.09 / 1.43 |
| Not Lagging | 1.44 / 0.81 | 1.09 / 1.44 |
| No sector rule | 1.44 / 0.80 | 1.08 / 1.44 |

Chosen on the training period, as every change is; the old rule's better test figure is not chased. Risk-off trading
lost money in training under every variant and made money in testing under every variant, which is why positions are
half size in risk-off.

## Ideas tested from wangzhe3224/awesome-systematic-trading (v2 branch, 2026-10-22)

The repo is a curated list of about 300 projects; its code folders are placeholders. Five ideas that target measured
weaknesses were tested on our data (`research/awesome_tests.py`, isolated research venv):

| Idea (source in the list) | Result | Decision |
|---|---|---|
| Portfolio metrics (quantstats, pyfolio, ffn) | All years: CAGR 11.6% vs Nifty 6.1%, Sharpe 0.35 vs 0.02, **max drawdown −27.0% vs −15.8%**, average exposure 55% | **Integrated** as `--portfolio` (evaluation only) |
| Date-clustered t-stats (honest-signals, Lacuna) | No pattern significant in both periods; some pooled t-stats were overstated (double bottom train −4.4 pooled, −1.2 clustered) | **Integrated** into `pattern_study.py` (evaluation only) |
| Volatility-managed momentum (pysystemtrade) | Train-best scheme (skip when 3-month momentum-factor return < 0) failed on test: CAGR 1.5% vs 5.8% live; vol targeting was worse on train | Rejected |
| Hurst exponent factor (hurst-calculator) | IC −0.001 train, −0.005 test | Rejected |
| ML ranking (Qlib-style gradient boosting, purged split) | Test IC +0.037 and top-10 excess +0.93% per 15 days, vs the momentum score's +0.057 and +1.94% | Rejected |

Finding: the momentum long-short factor earned money every year, 2024 included (+14%). The strategy's 2024–25 losses
and its deeper-than-Nifty drawdown come from being long in a falling market (beta), not from momentum failing, so a
fix would have to manage market exposure, not factor volatility.

## Known limits

- **Survivorship bias:** today's constituents only, so past returns are flattered; comparisons between configs are less affected.
- **Short history:** about 4 years and a few market regimes.
- **Per-trade figures:** trades overlap, so this is not a portfolio equity curve.
- **Model risk:** one Yahoo data source, with no NSE bhavcopy cross-check yet.
