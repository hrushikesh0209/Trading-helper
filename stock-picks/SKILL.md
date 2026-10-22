---
name: stock-picks
description: Daily Nifty 500 stock picks for the Indian market. A backtested technical screener (momentum ranking, trailing stops, market regime, sector rotation) shortlists swing and positional candidates from a local price database, then Claude checks news and results dates and builds a picks page with entry, stop-loss, targets and TradingView charts. Use when the user asks for today's stock picks, best stocks to buy, a screener, top swing or positional trades in India, or to update, screen, backtest or check the stock database, e.g. "/stock-picks", "/stock-picks 2026-10-21", "/stock-picks backtest", "/stock-picks status".
argument-hint: "[YYYY-MM-DD] | update | screen [date] | backtest | factors | status | install"
---

# Stock picks (Nifty 500, India)

A separate skill from `/trading-analysis`; it never changes that skill's files. It can suggest a deep dive there.

Paths:
- Python `PY` = `C:\Users\Dell\TradingAgents\.venv\Scripts\python.exe`; scripts `S` = `C:\Users\Dell\.claude\skills\stock-picks\scripts`
- Knowledge: `references\technical_playbook.md`, `india_sectors.md`, `backtest_report.md`, `architecture.md`, `reviewer.md`
- Data: `D:\TradingAgentsData\market\market.db` (prices), `screens\` (daily outputs), `picks\picks_log.csv` (kept picks)

## Default: today's picks (`/stock-picks [date]`)

Cost: one reviewer subagent, about 30–60K tokens. Everything else is Python.

1. **Fresh data.** Read `D:\TradingAgentsData\screens\` for the newest `<date>_summary.json`.
   - **If it is not today's date (or the requested date)**, run `PY S\market_data.py daily`. It updates prices, checks data quality and runs the screen, in about 1 minute.
   - **Before 3:45 pm IST** today's bar does not exist yet, so the newest complete day is yesterday; say so.
2. **Brief:** run `PY S\picks_prep.py [--date D]`. It writes `<date>_shortlist.md` with the regime, sectors, the swing candidate table, and headlines and results dates for the shortlisted stocks only.
3. **Review.** Launch one `general-purpose` subagent with this prompt:
   > You are the /stock-picks reviewer for `<DATE>`. Read `C:\Users\Dell\.claude\skills\stock-picks\references\reviewer.md` and follow it exactly, using the brief at `D:\TradingAgentsData\screens\<DATE>_shortlist.md` and the knowledge files it names. Do not use web search or fetch any other data.

   If the swing table is empty, skip the reviewer, write `[]` to `<date>_review.json` and go to step 4.
4. **Page:** run `PY S\picks_page.py [--date D]`. It writes `<date>_picks.html` and appends kept picks to the picks log.
5. **Reply to the user.** Every report is **swing trades only** (hold up to 20 trading days), the user's standing choice:
   - **Header:** the regime in one line, and how many swing picks were kept.
   - **Picks table:** recommendation (Buy) · symbol · sector · entry ₹ · stop-loss ₹ (risk %) · Target 1 ₹ (R) · Target 2 ₹ (R) · size.
   - **Why the levels:** one line per pick giving the technical source of the stop, T1 and T2 from the screen file (`stop_why`, `t1_why`, `t2_why`) and each target's historical hit rate (`t1_hit`, `t2_hit`), e.g. "stop below the 8 Oct swing low; T1 at the 22 Sep swing high (reached 41% of the time)". Mention detected chart patterns (`patterns`) as context only.
   - **Exit rule:** the trailing stop (highest close − 2 ATR) or the 20-day time stop closes the trade. Targets are optional booking points: half at T1 locks gains at a small cost, all at T1 wins more often for a similar profit.
   - **Dropped candidates:** each with its recommendation (Wait or Avoid), and its entry, stop-loss and targets from the screen so they can act once it re-qualifies, plus the one-line reason (for example, results in 2 days).
   - **Page:** the path to the HTML page; offer to open it.
   - **Deep dive:** suggest `/trading-analysis <SYMBOL>` for any pick they are serious about, a separate 12-agent analysis of about 750K tokens.
   - **Close:** end with "Research output, not investment advice."

   Never restate a number that is not in the screen files.

## Other commands
- **`update`:** `PY S\market_data.py daily` (prices, quality check, cleanup, screen). No tokens.
- **`screen [date]`:** `PY S\screener.py [--date D]`. Shows the swing list (entry, stop-loss, both targets) without the news review. No tokens.
- **`diagnose [date]`:** `PY S\diagnose.py [--date D] [--history]` answers "why these picks, or none?": data sanity, the rule-by-rule funnel, an independent recomputation of regime and sector numbers, and (with `--history`) how often the rules give zero picks. No tokens.
- **`status`:** `PY S\market_data.py status`, plus the newest screen date and whether the daily task is installed (`Get-ScheduledTask -TaskName "TradingAgents Daily Market Data"`).
- **`backtest`:** `PY S\backtest_screener.py --v2` (rules on stored history), then summarise against `references\backtest_report.md`. Rebuild features first with `PY S\screener.py --rebuild` if prices changed. No tokens.
- **`factors`:** `PY S\factor_ic.py` shows which factors predict 15-day returns. Use it before changing any weight.
- **`patterns`:** `PY S\pattern_study.py` re-runs the chart and candlestick pattern study (about 1 minute; `--report-only` re-prints the last one).
- **`calibrate`:** `PY S\calibrate_levels.py` re-measures level-type hit rates (about 1.5 minutes) and rewrites `level_stats.json`, which picks the targets. Re-run when a year of new data is in, then re-check with `PY S\backtest_screener.py --levels`.
- **`install`:** the daily 4:30 pm task must be installed by the user. Tell them to type: `! powershell -ExecutionPolicy Bypass -File C:\Users\Dell\.claude\skills\stock-picks\scripts\install_daily_task.ps1`

## Rules for changing the screener
- **Evidence first:** change a weight, threshold or exit only with evidence from `backtest_screener.py` or `factor_ic.py`. Choose on the training period (before 2025-04-01), confirm on the test period, and record the result in `backtest_report.md`.
- **Overfitting:** a change that wins only in training is overfit; reject it.
- **Keep the record:** setups B, C and D stay as tags for context but do not qualify picks; they lost money in both periods.
