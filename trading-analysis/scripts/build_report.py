"""Turn a run's agent files into TradingAgents' own report tree and HTML page.

Reads <run>/reports/*.md, rebuilds the final_state the graph would have held,
and calls tradingagents.reporting.write_report_tree, which writes the
1_analysts .. 5_portfolio folders, complete_report.md and complete_report.html.

    python build_report.py <run> [--analysts market,social,news,fundamentals]
                                 [--rounds 1] [--risk-rounds 1] [--lang English]
"""

import argparse
import json
import re
import sys
from pathlib import Path

import tradingagents
from tradingagents.agents.rating import parse_rating
from tradingagents.reporting import write_report_tree


def read(run: Path, name: str) -> str:
    p = run / "reports" / name
    return p.read_text(encoding="utf-8").strip() if p.is_file() else ""


def speakers(text: str, roles: tuple[str, ...]) -> dict[str, str]:
    """Split a debate file on its '### <Role> Analyst' headings, joining each role's turns."""
    out = {r: [] for r in roles}
    parts = re.split(r"^###\s+(\w+)\s+Analyst.*$", text, flags=re.M)
    for role, body in zip(parts[1::2], parts[2::2], strict=False):
        key = role.lower()
        if key in out:
            out[key].append(f"{role} Analyst: {body.strip()}")
    return {r: "\n\n".join(v) for r, v in out.items()}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("run")
    p.add_argument("--analysts", default="market,social,news,fundamentals")
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--risk-rounds", type=int, default=1)
    p.add_argument("--lang", default="English")
    a = p.parse_args()

    run = Path(a.run)
    meta = json.loads((run / "run.json").read_text(encoding="utf-8"))
    debate = speakers(read(run, "5_debate.md"), ("bull", "bear"))
    risk = speakers(read(run, "8_risk_debate.md"), ("aggressive", "conservative", "neutral"))
    decision = read(run, "9_final_decision.md")
    memory_note = (run / "data" / "memory_note.md")

    final_state = {
        "company_of_interest": meta["ticker"],
        "trade_date": meta["date"],
        "market_report": read(run, "1_market.md"),
        "fundamentals_report": read(run, "2_fundamentals.md"),
        "news_report": read(run, "3_news.md"),
        "sentiment_report": read(run, "4_sentiment.md"),
        "investment_debate_state": {"bull_history": debate["bull"], "bear_history": debate["bear"]},
        "investment_plan": read(run, "6_investment_plan.md"),
        "trader_investment_plan": read(run, "7_trader.md"),
        "risk_debate_state": {f"{k}_history": v for k, v in risk.items()},
        "final_trade_decision": decision,
        "final_rating": parse_rating(decision) if decision else None,
        "memory_note": memory_note.read_text(encoding="utf-8").strip() if memory_note.is_file() else "",
    }
    vendors = ({"core_stock_apis": "yfinance", "fundamental_data": "yfinance",
                "news_data": "google news india, ET, Mint, Business Standard, Moneycontrol, yfinance",
                "social": "stocktwits, reddit (Indian subs)"}
               if meta.get("market") == "india" else
               {"core_stock_apis": "yfinance", "fundamental_data": "sec_edgar,yfinance",
                "news_data": "yfinance", "prediction_markets": "polymarket"})
    settings = {
        "version": tradingagents.__version__,
        "llm_provider": "claude-code",
        "deep_think_llm": "Claude Code subagents",
        "quick_think_llm": "Claude Code subagents",
        "analysts": [x.strip() for x in a.analysts.split(",") if x.strip()],
        "max_debate_rounds": a.rounds,
        "max_risk_discuss_rounds": a.risk_rounds,
        "output_language": a.lang,
        "data_vendors": vendors,
    }
    path = write_report_tree(final_state, meta["ticker"], run, settings, html=True)
    print(json.dumps({"complete_report": str(path), "html": str(run / "complete_report.html"),
                      "rating": final_state["final_rating"]}))


if __name__ == "__main__":
    sys.exit(main())
