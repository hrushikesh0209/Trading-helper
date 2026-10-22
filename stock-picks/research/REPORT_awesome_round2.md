# awesome-systematic-trading, round 2: review of all 331 listed projects (2026-10-22)

Research only, on the `v3-research` branch; no live script changed. Reproduce with `research/awesome_tests_2.py`
(research venv). Every choice was made on the training period (before 2025-04-01) and checked on the test period.

## Triage of the 331 projects

| Group | Approx. count | Verdict |
|---|---|---|
| Crypto, prediction markets, crypto arbitrage | 95 | Not Indian equities |
| HFT, order books, C++/Rust/Go engines, queues, profilers | 50 | Daily swing tool: speed is not the constraint |
| Options pricing | 8 | No options |
| US-only data (SEC, 13F, Form 4, Congress, US options) | 15 | No India coverage; no listed source has NSE delivery % or FII/DII flows |
| Generic libraries (numpy, pandas, ML frameworks, dataframes, databases) | 40 | Building blocks already in use or not needed |
| Event-driven backtest frameworks | 30 | Our verified engine already does this |
| Paid or closed AI signal services | 15 | Methods not inspectable |
| **Tested: ideas that target measured weaknesses** | 6 | See below (5 in round 1, 3 more here) |

## Results

| Idea (project) | Result | Verdict |
|---|---|---|
| **RSRS market timing** (QuantsPlaybook, Everbright Securities): 18-day slope of Nifty high on low, z-scored over 600 days, × R²; no new entries after it drops below −0.7 until it rises above +0.7 | Chosen on train (Calmar 1.62 vs 0.73). **Test: CAGR 9.4% vs 5.8%, Sharpe 0.26 vs 0.02, max drawdown −8.2% vs −15.6%.** All years: CAGR 13.0% vs 11.6%, drawdown −12.7% vs −27.0%. Drawdown lower on test in **27 / 27** settings tried (N 14–22, M 400–800, thresholds 0.5–1.0); test Calmar higher in 16 / 27, so the return gain is setting-sensitive. 2024: +3.0% vs −8.5%; 2025: +0.9% vs −8.1%; 2023: +50% vs +77% (gives up some bull-market upside) | **Recommend**, as an exposure overlay |
| EWMAC trend filter on the Nifty (pysystemtrade) | Drawdown −19.6% / −14.2% (train / test) vs −23.4% / −15.6%; train Calmar 0.76–0.90 | Weaker than RSRS; not needed |
| Breadth floor (QuantsPlaybook diffusion index) | 20% floor ≈ live; 30% floor worse on test (CAGR 1.6%) | Reject |
| Adaptive factor weights from trailing IC (Inalpha) | Test top-10 excess +0.39% vs fixed score +1.42% | Reject |
| Deflated Sharpe ratio (Advances in Financial ML / Hudson & Thames) | Live rules, 45 variants tried: P(real skill beyond the 6.5% risk-free rate) **55%**; with the RSRS overlay **64–66%**; on raw returns 80% vs 90–91% | **Recommend** as a standing report |
| Point-in-time masking for LLM backtests (TraderHarness) | Lesson, not a test: `/trading-analysis` cannot be backtested on past dates because the model already knows what happened; only forward tracking of its calls is honest | Adopt as a rule |
| NSE charts with stop / targets drawn (mplfinance) | Not a performance change: TradingView embeds show only BSE; a static NSE chart with our levels would help reading | Optional UX |

## Honest reading

- The edge over a risk-free rate is modest and not yet statistically convincing (55% → 64–66% with RSRS). Forward
  tracking of live picks remains the decisive test.
- RSRS was tuned on the Chinese CSI 300 in its source; here it was re-tested on the Nifty without changing its published
  defaults (N 18, threshold 0.7). M = 600 was the train-chosen option among two standard values.
- With RSRS on, the screen still runs every day; on "off" days the page would say "market timing: stand aside, no new
  entries", which happened on about 45% of days in the test period.
