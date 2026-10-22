# Technical analysis playbook (Indian equities, daily data)

The rulebook for both the screener code (Phase 2) and the agents. Every indicator uses
TradingView's built-in formula and default inputs, so values match a TradingView chart.
Swing trading (hold 1 to 4 weeks) is the priority; positional (1 to 6 months) is second.

How to read it: **no single indicator is a signal.** A setup needs agreement across the
five layers below. Each layer either confirms or vetoes; the more layers agree, the stronger the call.

```
1. Market regime   -> is this a market to buy at all?        (Nifty trend, breadth, VIX)
2. Sector          -> is the stock's industry leading?        (sector RS, sector breadth)
3. Trend           -> is the stock itself in an uptrend?      (MAs, ADX, Supertrend, weekly trend)
4. Momentum/volume -> is buying pressure real and fresh?      (RSI, MACD, volume, OBV)
5. Trigger + risk  -> is there a defined entry and stop?      (breakout/pullback, ATR, R:R)
```

---

## 1. Formulas and defaults (TradingView-matching)

| Indicator | TradingView default | Formula notes that matter for matching |
|---|---|---|
| SMA | 50, 150, 200 | Plain mean of close |
| EMA | 9, 20, 50 | alpha = 2 / (n + 1); converges after about 3n bars, so compute on 1+ year of data |
| RSI | 14, levels 70 / 30 | Wilder smoothing (RMA, alpha = 1/n) of gains and losses, not a simple mean |
| MACD | 12, 26, 9 | EMA12 − EMA26; signal = EMA9 of MACD; histogram = MACD − signal |
| ATR | 14 | RMA of True Range (max of H−L, \|H−prevC\|, \|L−prevC\|) |
| ADX / DMI | 14, 14 | +DM/−DM and TR smoothed with RMA; ADX = RMA of DX |
| Supertrend | ATR 10, factor 3 | Bands at hl2 ± 3×ATR10, each band only ratchets in the trend's favour |
| Bollinger Bands | 20, 2 | SMA20 ± 2 × **population** stdev (pandas `std(ddof=0)`; the default ddof=1 will not match) |
| Stochastic | 14, 3, 3 | as listed in TradingView's Technical Ratings |
| Stochastic RSI | 3, 3, 14, 14 | Stochastic of RSI14 over 14, K and D smoothed 3 |
| CCI | 20 | (typical price − SMA) / (0.015 × mean deviation) |
| Williams %R | 14 | |
| Ichimoku | 9, 26, 52 | Conversion, base, spans A/B |
| Hull MA | 9 | WMA(2×WMA(n/2) − WMA(n), √n) |
| VWMA | 20 | Volume-weighted SMA |
| OBV | — | Cumulative ±volume by close direction |
| Donchian | 20, 55 | Highest high / lowest low of the prior n bars (exclude today for breakouts) |
| Classic pivots | prior week / month | P = (H+L+C)/3, R1 = 2P−L, S1 = 2P−H, R2 = P+(H−L), S2 = P−(H−L) |
| Chandelier exit | 22, 3 | Highest high 22 − 3 × ATR22 (long stop) |

Prices are split-adjusted, not dividend-adjusted, the same basis as TradingView charts.
Verify during the build: pick 3 stocks and compare RSI14, ATR14 and Supertrend with a TradingView chart.

## 2. Bullish vs bearish: what each indicator says

| Layer | Indicator | Bullish | Bearish | Watch out |
|---|---|---|---|---|
| Trend | Price vs SMA 200 | Above, and SMA200 rising for 20+ days | Below, SMA200 falling | Defines which side you trade; never buy swing longs below a falling 200 |
| Trend | MA stack | Close > EMA20 > SMA50 > SMA200 | Reverse order | Stack forming after a base is the best phase; a stretched stack is late |
| Trend | Golden / death cross | SMA50 crosses above SMA200 | Crosses below | Lagging; use as context, not a trigger |
| Trend | ADX 14 | ADX > 20 and rising with +DI > −DI | ADX > 20 rising with −DI > +DI | ADX < 20 = no trend: breakouts fail more, mean-reversion works better |
| Trend | Supertrend 10/3 | Price above the line (green) | Below (red) | Whipsaws in sideways markets; good as a trailing stop |
| Trend | Weekly (positional) | Weekly close > 30-week MA, MA rising (Weinstein stage 2) | Below a falling 30-week MA (stage 4) | Daily signals against the weekly trend fail more often |
| Momentum | RSI 14 | 40–80 range in uptrends; dips to 40–50 that hold are buy zones; bullish divergence at lows | 20–60 range in downtrends; rallies failing at 55–60; bearish divergence at highs | In strong trends RSI stays above 70 for weeks: overbought is not a sell by itself |
| Momentum | MACD | MACD > signal, histogram rising; cross above zero line | MACD < signal, histogram falling | Crosses deep below zero are weaker buys than crosses near zero |
| Momentum | Stoch RSI | K crosses up from < 20 in an uptrend (pullback entry) | K crosses down from > 80 in a downtrend | Very noisy; only for timing within a confirmed trend |
| Volatility | Bollinger | Close above upper band after a squeeze = expansion breakout | Close below lower band after a squeeze | Riding the upper band is strength, not a sell |
| Volatility | Squeeze | BB width at 6-month low (BB inside Keltner) then expands up | Expands down | The squeeze says "move coming", not the direction |
| Volatility | ATR % | Moderate (1.5–4% of price) = tradeable | Very high (> 6%) = stops too wide | Used for stops and position size, not direction |
| Volume | Volume ratio | Breakout day volume ≥ 1.5× 50-day average | Breakdown on high volume | Breakouts on low volume fail more often |
| Volume | OBV / up-down volume | OBV making new highs with price; up-day volume > down-day volume over 50 days | OBV falling while price rises (distribution) | Divergence leads price |
| Volume | Delivery % (NSE bhavcopy, Phase 1b) | Rising delivery % on up days = real buying | High delivery on down days = real selling | India-specific; Yahoo does not have it |
| Structure | 52-week high | Within 25% of the high; new highs on volume | Near 52-week lows, making lower lows | Stocks near highs keep outperforming (momentum effect) |
| Structure | Donchian 20 / 55 | Close above the prior 20 or 55-day high | Close below the prior 20 or 55-day low | False breakouts: require a close, not an intraday poke |
| Structure | Pivots / swing levels | Holding above the weekly pivot or prior resistance turned support | Failing at R1/R2 or prior support turned resistance | Use for targets and stops |

## 3. Setups the screener looks for

| Setup | Style | Conditions (all required) | Entry | Stop | Typical failure |
|---|---|---|---|---|---|
| **A. Trend template** (Minervini) | Positional + swing context | Close > SMA50 > SMA150 > SMA200; SMA200 rising 20+ days; close ≥ 1.3 × 52w low; within 25% of 52w high; RS percentile ≥ 70 | On a pullback or a breakout | Below SMA50 or the last swing low | Late-stage trend, extended stocks |
| **B. Breakout** | Swing | Close > highest close of prior 20 days (or 55); volume ≥ 1.5× 50-day avg; close in the top 25% of the day's range; base range of the prior 20 days ≤ 15% | Breakout close, or next day above the breakout high | Below the breakout level or 2 × ATR, whichever is tighter | Low-volume breakouts in weak markets |
| **C. Pullback in uptrend** | Swing | Close > SMA200 and SMA50 > SMA200; price within 1 ATR of EMA20 or SMA50; RSI 40–55 and up today; green candle | Close of the turn day | Below the pullback low | Pullback becomes a trend change: check sector and volume |
| **D. Squeeze breakout** | Swing | BB width at a 120-day low, then close above the upper band with volume ≥ 1.3× | Breakout close | Below the BB middle (SMA20) | Direction fails: needs layer 3 agreement |
| **E. Momentum leader** | Positional | Top decile of 3/6/12-month weighted return; above SMA200 | Pullbacks to EMA20 or SMA50 | Weekly close below the 30-week MA | Momentum crashes in sharp market reversals |

**What the backtest changed (v2, see `backtest_report.md`):** only setups A and E qualify a pick; B, C and D are
still tagged on each stock as context, but as stand-alone signals they lost money in both test periods. Stocks are
ranked by a momentum score (12-month-skip-1-month return 35%, nearness to the 52-week high 25%, RS percentile 20%,
above SMA200 10%, sector 10%). Exits use a trailing stop, not a fixed target. The tables in sections 2 and 3 remain
the vocabulary for explaining a chart; the score is what ranks stocks.

**Avoid list (vetoes):** close below a falling SMA200 (for longs); more than 3 ATR above EMA20 (extended); hit
upper or lower circuit today; results due within 3 trading days; a flagged data jump within the lookback; median
traded value under ₹10 crore a day; price under ₹50.

## 4. Market regime (layer 1)

**Market timing gate (v3, backtested):** before anything else, RSRS (`scripts/timing.py`) decides whether new entries
are allowed at all. It stands aside after the Nifty's RSRS score falls below −0.7 and takes entries again after it
rises above +0.7. On stand-aside days every candidate is a Wait (watchlist) and open trades keep their own stops. The
regime table below then sets how many picks and what size on the days entries are allowed.

| Signal | Risk-on | Neutral | Risk-off |
|---|---|---|---|
| Nifty 50 vs SMA200 | above, SMA200 rising | within ±2% | below |
| Nifty 50 vs SMA50 | above | around | below |
| Breadth: % of Nifty 500 above SMA50 | > 60% | 40–60% | < 40% |
| Breadth: % above SMA200 | > 60% | 40–60% | < 40% |
| India VIX | < 14 and stable | 14–20 | > 20 or up more than 25% in a week |
| Picks shown | 10 | 6 | 3 strongest only, or a "no-trade" day |

In risk-off, only setups A and E qualify, in sectors still beating the Nifty (RS > 0: Leading or Weakening quadrant), and position sizes are halved.
Most stocks move with the index: William O'Neil's often-cited observation is that three of four stocks follow the
general market's direction, which is why layer 1 comes first.

## 4b. TradingView Technical Ratings (one score input)

Implemented exactly as TradingView publishes it: 15 moving-average votes (SMA and EMA 10/20/30/50/100/200, Hull 9,
VWMA 20, Ichimoku 9/26/52) and 11 oscillator votes (RSI 14, Stochastic 14/3/3, CCI 20, ADX 14/14, Awesome Oscillator,
Momentum 10, MACD 12/26/9, Stoch RSI 3/3/14/14, Williams %R 14, Bull Bear Power 13, Ultimate Oscillator 7/14/28).
Each votes +1, 0 or −1; each group's rating is the mean of its votes; the overall rating is the mean of the two groups.
Above 0.5 Strong Buy, 0.1 to 0.5 Buy, −0.1 to 0.1 Neutral, −0.5 to −0.1 Sell, below −0.5 Strong Sell.
It is a summary of trend and momentum, not a setup: it feeds the score with a small weight and never selects a stock alone.

## 5. Risk management (layer 5)

- **Stop (v3, backtested):** 0.5 × ATR below the nearest support that is at least 1 ATR under entry: a confirmed swing low (60 bars), EMA20, SMA50, the prior week's pivot S1/S2, or the breakout level. With no support 1–3.5 ATR below, 2 × ATR. Capped at 10%. A support right under price (inside 1 ATR) is skipped: those stops were hit by noise in v1.
- **Targets (v4, adaptive):** candidates at least 1.5R above entry: confirmed swing highs (250 bars), the 52-week high, weekly pivot R1/R2, Fibonacci 1.272/1.618 extensions (stocks at new highs), the measured-move target of a fresh bullish chart pattern, and 2R/3R. T1 = the candidate with the highest (historical 20-day hit rate for its type, distance and context) × (distance in R); T2 = the best one beyond it. The method changes with the numbers: a swing high for one stock, a Fibonacci extension or a flag's measured move for another. Hit rates come from `level_stats.json` (training period).
- **Chart patterns** (double top/bottom, head & shoulders, triangles, flags, cup & handle, wedges) and **candles** are detected and reported as context. They showed no predictive edge in either period, so they never qualify or veto a pick on their own (see `backtest_report.md`).
- **Trailing exit (v2):** each day, raise the stop to the highest close since entry minus 2 × ATR (swing) or 3 × ATR (positional); never lower it. Time stop: 20 trading days (swing), 60 (positional).
- **Using the targets:** trailing everything had the best profit factor; selling half at T1 cost little; selling all at T1 won 7 points more often for a similar profit factor. The user picks the style.
- **Position size:** shares = (risk % of capital) / (entry − stop), with risk 1% when more than 60% of Nifty 500 stocks are above their SMA50, else 0.5%.
- **Gap risk:** NSE stocks gap on results and news overnight; a stop does not protect against a gap. Avoid holding through results unless sized for it.

## 6. India-specific behaviour

- **Price bands (circuits):** most stocks have 5/10/20% daily limits; F&O stocks have none but a dynamic band. A stock locked at upper circuit cannot be bought at a fair price, so skip it that day.
- **Results season** (mid-January, April, July and October): earnings gaps dominate; check the results date for every pick.
- **F&O expiry:** monthly expiry week adds volatility in F&O stocks (expiry day per current NSE rules; check the exchange circular).
- **Budget (1 February), RBI policy dates, state and general elections:** event volatility for rate-sensitive (banks, NBFCs, realty, autos) and PSU stocks.
- **FII flows:** heavy FII selling (often with a rising USD/INR and rising US yields) hits large-cap banks, IT and liquid names first. A strong dollar helps IT and pharma exporters.
- **T+1 settlement:** cash delivery is fast; there is no short selling of cash stocks overnight, so the screener is long-only.
- **Muhurat trading:** a one-hour Diwali session; treat that bar's volume as unrepresentative.

## 7. How agents use this

- **Screener (Python):** implements sections 1–5 exactly; produces numbers, never opinions.
- **/stock-picks reviewer (Claude):** reads the top-25 table, checks each pick against the avoid list and news, and explains which layers agree. It must not invent indicator values: every number comes from the table.
- **Market analyst (deep dive):** structures its report by the five layers and states which setup, if any, the stock fits.
- **Bull / bear researchers:** cite layer evidence; the bear must address the strongest bullish layer, and the bull the strongest bearish layer.
- **Trader / risk team:** use section 5 for entry, stop, target and size.

Sources: TradingView's published [Technical Ratings](https://in.tradingview.com/support/solutions/43000614331) method;
TradingView built-in indicator defaults; Minervini's trend template; Weinstein's stage analysis.
