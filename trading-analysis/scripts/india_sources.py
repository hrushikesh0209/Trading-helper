"""Keyless Indian-market data sources that TradingAgents' own vendors don't cover.

Every fetcher returns a markdown string, never raises, and keeps to the
analysis window: a historical run never sees anything published after it.
"""

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

import yfinance as yf

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TradingAgents-ClaudeCode"

# Live-only market feeds (no archive): served for a current-date run only.
MARKET_FEEDS = {
    "Economic Times Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Mint Markets": "https://www.livemint.com/rss/markets",
    "Business Standard Markets": "https://www.business-standard.com/rss/markets-106.rss",
    "Moneycontrol Market Reports": "https://www.moneycontrol.com/rss/marketreports.xml",
}

MARKET_INDICES = {
    "^NSEI": "Nifty 50",
    "^BSESN": "Sensex",
    "^NSEBANK": "Nifty Bank",
    "^INDIAVIX": "India VIX",
    "USDINR=X": "USD/INR",
    "BZ=F": "Brent crude (USD)",
    "GC=F": "Gold (USD)",
}

# Yahoo sector / industry -> the NSE sector benchmark that best tracks it. Yahoo
# keeps full history for only some sector indices (^CNXAUTO, ^CNXENERGY and
# others return a few days), so those sectors use an ETF on the same index.
_INDUSTRY_INDEX = [
    (r"bank", "^NSEBANK", "Nifty Bank"),
    (r"auto", "AUTOBEES.NS", "Nifty Auto (ETF)"),
    (r"real estate", "MOREALTY.NS", "Nifty Realty (ETF)"),
    (r"steel|metal|aluminum|copper|mining", "METALIETF.NS", "Nifty Metal (ETF)"),
    (r"drug|pharma|biotech", "^CNXPHARMA", "Nifty Pharma"),
    (r"oil|gas", "OILIETF.NS", "Nifty Oil & Gas (ETF)"),
]
_SECTOR_INDEX = {
    "Technology": ("^CNXIT", "Nifty IT"),
    "Financial Services": ("FINIETF.NS", "Nifty Financial Services (ETF)"),
    "Energy": ("OILIETF.NS", "Nifty Oil & Gas (ETF)"),
    "Utilities": ("CPSEETF.NS", "Nifty CPSE (ETF)"),
    "Consumer Defensive": ("FMCGIETF.NS", "Nifty FMCG (ETF)"),
    "Consumer Cyclical": ("CONSUMBEES.NS", "Nifty India Consumption (ETF)"),
    "Healthcare": ("HEALTHIETF.NS", "Nifty Healthcare (ETF)"),
    "Basic Materials": ("METALIETF.NS", "Nifty Metal (ETF)"),
    "Real Estate": ("MOREALTY.NS", "Nifty Realty (ETF)"),
    "Industrials": ("INFRABEES.NS", "Nifty Infrastructure (ETF)"),
}

INDIA_GLOBAL_NEWS_QUERIES = [
    "RBI monetary policy repo rate India inflation",
    "Nifty Sensex stock market India FII",
    "India economy GDP growth",
    "crude oil prices rupee",
    "US Federal Reserve global markets",
]

INDIA_SUBREDDITS = ("IndianStreetBets", "IndiaInvestments", "StockMarketIndia", "IndianStockMarket")


def is_indian(ticker: str) -> bool:
    return ticker.upper().endswith((".NS", ".BO"))


def to_indian_symbol(raw: str) -> str:
    """A bare NSE symbol (RELIANCE) gets the .NS suffix Yahoo needs."""
    s = raw.strip().upper()
    if "." in s or "-" in s or "=" in s or s.startswith("^"):
        return s
    return s + ".NS"


def base_symbol(ticker: str) -> str:
    return ticker.upper().rsplit(".", 1)[0]


def short_name(company: str | None, ticker: str) -> str:
    """'Reliance Industries Limited' -> 'Reliance Industries' for searching."""
    if not company:
        return base_symbol(ticker)
    name = re.sub(r"\b(Limited|Ltd\.?|Corporation|Corp\.?|Inc\.?|Co\.?)\s*$", "", company.strip(), flags=re.I)
    return name.strip(" ,.") or company


def sector_index(identity: dict) -> tuple[str, str] | None:
    industry = (identity.get("industry") or "").lower()
    for pattern, symbol, name in _INDUSTRY_INDEX:
        if re.search(pattern, industry):
            return symbol, name
    return _SECTOR_INDEX.get(identity.get("sector") or "")


def _get(url: str, timeout: float = 15.0) -> bytes:
    req = Request(url, headers={"User-Agent": _UA})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _clean(text: str | None, limit: int = 300) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _rss_items(raw: bytes) -> list[dict]:
    root = ET.fromstring(raw)
    items = []
    for it in root.iter("item"):
        pub = it.findtext("pubDate")
        try:
            when = parsedate_to_datetime(pub) if pub else None
        except (TypeError, ValueError):
            when = None
        source = it.find("source")
        items.append({
            "title": _clean(it.findtext("title"), 200),
            "summary": _clean(it.findtext("description")),
            "when": when,
            "source": source.text if source is not None else None,
        })
    return items


def _in_window(when, start: datetime, end: datetime) -> bool:
    if when is None:
        return False
    day = when.date() if hasattr(when, "date") else when
    return start.date() <= day <= end.date()


def _fmt_items(items: list[dict], show_summary: bool = True) -> str:
    lines = []
    for it in items:
        date = it["when"].strftime("%Y-%m-%d") if it["when"] else "?"
        src = f" ({it['source']})" if it.get("source") else ""
        lines.append(f"- [{date}] {it['title']}{src}")
        if show_summary and it["summary"] and it["summary"] not in it["title"]:
            lines.append(f"  {it['summary']}")
    return "\n".join(lines)


def company_news(company: str, ticker: str, start_date: str, end_date: str, limit: int = 25) -> str:
    """Google News (India edition) articles about the company inside the window."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    before = (end + timedelta(days=1)).strftime("%Y-%m-%d")
    q = f'"{company}" after:{start_date} before:{before}'
    url = f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        items = _rss_items(_get(url))
    except Exception as exc:
        return f"DATA_UNAVAILABLE: Google News fetch failed ({type(exc).__name__}). This is not an absence of news; do not fabricate."
    items = [i for i in items if _in_window(i["when"], start, end)]
    if not items:
        return f"<no Google News articles found for \"{company}\" within {start_date}..{end_date}>"
    items.sort(key=lambda i: i["when"], reverse=True)
    # Google News descriptions repeat the title, so show titles and sources only.
    return f"Google News India, \"{company}\", {start_date} to {end_date} ({len(items[:limit])} articles):\n\n" + _fmt_items(items[:limit], show_summary=False)


def market_feeds(start_date: str, end_date: str, live: bool, per_feed: int = 12) -> str:
    """Indian market headlines from ET, Mint, Business Standard and Moneycontrol."""
    if not live:
        return ("<Indian market RSS feeds withheld: they serve only the latest headlines, with no archive, "
                f"so they would leak post-{end_date} information into this analysis>")
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    blocks = []
    for name, url in MARKET_FEEDS.items():
        try:
            items = [i for i in _rss_items(_get(url)) if _in_window(i["when"], start, end)]
        except Exception as exc:
            blocks.append(f"### {name}\n<unavailable: {type(exc).__name__}>")
            continue
        items.sort(key=lambda i: i["when"], reverse=True)
        blocks.append(f"### {name}\n" + (_fmt_items(items[:per_feed]) if items else "<no headlines in window>"))
    return "\n\n".join(blocks)


def _closes(symbol: str, end_date: str, days: int = 400):
    end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    start = end - timedelta(days=days)
    h = yf.Ticker(symbol).history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"), auto_adjust=True)
    return h["Close"].dropna()


def _ret(closes, sessions: int) -> str:
    if len(closes) <= sessions:
        return "n/a"
    return f"{(closes.iloc[-1] / closes.iloc[-1 - sessions] - 1) * 100:+.1f}%"


def market_dashboard(end_date: str, extra: tuple[str, str] | None = None) -> str:
    """Level and 1w/1m/3m/6m/1y change for Indian indices, INR, crude and gold."""
    rows = ["| Instrument | Last close | Date | 1W | 1M | 3M | 6M | 1Y |", "|---|---|---|---|---|---|---|---|"]
    symbols = dict(MARKET_INDICES)
    if extra:
        symbols[extra[0]] = extra[1] + " (sector index)"
    for symbol, name in symbols.items():
        try:
            c = _closes(symbol, end_date)
            if c.empty:
                raise ValueError("no data")
            rows.append(f"| {name} (`{symbol}`) | {c.iloc[-1]:,.2f} | {c.index[-1].strftime('%Y-%m-%d')} | "
                        f"{_ret(c, 5)} | {_ret(c, 21)} | {_ret(c, 63)} | {_ret(c, 126)} | {_ret(c, 250)} |")
        except Exception as exc:
            rows.append(f"| {name} (`{symbol}`) | unavailable ({type(exc).__name__}) | | | | | | |")
    return "\n".join(rows)


def relative_strength(ticker: str, end_date: str, benchmarks: list[tuple[str, str]]) -> str:
    """The stock's returns against Nifty 50 and its sector index over the same sessions."""
    try:
        stock = _closes(ticker, end_date)
    except Exception as exc:
        return f"DATA_UNAVAILABLE: price history for {ticker} ({type(exc).__name__})"
    rows = ["| Window | " + ticker + " | " + " | ".join(n for _, n in benchmarks) + " |",
            "|---|---|" + "---|" * len(benchmarks)]
    series = []
    for symbol, _ in benchmarks:
        try:
            series.append(_closes(symbol, end_date))
        except Exception:
            series.append(None)
    for label, n in (("1 week", 5), ("1 month", 21), ("3 months", 63), ("6 months", 126), ("1 year", 250)):
        cells = [_ret(stock, n)] + [(_ret(s, n) if s is not None else "n/a") for s in series]
        rows.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def shareholding(ticker: str, live: bool) -> str:
    """Promoter/insider and institutional holding: today's figures, so live runs only."""
    if not live:
        return "<shareholding withheld: Yahoo serves only the current pattern, not the one on the analysis date>"
    try:
        mh = yf.Ticker(ticker).major_holders
        if mh is None or mh.empty:
            return "<no shareholding data on Yahoo>"
        v = mh["Value"].to_dict()
        pct = lambda k: f"{v[k] * 100:.2f}%" if k in v else "n/a"
        return (f"- Promoters / insiders: {pct('insidersPercentHeld')} (for Indian companies Yahoo's 'insiders' is mostly the promoter group)\n"
                f"- Institutions (FII + DII + MFs): {pct('institutionsPercentHeld')} of shares, {pct('institutionsFloatPercentHeld')} of free float\n"
                f"- Institutional holders counted: {int(v.get('institutionsCount', 0))}")
    except Exception as exc:
        return f"DATA_UNAVAILABLE: shareholding ({type(exc).__name__})"


def annual_statements(ticker: str, end_date: str) -> str:
    """Annual income statement and cash flow (Indian quarterly data on Yahoo is sparse)."""
    cutoff = datetime.strptime(end_date, "%Y-%m-%d")
    t = yf.Ticker(ticker)
    out = []
    for title, df in (("Annual income statement", t.income_stmt), ("Annual cash flow", t.cashflow)):
        try:
            # A fiscal year's figures are published ~2 months after it closes.
            cols = [c for c in df.columns if c + timedelta(days=60) <= cutoff]
            if not cols:
                out.append(f"### {title}\n<none published by {end_date}>")
                continue
            out.append(f"### {title} (INR, fiscal years ending March)\n" + df[cols].dropna(how="all").to_csv())
        except Exception as exc:
            out.append(f"### {title}\nDATA_UNAVAILABLE ({type(exc).__name__})")
    return "\n\n".join(out)


def upcoming_events(ticker: str, live: bool) -> str:
    if not live:
        return "<event calendar withheld for a historical date>"
    try:
        cal = yf.Ticker(ticker).calendar or {}
        lines = []
        for key in ("Earnings Date", "Ex-Dividend Date", "Dividend Date"):
            if cal.get(key):
                val = cal[key]
                val = ", ".join(str(d) for d in val) if isinstance(val, list) else str(val)
                lines.append(f"- {key}: {val}")
        for key in ("Earnings Average", "Revenue Average"):
            if cal.get(key):
                lines.append(f"- Consensus {key.split()[0].lower()} estimate for next results: {cal[key]:,.2f}")
        return "\n".join(lines) or "<no upcoming events listed>"
    except Exception as exc:
        return f"DATA_UNAVAILABLE: event calendar ({type(exc).__name__})"
