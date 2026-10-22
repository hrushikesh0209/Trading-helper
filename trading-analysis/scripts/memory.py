"""TradingAgents' memory log, driven by Claude Code instead of an LLM key.

The log itself, settlement against the regional benchmark (Nifty 50 for .NS,
Sensex for .BO, SPY for US) and the past-context selection are the repo's own
code; only the 2-4 sentence reflection is written by Claude, between `due` and
`settle`.

    python memory.py store   --ticker T --date D --decision-file F [--rating R] [--log L]
    python memory.py due     [--out due.json] [--log L]       # settleable decisions + returns
    python memory.py settle  --reflections reflections.json [--log L]
    python memory.py context --ticker T --date D [--out F] [--log L]
    python memory.py summary [--log L]                        # backtest-style scorecard
"""

import argparse
import json
import os
import sys
from pathlib import Path

DATA_ROOT = Path(os.environ.get("TRADINGAGENTS_DATA_ROOT", r"D:\TradingAgentsData"))
DEFAULT_LOG = DATA_ROOT / "memory" / "trading_memory.md"
os.environ.setdefault("TRADINGAGENTS_CACHE_DIR", str(DATA_ROOT / "cache"))

from tradingagents.backtest import summarize  # noqa: E402
from tradingagents.dataflows.config import set_config  # noqa: E402
from tradingagents.dataflows.date_window import is_historical  # noqa: E402
from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402
from tradingagents.memory.log import TradingMemoryLog  # noqa: E402
from tradingagents.memory.settlement import fetch_returns, resolve_benchmark  # noqa: E402

HOLDING_DAYS = DEFAULT_CONFIG.get("holding_period_days", 5)


def _log(path) -> TradingMemoryLog:
    return TradingMemoryLog({"memory_log_path": str(path)})


def cmd_store(a):
    text = Path(a.decision_file).read_text(encoding="utf-8")
    _log(a.log).store_decision(a.ticker, a.date, text, rating=a.rating)
    print(f"stored {a.ticker} {a.date} in {a.log}")


def cmd_due(a):
    set_config({"data_cache_dir": str(DATA_ROOT / "cache")})
    due, waiting, failed = [], [], []
    for e in _log(a.log).get_pending_entries():
        bench = resolve_benchmark(e["ticker"], DEFAULT_CONFIG)
        try:
            raw, alpha, days, resolved = fetch_returns(e["ticker"], e["date"], HOLDING_DAYS, benchmark=bench)
        except Exception as exc:
            failed.append(f"{e['ticker']} {e['date']}: {exc}")
            continue
        if raw is None:
            waiting.append(f"{e['ticker']} {e['date']}")
            continue
        due.append({"ticker": e["ticker"], "date": e["date"], "rating": e.get("rating"),
                    "raw_return": raw, "alpha_return": alpha, "holding_days": days,
                    "resolution_date": resolved, "benchmark": bench,
                    "decision": e.get("decision", "")})
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(due, indent=2), encoding="utf-8")
    print(json.dumps({"due": [f"{d['ticker']} {d['date']} raw {d['raw_return']:+.1%} "
                              f"alpha vs {d['benchmark']} {d['alpha_return']:+.1%}" for d in due],
                      "still_in_holding_window": waiting, "price_fetch_failed": failed,
                      "due_file": str(a.out)}, indent=2))


def cmd_settle(a):
    """Apply reflections: a JSON list of due entries, each with a 'reflection' added."""
    log = _log(a.log)
    for d in json.loads(Path(a.reflections).read_text(encoding="utf-8-sig")):
        if not d.get("reflection"):
            continue
        ok = log.update_with_outcome(d["ticker"], d["date"], d["raw_return"], d["alpha_return"],
                                     d["holding_days"], d["reflection"].strip(),
                                     resolution_date=d.get("resolution_date"))
        print(f"{'settled' if ok else 'already settled'}: {d['ticker']} {d['date']}")


def cmd_context(a):
    # Same cutoff as TradingAgentsGraph._memory_as_of: a historical run only
    # learns from outcomes known by its date.
    as_of = a.date if is_historical(a.date) else None
    ctx = _log(a.log).get_past_context(a.ticker, as_of=as_of)
    ctx = ctx or "No prior decisions or lessons in the memory log yet."
    if a.out:
        Path(a.out).write_text(ctx, encoding="utf-8")
    print(ctx)


def cmd_summary(a):
    print(summarize(Path(a.log)).render())


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("store", "due", "settle", "context", "summary"):
        s = sub.add_parser(name)
        s.add_argument("--log", default=str(DEFAULT_LOG))
        if name in ("store", "context"):
            s.add_argument("--ticker", required=True)
            s.add_argument("--date", required=True)
        if name == "store":
            s.add_argument("--decision-file", required=True)
            s.add_argument("--rating")
        if name == "due":
            s.add_argument("--out", default=str(DATA_ROOT / "memory" / "due.json"))
        if name == "settle":
            s.add_argument("--reflections", required=True)
        if name == "context":
            s.add_argument("--out")
    a = p.parse_args()
    Path(a.log).parent.mkdir(parents=True, exist_ok=True)
    {"store": cmd_store, "due": cmd_due, "settle": cmd_settle,
     "context": cmd_context, "summary": cmd_summary}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
