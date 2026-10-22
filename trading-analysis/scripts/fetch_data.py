"""Fetch every data source the TradingAgents analysts use, with no LLM key.

Calls TradingAgents' own vendor router (yfinance, StockTwits, Reddit, Polymarket,
FRED when FRED_API_KEY is set) and, for Indian listings (.NS / .BO, or a bare
NSE symbol), the keyless Indian sources in india_sources.py. Writes one markdown
file per analyst into <out>/data/. Run it with the TradingAgents venv's python:

    python fetch_data.py RELIANCE 2026-10-21 --out D:/TradingAgentsData/runs/RELIANCE.NS/2026-10-21
"""

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

DATA_ROOT = Path(os.environ.get("TRADINGAGENTS_DATA_ROOT", r"D:\TradingAgentsData"))
os.environ.setdefault("TRADINGAGENTS_CACHE_DIR", str(DATA_ROOT / "cache"))
os.environ.setdefault("TRADINGAGENTS_NO_UPDATE_CHECK", "1")

# Pick up FRED / TypeSafe settings from the repo's .env if present.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(r"C:\Users\Dell\TradingAgents\.env"))
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

import india_sources as india  # noqa: E402
from tradingagents.agents.context import build_instrument_context, resolve_instrument_identity  # noqa: E402
from tradingagents.agents.post_screen import jev_screen  # noqa: E402
from tradingagents.dataflows.config import set_config  # noqa: E402
from tradingagents.dataflows.date_window import is_historical  # noqa: E402
from tradingagents.dataflows.router import route_to_vendor  # noqa: E402
from tradingagents.dataflows.symbols import normalize_symbol  # noqa: E402
from tradingagents.dataflows.vendors.reddit import fetch_reddit_posts, subreddits_for  # noqa: E402
from tradingagents.dataflows.vendors.stocktwits import fetch_stocktwits_messages  # noqa: E402
from tradingagents.dataflows.vendors.yahoo.snapshot import build_verified_market_snapshot  # noqa: E402
from tradingagents.portfolio import load_portfolio  # noqa: E402

# The indicator menu the Market Analyst chooses from.
INDICATORS = [
    "close_50_sma", "close_200_sma", "close_10_ema",
    "macd", "macds", "macdh", "rsi",
    "boll", "boll_ub", "boll_lb", "atr", "vwma",
]
US_PREDICTION_TOPICS = ["Fed rate cut", "recession", "tariffs"]
US_MACRO_SERIES = ["fed_funds_rate", "10y_treasury", "cpi", "unemployment", "vix"]
INDIA_FRED_SERIES = ["fed_funds_rate", "10y_treasury"]  # global rate backdrop for Indian flows


def days_back(date: str, n: int) -> str:
    return (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=n)).strftime("%Y-%m-%d")


def call(label: str, fn, *args, **kwargs) -> str:
    """Run one fetch; a failure becomes a DATA_UNAVAILABLE note, never a crash."""
    try:
        result = fn(*args, **kwargs)
        text = result if isinstance(result, str) else str(result)
        print(f"  ok   {label}", file=sys.stderr)
        return text
    except Exception as exc:
        print(f"  FAIL {label}: {exc}", file=sys.stderr)
        return f"DATA_UNAVAILABLE: {label} failed ({type(exc).__name__}: {exc}). Do not fabricate values."


def section(title: str, body: str) -> str:
    return f"## {title}\n\n{body.strip()}\n\n"


def portfolio_block(path: Path, ticker: str) -> str:
    """The caller's holdings via TradingAgents' own PortfolioContext, or '' if none."""
    if not path.is_file():
        return ""
    book = load_portfolio(path)
    if india.is_indian(ticker):
        for p in book.positions:  # let the user write RELIANCE for RELIANCE.NS
            p.ticker = india.to_indian_symbol(p.ticker)
    return book.render(ticker)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", help="e.g. RELIANCE, TCS.NS, 500325.BO, NVDA")
    parser.add_argument("date", help="analysis date, YYYY-MM-DD")
    parser.add_argument("--out", required=True, help="run folder; data goes in <out>/data")
    parser.add_argument("--market", choices=["india", "us"], default="india",
                        help="how to read a bare symbol: india adds .NS (default)")
    parser.add_argument("--portfolio", default=str(DATA_ROOT / "portfolio.json"))
    args = parser.parse_args()

    raw = india.to_indian_symbol(args.ticker) if args.market == "india" else args.ticker
    ticker = normalize_symbol(raw)
    date = args.date
    out = Path(args.out)
    data_dir = out / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (out / "reports").mkdir(exist_ok=True)

    indian = india.is_indian(ticker)
    live = not is_historical(date)
    asset_type = "crypto" if ticker.endswith("-USD") else "stock"
    week_ago = days_back(date, 7)
    config = {"data_cache_dir": str(DATA_ROOT / "cache")}
    if indian:
        # SEC EDGAR only covers US filers; India-focused macro headlines.
        config["data_vendors"] = {"fundamental_data": "yfinance"}
        config["global_news_queries"] = india.INDIA_GLOBAL_NEWS_QUERIES
    set_config(config)

    print(f"Fetching {ticker} as of {date} ({'India' if indian else 'US/other'}, "
          f"{'live' if live else 'historical'}) -> {data_dir}", file=sys.stderr)

    identity = resolve_instrument_identity(ticker)  # {} when the lookup fails
    context = build_instrument_context(ticker, asset_type, identity, date)
    if indian:
        exch = "NSE" if ticker.endswith(".NS") else "BSE"
        context += (f" It is listed on the {exch} in India; prices and financials are in INR (₹), and the "
                    "benchmark is the Nifty 50 (^NSEI)" + (" / Sensex (^BSESN)" if exch == "BSE" else "") + ".")
    (data_dir / "instrument_context.md").write_text(context, encoding="utf-8")
    company = india.short_name(identity.get("company_name"), ticker)
    sector_idx = india.sector_index(identity) if indian else None

    # Market analyst
    market = f"# Market data for {ticker} as of {date}\n\n"
    market += section(
        f"OHLCV {days_back(date, 120)} to {date}",
        call("stock_data", route_to_vendor, "get_stock_data", ticker, days_back(date, 120), date),
    )
    for ind in INDICATORS:
        market += section(
            f"Indicator: {ind} (30-day window)",
            call(f"indicator {ind}", route_to_vendor, "get_indicators", ticker, ind, date, 30),
        )
    market += section(
        "Verified market snapshot (source of truth for exact numbers)",
        call("snapshot", build_verified_market_snapshot, ticker, date, 30),
    )
    if indian:
        benches = [("^NSEI", "Nifty 50")] + ([sector_idx] if sector_idx else [])
        market += section("Relative strength vs Nifty 50 and sector index",
                          call("relative strength", india.relative_strength, ticker, date, benches))
    (data_dir / "market.md").write_text(market, encoding="utf-8")

    # Fundamentals analyst
    fund = f"# Fundamentals data for {ticker} as of {date}\n\n"
    fund += section("Company fundamentals", call("fundamentals", route_to_vendor, "get_fundamentals", ticker, date))
    for method, title in (
        ("get_balance_sheet", "Balance sheet (quarterly)"),
        ("get_cashflow", "Cash flow (quarterly)"),
        ("get_income_statement", "Income statement (quarterly)"),
    ):
        fund += section(title, call(method, route_to_vendor, method, ticker, "quarterly", date))
    if indian:
        fund += section("Annual statements", call("annual statements", india.annual_statements, ticker, date))
        fund += section("Shareholding pattern (current)", call("shareholding", india.shareholding, ticker, live))
        fund += section("Upcoming corporate events", call("events", india.upcoming_events, ticker, live))
    fund += section("Insider transactions", call("insider", route_to_vendor, "get_insider_transactions", ticker, date))
    (data_dir / "fundamentals.md").write_text(fund, encoding="utf-8")

    # News analyst
    news = f"# News and macro data for {ticker} as of {date}\n\n"
    if indian:
        ticker_news = call("google news", india.company_news, company, ticker, week_ago, date)
        news += section(f"{company} news {week_ago} to {date}", ticker_news)
        news += section("Indian market dashboard (indices, VIX, INR, crude, gold)",
                        call("market dashboard", india.market_dashboard, date, sector_idx))
        news += section("Indian market headlines (past 7 days)", call("market feeds", india.market_feeds, week_ago, date, live))
        news += section("Global / macro news (Yahoo, India-focused queries)",
                        call("global_news", route_to_vendor, "get_global_news", date, None, None))
        fred_series, topics = INDIA_FRED_SERIES, []
    else:
        ticker_news = call("news", route_to_vendor, "get_news", ticker, week_ago, date)
        news += section(f"{ticker} news {week_ago} to {date}", ticker_news)
        news += section("Global / macro news (past 7 days)", call("global_news", route_to_vendor, "get_global_news", date, None, None))
        fred_series, topics = US_MACRO_SERIES, US_PREDICTION_TOPICS
    if os.environ.get("FRED_API_KEY"):
        for series in fred_series:
            news += section(f"FRED macro: {series}", call(f"fred {series}", route_to_vendor, "get_macro_indicators", series, date, None))
    elif not indian:
        news += section("FRED macro data", "DATA_UNAVAILABLE: FRED_API_KEY is not set, so no macro series were fetched. Do not fabricate values.")
    for topic in topics:
        news += section(f"Prediction markets: {topic}", call(f"polymarket {topic}", route_to_vendor, "get_prediction_markets", topic, None, date))
    (data_dir / "news.md").write_text(news, encoding="utf-8")

    # Sentiment analyst
    screen = jev_screen(ticker)
    if indian:
        st_symbol = india.base_symbol(ticker) + ".NSE"
        subs = india.INDIA_SUBREDDITS
        reddit_query = f'{india.base_symbol(ticker)} OR "{company}"'
    else:
        st_symbol, subs, reddit_query = ticker, subreddits_for(ticker), ticker
    senti = f"# Sentiment data for {ticker}, {week_ago} to {date}\n\n"
    senti += section("News headlines (past 7 days)", ticker_news)
    senti += section(
        f"StockTwits messages (${st_symbol})",
        call("stocktwits", fetch_stocktwits_messages, st_symbol, limit=30, start_date=week_ago, end_date=date, screen=screen),
    )
    senti += section(
        f"Reddit posts ({', '.join('r/' + s for s in subs)})",
        call("reddit", fetch_reddit_posts, reddit_query, subs, start_date=week_ago, end_date=date, screen=screen),
    )
    (data_dir / "sentiment.md").write_text(senti, encoding="utf-8")

    # Portfolio (optional), for the trader, risk team and portfolio manager.
    pf = call("portfolio", portfolio_block, Path(args.portfolio), ticker) if Path(args.portfolio).is_file() else ""
    (data_dir / "portfolio_context.md").write_text(
        pf or "No portfolio was provided: size against a standard allocation and do not assume any existing position.",
        encoding="utf-8")

    meta = {
        "ticker": ticker,
        "date": date,
        "market": "india" if indian else "other",
        "live": live,
        "asset_type": asset_type,
        "identity": identity,
        "search_name": company,
        "sector_index": sector_idx[0] if sector_idx else None,
        "portfolio": bool(pf),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }
    (out / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
