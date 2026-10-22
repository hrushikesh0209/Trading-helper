# India stock agents (Claude Code skills)

Two independent Claude Code skills for the Indian stock market (NSE / BSE), run by Claude Code itself, with no LLM API key.

| Skill | What it does | Cost per run |
|---|---|---|
| `stock-picks` | Daily Nifty 500 swing picks: local price database, TradingView-matching indicators, a backtested momentum screener, market regime and sector rotation, technical stop-loss, adaptive targets, and a Claude news/results review | about 30–60K Claude tokens |
| `trading-analysis` | Deep dive on one stock: the 12-agent [TradingAgents](https://github.com/TauricResearch/TradingAgents) pipeline (analysts, bull/bear debate, trader, risk team, portfolio manager) with Indian news, social and market sources | about 750K Claude tokens |

## Layout

```
stock-picks/
  SKILL.md                  commands and workflow
  scripts/                  market_data, indicators, screener, levels, patterns, backtests, picks pages
  references/               technical playbook, India sectors, backtest report, reviewer rules
trading-analysis/
  SKILL.md
  scripts/                  data fetch (yfinance + Indian sources), memory log, report builder
  references/prompts.md     the agent roles
```

## Requirements

- Claude Code with a Claude plan.
- [TradingAgents](https://github.com/TauricResearch/TradingAgents) cloned to `C:\Users\Dell\TradingAgents`, with its `.venv` (`pip install .`, plus `TA-Lib`).
- A data folder at `D:\TradingAgentsData` (created by the scripts).
- Copy or clone this folder as `%USERPROFILE%\.claude\skills`. The paths in the scripts assume the locations above.

## Evidence

Every rule in the screener was chosen on a training period (Dec 2022 – Mar 2025) and checked on a later test period
(Apr 2025 – Sep 2026); see `stock-picks/references/backtest_report.md`, including what failed.

## Credits and disclaimer

The deep-dive agent prompts and data layer come from TauricResearch/TradingAgents (Apache-2.0).
Research output, not investment advice.
