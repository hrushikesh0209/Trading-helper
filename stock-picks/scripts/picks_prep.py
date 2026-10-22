"""Prepare the reviewer's one-page brief for a screened day (no LLM).

Reads the screener's files for the day, then fetches headlines (Google News India,
last 7 days) and the results calendar for the shortlisted stocks only, and writes
D:\\TradingAgentsData\\screens\\<date>_shortlist.md: everything the /stock-picks
reviewer needs, in one compact file.

    python picks_prep.py [--date YYYY-MM-DD]
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import india_sources as india  # noqa: E402

ROOT = Path(r"D:\TradingAgentsData")
SCREENS = ROOT / "screens"
NEWS = SCREENS / "news"
DB = ROOT / "market" / "market.db"


def latest_day() -> str:
    days = sorted(p.name[:10] for p in SCREENS.glob("*_summary.json"))
    if not days:
        sys.exit("No screen found: run screener.py (or market_data.py daily) first.")
    return days[-1]


def fmt(v, nd=2):
    return "" if pd.isna(v) else f"{v:,.{nd}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    a = ap.parse_args()
    day = a.date or latest_day()
    summary = json.loads((SCREENS / f"{day}_summary.json").read_text(encoding="utf-8"))
    swing = pd.read_csv(SCREENS / f"{day}_swing25.csv")
    live = datetime.strptime(day, "%Y-%m-%d").date() >= (datetime.now().date() - timedelta(days=4))
    names = dict(sqlite3.connect(DB).execute("SELECT symbol, company FROM universe").fetchall())
    week_ago = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    NEWS.mkdir(parents=True, exist_ok=True)

    out = [f"# Shortlist brief {day}\n",
           (SCREENS / f"{day}_regime.md").read_text(encoding="utf-8").replace("# ", "## ", 1),
           "## Sectors (top 5 and bottom 3 by RS)\n"]
    sec_lines = (SCREENS / f"{day}_sectors.md").read_text(encoding="utf-8").splitlines()
    table = [line for line in sec_lines if line.startswith("|")]
    out += table[:2] + table[2:7] + table[-3:] + [""]
    out.append(f"Screen summary: {summary['universe']} stocks screened, {summary['with_setup']} with a qualifying setup, "
               f"{summary['swing_list']} on the swing list. Regime allows up to {summary['picks']} swing picks.\n")
    tm = summary.get("timing")
    if tm and not tm["take_entries"]:
        out.append("**MARKET TIMING SAYS STAND ASIDE: no new entries today.** Every candidate below is a Wait "
                   "(watchlist only), whatever its news; it can become a Buy once RSRS turns back on.\n")

    for title, df in (("Swing candidates (hold up to 20 trading days; stop trails at highest close − 2 × ATR)", swing),):
        out.append(f"## {title}\n")
        if df.empty:
            out.append("_None today._\n")
            continue
        out.append("| # | Symbol | Company | Sector (quadrant) | Setup | Score | Entry ₹ | Stop ₹ (risk) | Target 1 ₹ (R) | Target 2 ₹ (R) | Size | RSI | 1M | 12M |")
        out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for i, r in enumerate(df.itertuples(), 1):
            rr2 = (r.target2 - r.entry) / (r.entry - r.stop)
            out.append(f"| {i} | {r.symbol} | {names.get(r.symbol, '')} | {r.industry} ({r.quadrant}) | {r.setup_names} | {r.score:.1f} "
                       f"| {fmt(r.entry)} | {fmt(r.stop)} ({r.stop_pct:.1%}) | {fmt(r.target)} ({r.rr:.1f}R) | {fmt(r.target2)} ({rr2:.1f}R) | {r.size} "
                       f"| {r.rsi:.0f} | {r.r21:+.1%} | {r.r252:+.1%} |")
        out.append("\nWhere the levels come from (technical structure; % = how often that kind of level at that distance "
                   "was reached within 20 trading days in the 2022-25 calibration):\n")
        pct = lambda v: "" if pd.isna(v) else f", reached {v:.0%} of the time"
        for r in df.itertuples():
            pats = f" Recent chart patterns: {r.patterns}." if isinstance(r.patterns, str) and r.patterns else ""
            out.append(f"- **{r.symbol}**: stop {r.stop_why}; T1 {r.t1_why}{pct(r.t1_hit)}; T2 {r.t2_why}{pct(r.t2_hit)}.{pats}")
        out.append("")

    out.append("## News and events per candidate\n")
    for sym in dict.fromkeys(swing.symbol):
        company = india.short_name(names.get(sym), sym + ".NS")
        news = india.company_news(company, sym + ".NS", week_ago, day, limit=10)
        events = india.upcoming_events(sym + ".NS", live)
        (NEWS / f"{day}_{sym}.md").write_text(f"{news}\n\n{events}\n", encoding="utf-8")
        out.append(f"### {sym} ({company})\n\nEvents: {events.replace(chr(10), '; ')}\n\n{news}\n")
        print(f"  {sym}: news and events fetched", file=sys.stderr)

    path = SCREENS / f"{day}_shortlist.md"
    path.write_text("\n".join(out), encoding="utf-8")
    print(json.dumps({"date": day, "brief": str(path), "swing": len(swing),
                      "max_swing_picks": summary["picks"], "live": live}))


if __name__ == "__main__":
    main()
