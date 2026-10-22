---
name: trading-analysis
description: Run a TradingAgents-style multi-agent stock analysis (market, fundamentals, news and sentiment analysts, bull/bear debate, research manager, trader, risk debate, portfolio manager, memory of past decisions) using Claude Code itself instead of an LLM API key. Indian stocks (NSE/BSE) by default. Use when the user asks to analyze a ticker, get a buy/sell/hold call, run trading agents, settle past calls, or backtest, e.g. "/trading-analysis RELIANCE", "/trading-analysis TCS 2026-10-21 --lang Hindi", "/trading-analysis backtest INFY 2026-09-01 2026-10-01".
argument-hint: <TICKER> [YYYY-MM-DD] [--analysts market,social,news,fundamentals] [--rounds N] [--risk-rounds N] [--lang L] [--us] | settle | backtest <TICKERS> <START> <END> [--every N] | summary
---

# Trading analysis (TradingAgents, run by Claude Code)

This reproduces the TauricResearch/TradingAgents pipeline, adapted for the Indian market. Market data comes from the repo's own data functions plus keyless Indian sources (no AI key needed). Every agent role is played by a Claude Code subagent. The memory log, benchmark settlement, report tree and HTML page are the repo's own code.

Paths:
- Python: `C:\Users\Dell\TradingAgents\.venv\Scripts\python.exe` (call it `PY`)
- Scripts: `C:\Users\Dell\.claude\skills\trading-analysis\scripts` (call it `S`); prompts in `..\references\prompts.md`
- Data root `D:\TradingAgentsData`: runs in `runs\<TICKER>\<DATE>`, memory log in `memory\trading_memory.md`, portfolio in `portfolio.json`, yfinance cache in `cache`, backtests in `backtest\<id>`

## Arguments
- **Ticker**: a bare symbol is treated as NSE (`RELIANCE` becomes `RELIANCE.NS`). Use `.BO` for BSE (e.g. `500325.BO`). Pass `--us` to read a bare symbol as US (fetch with `--market us`).
- **Date**: defaults to today. A past date makes live-only feeds (Indian market RSS, StockTwits, shareholding, event calendar, Yahoo's news sample) come back as withheld, by design, to avoid look-ahead. Google News and Reddit stay date-filtered and work for recent past dates.
- `--analysts`: subset of `market,social,news,fundamentals` (social = sentiment). Default all four.
- `--rounds N` (bull/bear rounds, default 1) and `--risk-rounds N` (risk rounds, default 1).
- `--lang L`: output language, e.g. Hindi, Telugu, Tamil. Default English.

## Analyze: steps
Use `RUN = D:\TradingAgentsData\runs\<TICKER>\<DATE>`, where TICKER is the resolved symbol printed by the fetch step.

**0. Resume.** If `RUN\reports\` already holds some outputs from an interrupted run, skip each step whose output file exists and continue from the first missing one. This is the skill's version of the checkpoint resume. Refetch data only if the user asks.

**1. Fetch data:** `PY S\fetch_data.py <ticker> <DATE> --out <RUN>` (add `--market us` for `--us`). The last stdout line is JSON with the resolved `ticker`. If the stock data or snapshot failed (for example an invalid ticker), stop and tell the user. Other failures are fine; the files mark them as unavailable.

**2. Memory step** (the repo runs it alongside the analysts):
- `PY S\memory.py due` lists past decisions whose 5-trading-day window has now traded, with raw return and alpha against Nifty 50 / Sensex / SPY.
- If any are due, launch one `general-purpose` subagent as the `reflector` role (prompt template below). Then run `PY S\memory.py settle --reflections D:\TradingAgentsData\memory\reflections.json`.
- If settling fails, write a one-line note to `RUN\data\memory_note.md` and continue.
- Then run `PY S\memory.py context --ticker <TICKER> --date <DATE> --out <RUN>\data\past_context.md`.

**3. Analysts, in parallel.** In one message, launch one `general-purpose` subagent per selected analyst: market_analyst, fundamentals_analyst, news_analyst, sentiment_analyst. The memory step can run at the same time. Prompt template:
> You are the `<role>` in a TradingAgents run. RUN = `<RUN>`, ticker `<TICKER>`, analysis date `<DATE>`, LANG = `<LANG>`. Read `C:\Users\Dell\.claude\skills\trading-analysis\references\prompts.md`, follow the "Shared rules", the "Indian market context" if the instrument is Indian, and the `## <role>` section exactly. Read the input files it names and write the output file it names. Do not use web search or fetch any other data.

**4. Investment debate, in sequence.** Run `bull_researcher`, then `bear_researcher`, one subagent at a time, and repeat for each extra `--rounds`. Tell each turn to append to `5_debate.md` without changing earlier sections. Then run `research_manager`, then `trader`.

**5. Risk debate, in sequence:** `aggressive_risk`, then `conservative_risk`, then `neutral_risk`, repeated per `--risk-rounds`. Each appends to `8_risk_debate.md`.

**6. Final decision:** run `portfolio_manager`.

**7. Save and record:**
- `PY S\build_report.py <RUN> --analysts <list> --rounds N --risk-rounds N --lang <LANG>` writes the repo's report tree (`1_analysts` to `5_portfolio`), `complete_report.md` and `complete_report.html`.
- `PY S\memory.py store --ticker <TICKER> --date <DATE> --decision-file <RUN>\reports\9_final_decision.md` records the decision as pending. A later run settles it once 5 trading days have passed.

**8. Report to the user:**
- the final rating, and the trader's action with entry and stop in ₹
- 3 to 5 key reasons
- any lesson from past decisions that was used
- which sources were unavailable
- paths to `complete_report.html` and `complete_report.md`

Offer to open the HTML page. End with a note that this is research output, not financial advice.

## Other modes
- **settle**: run step 2 alone (due, reflector, settle), then `PY S\memory.py summary`.
- **summary**: `PY S\memory.py summary` prints the scorecard: per rating, the count, how often it called the direction, and the mean alpha against the benchmark.
- **backtest `<TICKERS> <START> <END> [--every N]`** (default every 7 days): every ticker × date cell is one full analysis.
  - **Cost check first:** about 12 subagents per cell, so tell the user how many cells that is and confirm before starting.
  - **Isolated log:** use `--log D:\TradingAgentsData\backtest\<id>\trading_memory.md` on every memory.py call and put runs under `D:\TradingAgentsData\backtest\<id>\runs`, so the live memory log stays clean.
  - **Order:** run the cells in date order, with the memory step before each cell, then settle and print `summary --log ...`.
  - **Data caveat:** past dates lack the live-only feeds, so backtest analyses see less data than live ones.

## Portfolio (optional)
If `D:\TradingAgentsData\portfolio.json` exists, the trader, risk team and portfolio manager size against it. Format (the repo's PortfolioContext; a bare symbol means NSE):
```json
{"cash": 250000, "currency": "INR", "positions": [{"ticker": "RELIANCE", "quantity": 20, "average_price": 1290.5}]}
```

## Notes
- Do not do the analysis in the main conversation: subagents write the files, and the main thread only orchestrates and reads the final decision.
- **Optional keys** in `C:\Users\Dell\TradingAgents\.env`:
  - `FRED_API_KEY` adds US rate data as the global backdrop.
  - `TYPESAFE_API_KEY` screens off-topic social posts.
- **Not carried over from the repo**, because they don't apply here: LLM provider settings, SEC EDGAR (US filers only, skipped for Indian stocks), Alpha Vantage, and ChatGPT login.
