"""Build the day's picks page and record kept picks in the picks log (no LLM).

Merges the screener's lists with the reviewer's verdicts into
D:\\TradingAgentsData\\screens\\<date>_picks.html (TradingView chart per kept pick)
and appends kept picks to D:\\TradingAgentsData\\picks\\picks_log.csv for tracking.

    python picks_page.py [--date YYYY-MM-DD]
"""

import argparse
import html
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(r"D:\TradingAgentsData")
SCREENS = ROOT / "screens"
LOG = ROOT / "picks" / "picks_log.csv"

CSS = """
:root{--bg:#fafaf8;--fg:#1d1d1b;--muted:#6b6b66;--line:#e3e2dc;--card:#fff;--good:#1f7a4d;--bad:#b3261e;--accent:#2457c5}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe6;--muted:#a3a29b;--line:#34332f;--card:#1f1f1d;--good:#5cc28d;--bad:#ef8a80;--accent:#8fb0ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:32px 0 8px}
.sub{color:var(--muted)}.pill{display:inline-block;padding:2px 10px;border-radius:99px;font-weight:600;font-size:13px}
.off{background:color-mix(in srgb,var(--bad) 15%,transparent);color:var(--bad)}.on{background:color-mix(in srgb,var(--good) 15%,transparent);color:var(--good)}
.neutral{background:color-mix(in srgb,var(--accent) 15%,transparent);color:var(--accent)}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{color:var(--muted);font-weight:600}td.num{text-align:right;font-variant-numeric:tabular-nums}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:14px 0}
.card h3{margin:0 0 6px;font-size:17px}.levels{display:flex;flex-wrap:wrap;gap:18px;margin:10px 0}.levels div span{display:block;color:var(--muted);font-size:12px}
.levels b{font-variant-numeric:tabular-nums}.stop{color:var(--bad)}.tgt{color:var(--good)}.chart{height:420px;margin-top:10px}
.note{color:var(--muted);font-size:13px}a{color:var(--accent)}
"""


def money(v):
    return f"₹{v:,.2f}"


def hitpct(v):
    return "" if pd.isna(v) else f" (levels like this were reached within 20 days {v:.0%} of the time)"


def regime_class(r):
    return {"risk-off": "off", "risk-on": "on"}.get(r, "neutral")


def chart(sym, i):
    cid = f"tv_{i}"
    cfg = {"autosize": True, "symbol": f"BSE:{sym}", "interval": "D", "timezone": "Asia/Kolkata", "theme": "light",
           "style": "1", "locale": "in", "allow_symbol_change": True, "container_id": cid,
           "studies": ["MASimple@tv-basicstudies", "RSI@tv-basicstudies"]}
    return (f'<div class="chart" id="{cid}"></div><script>if(window.TradingView){{new TradingView.widget({json.dumps(cfg)});}}</script>'
            f'<p class="note">Chart shows the BSE listing (TradingView blocks NSE in embedded widgets). '
            f'<a href="https://www.tradingview.com/chart/?symbol=NSE:{html.escape(sym)}" target="_blank" rel="noopener">Open NSE chart on TradingView</a></p>')


def card(r, rv, i, style):
    trail = "2" if style == "swing" else "3"
    hold = "20" if style == "swing" else "60"
    rec = rv.get("recommendation", "Buy")
    return f"""<div class="card"><h3><span class="pill on">{html.escape(rec.upper())} · swing</span> {html.escape(r.symbol)} <span class="sub">· {html.escape(r.industry)} ({html.escape(r.quadrant)}) · score {r.score:.1f}</span></h3>
<div>{html.escape(rv.get('why_it_qualified', r.setup_names))}</div>
<div class="levels"><div><span>Entry (close)</span><b>{money(r.entry)}</b></div>
<div><span>Stop-loss</span><b class="stop">{money(r.stop)} (−{r.stop_pct:.1%})</b></div>
<div><span>Target 1 ({r.rr:.1f}R)</span><b class="tgt">{money(r.target)}</b></div>
<div><span>Target 2 ({(r.target2 - r.entry) / (r.entry - r.stop):.1f}R)</span><b class="tgt">{money(r.target2)}</b></div>
<div><span>Size</span><b>{html.escape(r.size)}</b></div></div>
<div class="note">Stop: {html.escape(str(r.stop_why))}. T1: {html.escape(str(r.t1_why))}{hitpct(r.t1_hit)}. T2: {html.escape(str(r.t2_why))}{hitpct(r.t2_hit)}.
{('<br>Chart patterns (context only; not predictive in backtests): ' + html.escape(r.patterns)) if isinstance(r.patterns, str) and r.patterns else ''}</div>
<div class="note">Exit the rest on the trailing stop: highest close since entry − {trail} × ATR (ATR ₹{r.atr:,.2f}); time stop {hold} trading days.
{('<br>Watch: ' + html.escape(rv['risk_note'])) if rv.get('risk_note') else ''}</div>
{chart(r.symbol, i)}</div>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    a = ap.parse_args()
    day = a.date or sorted(p.name[:10] for p in SCREENS.glob("*_review.json"))[-1]
    summary = json.loads((SCREENS / f"{day}_summary.json").read_text(encoding="utf-8"))
    review = json.loads((SCREENS / f"{day}_review.json").read_text(encoding="utf-8-sig"))
    rv = {(x["symbol"], x["list"]): x for x in review}
    lists = {"swing": pd.read_csv(SCREENS / f"{day}_swing25.csv")}  # reports are swing-only
    regime_md = (SCREENS / f"{day}_regime.md").read_text(encoding="utf-8")
    reg_rows = [line.split("|")[1:3] for line in regime_md.splitlines() if line.startswith("| ") and "Signal" not in line]

    parts, kept_rows, dropped = [], [], []
    for style, df in lists.items():
        keep = [r for r in df.itertuples() if rv.get((r.symbol, style), {}).get("verdict") == "keep"]
        for r in df.itertuples():
            v = rv.get((r.symbol, style), {})
            if v.get("verdict") != "keep":
                dropped.append((v.get("recommendation", "Wait"), r.symbol, v.get("reason", "not reviewed")))
        title = "Swing picks (hold up to 4 weeks)"
        parts.append(f"<h2>{title}</h2>")
        if not keep:
            parts.append('<p class="sub">No pick today. The rules would rather sit out than force a trade.</p>')
        for i, r in enumerate(keep):
            parts.append(card(r, rv[(r.symbol, style)], f"{style}{i}", style))
            kept_rows.append({"date": day, "list": style, "symbol": r.symbol, "industry": r.industry, "setup": r.setup_names,
                              "score": r.score, "entry_ref": r.entry, "stop": r.stop, "atr": r.atr,
                              "trail_atr": 2 if style == "swing" else 3, "max_hold": 20 if style == "swing" else 60,
                              "target1": r.target, "target2": r.target2, "size": r.size, "regime": summary["regime"],
                              "recommendation": rv[(r.symbol, style)].get("recommendation", "Buy"),
                              "reason": rv[(r.symbol, style)].get("why_it_qualified", "")})
    if dropped:
        rows = "".join(f"<tr><td><b>{html.escape(rec)}</b></td><td>{html.escape(sym)}</td><td>{html.escape(why)}</td></tr>"
                       for rec, sym, why in dropped)
        parts.append(f'<h2>Screened but not picked</h2><div class="wrap"><table><tr><th>Recommendation</th><th>Stock</th><th>Why</th></tr>{rows}</table></div>')

    sectors = (SCREENS / f"{day}_sectors.md").read_text(encoding="utf-8").splitlines()
    sec_rows = [line.strip("|").split("|") for line in sectors if line.startswith("| ") and "Sector" not in line]
    sec_html = "".join("<tr>" + "".join(f"<td>{html.escape(c.strip())}</td>" for c in row) + "</tr>" for row in sec_rows)
    reg_html = "".join(f"<tr><td>{html.escape(k.strip())}</td><td>{html.escape(v.strip())}</td></tr>" for k, v in reg_rows)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stock Picks {day}</title><style>{CSS}</style><script src="https://s3.tradingview.com/tv.js"></script></head><body><main>
<h1>Stock picks · {day}</h1>
<p class="sub">Nifty 500 screen after NSE close · <span class="pill {regime_class(summary['regime'])}">{summary['regime'].upper()}</span>
 · up to {summary['picks']} swing picks · {summary['universe']} stocks screened, {summary['with_setup']} qualified</p>
{''.join(parts)}
<h2>Market regime</h2><div class="wrap"><table><tr><th>Signal</th><th>Value</th></tr>{reg_html}</table></div>
<h2>Sectors</h2><div class="wrap"><table><tr><th>Sector</th><th>Stocks</th><th>Quadrant</th><th>RS vs Nifty</th><th>RS momentum</th><th>1M</th><th>3M</th><th>&gt; SMA50</th><th>&gt; SMA200</th></tr>{sec_html}</table></div>
<p class="note">Rules backtested Dec 2022 to Sep 2026 (see backtest_report.md): momentum ranking with trailing stops, profit factor 1.41 in training and 1.13 on the later test period, with losing years. Prices are end-of-day; entry assumes the next session's open near the close shown. Research output, not investment advice.</p>
</main></body></html>"""
    out = SCREENS / f"{day}_picks.html"
    out.write_text(page, encoding="utf-8")

    LOG.parent.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame(kept_rows)
    if LOG.exists() and not new.empty:
        old = pd.read_csv(LOG)
        old = old[~((old.date == day) & old.symbol.isin(new.symbol))]  # re-running a day replaces its rows
        new = pd.concat([old, new], ignore_index=True)
    if not new.empty:
        new.to_csv(LOG, index=False)
    print(json.dumps({"page": str(out), "kept": [(k["recommendation"], k["symbol"]) for k in kept_rows],
                      "dropped": [(rec, sym) for rec, sym, _ in dropped], "log": str(LOG)}))


if __name__ == "__main__":
    main()
