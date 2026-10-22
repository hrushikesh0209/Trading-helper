# System map: data, knowledge, agents

Two independent skills:
- **`/stock-picks`** (this one): all the files here, plus the price database and screener.
- **`/trading-analysis`**: the original 12-agent deep dive. It is unchanged and does not read these files.

They connect only through you: `/stock-picks` suggests a symbol, and you may run `/trading-analysis <SYMBOL>` on it.
The tables below that mention the deep-dive agents describe how the playbook *could* inform them; that wiring is
deliberately not installed, so the original agents run exactly as before.

Three layers, each doing what it is cheapest and most reliable at:

| Layer | Does | Never does | Token cost |
|---|---|---|---|
| **Python** (scripts, scheduled) | Downloads, stores and cleans prices; computes every indicator, setup, score, stop and target | Judgement calls, reading news | 0 |
| **Knowledge files** (`references/`) | Hold the rules: indicator meanings, setups, regime, risk, sector drivers | Change by themselves (updated by you or by the scorecard review) | read only when an agent needs them |
| **Claude agents** | Judge, cross-check, read news, argue bull vs bear, explain | Invent numbers: every figure comes from a data file | only when you ask |

## Daily flow

```
4:30 pm IST, weekdays (Task Scheduler, no Claude)
  market_data.py daily ── NSE list ─┐
                         Yahoo ─────┼─> market.db (5 years, Nifty 500 + benchmarks)
                                    └─> suspect table (data jumps)
  screener.py (Phase 2) ── reads market.db + technical_playbook rules
      ├─> screens/<date>_regime.md      (layer 1: risk-on / neutral / risk-off)
      ├─> screens/sector_snapshot.md    (layer 2: 20 sectors, quadrants)
      ├─> screens/<date>_swing25.csv    (layers 3-5: setups, scores, entry/stop/target)
      └─> screens/<date>_positional10.csv

When you run /stock-picks (Phase 3, about 30-60K tokens)
  script pre-fetches headlines + results dates for the 25 only
  Claude reviewer reads: swing25 + regime + sector snapshot + headlines
                         + technical_playbook (avoid list) + india_sectors (drivers)
  ─> Top 10 table + HTML page with TradingView chart widgets

When you pick a stock: /trading-analysis <SYMBOL> (about 750K tokens)
  fetch_data.py ── live news, social, fundamentals (+ from Phase 2: indicators,
                   setup and sector row read from market.db, no re-download)
  4 analysts ─> bull/bear ─> research manager ─> trader ─> 3 risk ─> portfolio manager
  each role reads the knowledge sections named in prompts.md

Every pick and every deep-dive call
  ─> memory log ─> settled after 5 trading days vs Nifty ─> lessons fed to later runs
  ─> picks log (Phase 4) ─> 5/10/20-day hit rate per setup ─> weight tuning
```

## Who uses what

| Component | Reads | Writes |
|---|---|---|
| `market_data.py` | NSE Nifty 500 list, Yahoo | `market\market.db`, logs, backups |
| `screener.py` (Phase 2) | `market.db`, playbook rules (as code) | `screens\` files |
| `/stock-picks` reviewer | `screens\` files, headlines, `technical_playbook.md` §3 avoid list and §7, `india_sectors.md` §1–2 | Top 10 page, picks log |
| `fetch_data.py` | Yahoo, Google News, ET/Mint/BS/Moneycontrol, Reddit, StockTwits, (Phase 2) `market.db` | `runs\<stock>\<date>\data\` |
| Market analyst | `market.md`, playbook §1–4b, §6 | report 1 |
| Fundamentals analyst | `fundamentals.md`, `india_sectors.md` §1 | report 2 |
| News analyst | `news.md`, `india_sectors.md` §1–2 | report 3 |
| Sentiment analyst | `sentiment.md` | report 4 |
| Bull / bear researchers | reports 1–4, playbook §2 | debate |
| Research manager | debate | plan |
| Trader | plan, report 1, portfolio, playbook §5 | order |
| Risk team (3) | order, reports 1–4, portfolio, playbook §4–5 | risk debate |
| Portfolio manager | plan, order, risk debate, past lessons, playbook §4 | final decision |
| Reflector | due decisions + outcomes | lessons in the memory log |

## Feedback loop

The playbook's weights and thresholds are starting values from published methods. Phase 4 measures every pick
after 5, 10 and 20 trading days against the Nifty, by setup and by regime. Once a setup has enough settled picks
(at least 30), its weight is raised or lowered from the results, and the change is written into this playbook with
its evidence, so the knowledge improves from Indian market outcomes rather than opinion.
