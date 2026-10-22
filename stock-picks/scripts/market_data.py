"""Daily Nifty 500 price store: no LLM, no tokens.

Keeps D:\\TradingAgentsData\\market\\market.db (SQLite) up to date with daily
OHLCV for the Nifty 500 plus Indian benchmarks, fetched from Yahoo Finance.

    python market_data.py universe          # refresh the Nifty 500 list from NSE
    python market_data.py update            # fetch new bars (first run backfills 5 years)
    python market_data.py status            # coverage report
    python market_data.py cleanup           # retention rules + monthly backup
    python market_data.py daily             # universe (if stale) + update + cleanup: the scheduled job

Prices are split-adjusted and not dividend-adjusted, the same basis TradingView
charts use. A split or bonus issue rewrites a stock's whole history, so a
symbol whose overlap bars disagree with the store, or that reports a split,
is re-downloaded in full.
"""

import argparse
import io
import logging
import shutil
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd
import yfinance as yf

ROOT = Path(r"D:\TradingAgentsData")
MARKET = ROOT / "market"
DB = MARKET / "market.db"
LOGS = MARKET / "logs"
BACKUPS = MARKET / "backups"
NIFTY500_CSV = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
HISTORY_YEARS = 5
OVERLAP_DAYS = 7          # re-check the last week of stored bars on every update
ADJUST_TOLERANCE = 0.005  # a stored close off by more than 0.5% means a corporate action
CHUNK = 50
MARKET_CLOSE_IST = (15, 45)

BENCHMARKS = {
    "^NSEI": "Nifty 50", "^CRSLDX": "Nifty 500", "^BSESN": "Sensex", "^NSEBANK": "Nifty Bank",
    "^CNXIT": "Nifty IT", "^CNXPHARMA": "Nifty Pharma", "^INDIAVIX": "India VIX",
    "USDINR=X": "USD/INR", "BZ=F": "Brent crude",
}

log = logging.getLogger("market_data")


def connect() -> sqlite3.Connection:
    MARKET.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS universe (
            symbol TEXT PRIMARY KEY, company TEXT, industry TEXT, isin TEXT,
            first_seen TEXT, last_seen TEXT, active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS prices (
            symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (symbol, date)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS actions (
            symbol TEXT, date TEXT, dividend REAL, split REAL, PRIMARY KEY (symbol, date));
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    return con


def meta_get(con, key, default=None):
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def meta_set(con, key, value):
    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))
    con.commit()


def yahoo(symbol: str) -> str:
    return symbol if symbol in BENCHMARKS else f"{symbol}.NS"


# ---------- universe ----------

def refresh_universe(con) -> int:
    req = Request(NIFTY500_CSV, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as r:
        df = pd.read_csv(io.BytesIO(r.read()))
    # NSE pads the list with placeholder rows such as DUMMYHEG.
    df = df[(df["Series"] == "EQ") & ~df["Symbol"].str.startswith("DUMMY")]
    today = date.today().isoformat()
    current = set(df["Symbol"])
    for row in df.itertuples():
        con.execute("""
            INSERT INTO universe (symbol, company, industry, isin, first_seen, last_seen, active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(symbol) DO UPDATE SET company=excluded.company, industry=excluded.industry,
                isin=excluded.isin, last_seen=excluded.last_seen, active=1""",
                    (row.Symbol, row._1, row.Industry, row._5, today, today))
    # Leavers stay in the store, marked inactive: dropping them would bias backtests.
    gone = [s for (s,) in con.execute("SELECT symbol FROM universe WHERE active=1") if s not in current]
    con.executemany("UPDATE universe SET active=0 WHERE symbol=?", [(s,) for s in gone])
    meta_set(con, "universe_refreshed", today)
    con.commit()
    log.info("universe: %d active, %d marked inactive", len(current), len(gone))
    return len(current)


# ---------- prices ----------

def last_complete_day() -> date:
    """Today once NSE has closed, else yesterday: a partial bar is never stored."""
    now = datetime.now()
    return now.date() if (now.hour, now.minute) >= MARKET_CLOSE_IST else now.date() - timedelta(days=1)


def download(tickers: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
    """Yahoo bars for several tickers; {ticker: frame}, missing tickers omitted."""
    out = {}
    for attempt in range(3):
        try:
            raw = yf.download(tickers, start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
                              group_by="ticker", auto_adjust=False, actions=True,
                              threads=True, progress=False)
            break
        except Exception as exc:
            log.warning("download attempt %d failed: %s", attempt + 1, exc)
            time.sleep(5 * (attempt + 1))
    else:
        return out
    if raw is None or raw.empty:
        return out
    for t in tickers:
        try:
            f = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
        except KeyError:
            continue
        f = f.dropna(subset=["Close"])
        if not f.empty:
            out[t] = f
    return out


def store(con, symbol: str, f: pd.DataFrame):
    rows = [(symbol, d.strftime("%Y-%m-%d"), float(r.Open), float(r.High), float(r.Low),
             float(r.Close), float(r.Volume or 0)) for d, r in f.iterrows()]
    con.executemany("INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?,?)", rows)
    acts = [(symbol, d.strftime("%Y-%m-%d"), float(r.get("Dividends", 0) or 0), float(r.get("Stock Splits", 0) or 0))
            for d, r in f.iterrows() if (r.get("Dividends", 0) or 0) or (r.get("Stock Splits", 0) or 0)]
    con.executemany("INSERT OR REPLACE INTO actions VALUES (?,?,?,?)", acts)


def needs_refetch(con, symbol: str, f: pd.DataFrame) -> bool:
    """A split in the new bars, or overlap closes that moved: history is stale."""
    if "Stock Splits" in f and (f["Stock Splits"].fillna(0) > 0).any():
        return True
    stored = dict(con.execute(
        "SELECT date, close FROM prices WHERE symbol=? AND date>=?",
        (symbol, f.index[0].strftime("%Y-%m-%d"))).fetchall())
    for d, r in f.iterrows():
        old = stored.get(d.strftime("%Y-%m-%d"))
        if old and abs(float(r.Close) / old - 1) > ADJUST_TOLERANCE:
            return True
    return False


def update(con) -> dict:
    end = last_complete_day()
    full_start = end - timedelta(days=365 * HISTORY_YEARS + 10)
    symbols = [s for (s,) in con.execute("SELECT symbol FROM universe WHERE active=1")] + list(BENCHMARKS)
    last = dict(con.execute("SELECT symbol, MAX(date) FROM prices GROUP BY symbol").fetchall())

    new = [s for s in symbols if s not in last]
    existing = [s for s in symbols if s in last and last[s] < end.isoformat()]
    stats = {"backfilled": 0, "updated": 0, "refetched": 0, "missing": []}

    def run(batch, start, mode):
        tickers = [yahoo(s) for s in batch]
        got = download(tickers, start, end)
        refetch = []
        for s in batch:
            f = got.get(yahoo(s))
            if f is None:
                stats["missing"].append(s)
                continue
            if mode == "update" and needs_refetch(con, s, f):
                refetch.append(s)
                continue
            store(con, s, f)
            stats["backfilled" if mode == "full" else "updated"] += 1
        con.commit()
        return refetch

    refetch_all = []
    if existing:
        start = date.fromisoformat(min(last[s] for s in existing)) - timedelta(days=OVERLAP_DAYS)
        for i in range(0, len(existing), CHUNK):
            refetch_all += run(existing[i:i + CHUNK], start, "update")
            time.sleep(1)
    for s in refetch_all:
        con.execute("DELETE FROM prices WHERE symbol=?", (s,))
    stats["refetched"] = len(refetch_all)
    todo = new + refetch_all
    for i in range(0, len(todo), CHUNK):
        run(todo[i:i + CHUNK], full_start, "full")
        log.info("backfill %d/%d", min(i + CHUNK, len(todo)), len(todo))
        time.sleep(2)
    meta_set(con, "last_update", datetime.now().isoformat(timespec="seconds"))
    meta_set(con, "last_bar", end.isoformat())
    log.info("update: %s", {k: (v if k != "missing" else len(v)) for k, v in stats.items()})
    if stats["missing"]:
        log.warning("no Yahoo data for: %s", ", ".join(stats["missing"][:40]))
    return stats


# ---------- data quality ----------

JUMP = 0.30  # NSE price bands cap most stocks at 20% a day; a bigger one-day move is suspect


def quality_fix(con) -> list[str]:
    """Flag one-day jumps over 30% in the `suspect` table; never rewrite prices.

    Such a jump is an unadjusted split or bonus, a demerger, a Yahoo data error,
    or (rarely) a real crash, and Yahoo's split records do not reliably say
    which. Guessing a ratio once corrupted a real crash (ZEEL 2024-01-23), so
    the screener instead skips a stock while a flagged jump is in its lookback.
    """
    con.execute("CREATE TABLE IF NOT EXISTS suspect (symbol TEXT, date TEXT, ratio REAL, PRIMARY KEY (symbol, date))")
    p = pd.read_sql("SELECT symbol, date, close FROM prices ORDER BY symbol, date", con)
    p["r"] = p.groupby("symbol").close.pct_change() + 1
    jumps = p[((p.r - 1).abs() > JUMP) & ~p.symbol.isin(list(BENCHMARKS))]
    con.execute("DELETE FROM suspect")  # rebuilt each run: a refetch can clear a jump
    con.executemany("INSERT INTO suspect VALUES (?, ?, ?)",
                    [(j.symbol, j.date, float(j.r)) for j in jumps.itertuples()])
    con.commit()
    flagged = [f"{j.symbol} {j.date} {j.r - 1:+.0%}" for j in jumps.itertuples()]
    if flagged:
        log.info("flagged %d jumps >30%%: %s", len(flagged), "; ".join(flagged))
    return flagged


# ---------- housekeeping ----------

def cleanup(con):
    now = time.time()
    rules = [  # (folder, glob, max age in days)
        (ROOT / "cache", "**/*", 7),
        (LOGS, "*.log", 90),
        (ROOT / "screens" / "news", "*", 90),
    ]
    removed = 0
    for folder, pattern, days in rules:
        if folder.exists():
            for p in folder.glob(pattern):
                if p.is_file() and now - p.stat().st_mtime > days * 86400:
                    p.unlink(missing_ok=True)
                    removed += 1
    # Deep-analysis raw data is re-downloadable; the reports are kept.
    runs = ROOT / "runs"
    if runs.exists():
        for d in runs.glob("*/*/data"):
            if now - d.stat().st_mtime > 30 * 86400:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
    # Monthly backup, keep the last 3.
    BACKUPS.mkdir(parents=True, exist_ok=True)
    month = date.today().strftime("%Y%m")
    target = BACKUPS / f"market_{month}.db"
    if not target.exists():
        con.execute("PRAGMA wal_checkpoint(FULL)")
        bk = sqlite3.connect(target)
        con.backup(bk)
        bk.close()
        for old in sorted(BACKUPS.glob("market_*.db"))[:-3]:
            old.unlink()
    log.info("cleanup: removed %d items; backup %s", removed, target.name)


def status(con):
    u = con.execute("SELECT COUNT(*), SUM(active) FROM universe").fetchone()
    p = con.execute("SELECT COUNT(DISTINCT symbol), COUNT(*), MIN(date), MAX(date) FROM prices").fetchone()
    stale = con.execute("""SELECT COUNT(*) FROM universe u WHERE active=1 AND
        COALESCE((SELECT MAX(date) FROM prices p WHERE p.symbol=u.symbol), '') < ?""",
                        (meta_get(con, "last_bar", ""),)).fetchone()[0]
    size = DB.stat().st_size / 1e6 if DB.exists() else 0
    print(f"Universe: {u[0]} symbols ({u[1] or 0} active), refreshed {meta_get(con, 'universe_refreshed')}")
    print(f"Prices:   {p[0]} symbols, {p[1]:,} bars, {p[2]} to {p[3]}")
    print(f"Last update {meta_get(con, 'last_update')}, last bar {meta_get(con, 'last_bar')}, "
          f"{stale} active symbols behind")
    print(f"Database: {DB} ({size:.1f} MB)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["universe", "update", "status", "cleanup", "daily"])
    a = ap.parse_args()
    LOGS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(LOGS / f"{date.today():%Y%m%d}.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stderr)])
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    con = connect()
    if a.cmd == "universe":
        refresh_universe(con)
    elif a.cmd == "update":
        update(con)
        quality_fix(con)
    elif a.cmd == "status":
        status(con)
    elif a.cmd == "cleanup":
        cleanup(con)
    elif a.cmd == "daily":
        refreshed = meta_get(con, "universe_refreshed")
        if not refreshed or date.fromisoformat(refreshed) < date.today() - timedelta(days=7):
            try:
                refresh_universe(con)
            except Exception as exc:  # NSE blocks now and then; the old list still works
                log.warning("universe refresh failed, keeping the stored list: %s", exc)
        update(con)
        quality_fix(con)
        cleanup(con)
        con.close()
        try:  # the day's screen, so /stock-picks finds it ready
            import screener
            summary, _, _ = screener.run_day(rebuild=True)
            log.info("screen: %s", summary)
        except Exception as exc:
            log.exception("screen failed: %s", exc)
        return
    con.close()


if __name__ == "__main__":
    main()
