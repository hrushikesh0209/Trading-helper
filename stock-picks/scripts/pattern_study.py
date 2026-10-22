"""Do chart and candlestick patterns predict anything in Indian stocks? (no LLM)

Scans every Nifty 500 stock's history with patterns.py (look-ahead free), then
measures each event's forward return (next open to the close `hold` days later)
in excess of the median eligible stock on the same day, so market moves cancel
out. Chart patterns also report how often their measured-move target was reached
before their invalidation level. Train / test split as in backtest_screener.

    python pattern_study.py [--hold 15]

Writes market\\pattern_events.pkl (used by levels calibration) and prints the tables.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import patterns as pt  # noqa: E402
import screener as sc  # noqa: E402
from backtest_screener import SPLIT  # noqa: E402

OUT = sc.ROOT / "market" / "pattern_events.pkl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=int, default=15)
    ap.add_argument("--report-only", action="store_true", help="re-print tables from the saved events")
    a = ap.parse_args()
    H = a.hold
    if a.report_only:
        return report(pd.read_pickle(OUT), H)
    panel = sc.build_features()
    stocks = panel[~panel.symbol.str.startswith("^")]
    fwd_rows, events = [], []
    for sym, d in stocks.groupby("symbol", sort=False):
        d = d.sort_values("date")
        o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        atr = d.atr.to_numpy(float)
        dates = d.date.to_numpy()
        ok = ((d.traded_value >= 1e8) & ~(d.bars_since_jump < sc.JUMP_LOOKBACK)).to_numpy()
        up = (d.close > d.sma200).to_numpy()
        near_sup = ((np.abs(d.low - d.ema20) <= 0.5 * d.atr) | (np.abs(d.low - d.sma50) <= 0.5 * d.atr)).to_numpy()
        n = len(c)
        fwd = np.full(n, np.nan)
        fwd[:n - H - 1] = c[H + 1:n] / o[1:n - H] - 1  # enter next open, hold H bars
        fwd_rows.append(pd.DataFrame({"date": dates, "fwd": fwd, "ok": ok}))
        for i, p in pt.scan(o, h, l, c, atr):
            if not ok[i] or np.isnan(fwd[i]):
                continue
            hit = None
            if p["dir"] == 1:  # target before invalidation within 20 bars?
                hit = "neither"
                for k in range(i + 1, min(i + 21, n)):
                    if l[k] <= p["invalid"]:
                        hit = "invalid"; break
                    if h[k] >= p["target"]:
                        hit = "target"; break
            events.append({"symbol": sym, "date": dates[i], "kind": "chart", "pattern": p["name"], "dir": p["dir"],
                           "uptrend": up[i], "at_support": near_sup[i], "fwd": fwd[i], "hit": hit,
                           "target_atr": abs(p["target"] - c[i]) / atr[i], "invalid_atr": abs(c[i] - p["invalid"]) / atr[i]})
        for name, mask in pt.candle_signals(o, h, l, c).items():
            bull = name in {v[0] for v in pt.CANDLES.values()}
            for i in np.flatnonzero(mask & ok & ~np.isnan(fwd)):
                events.append({"symbol": sym, "date": dates[i], "kind": "candle", "pattern": name, "dir": 1 if bull else -1,
                               "uptrend": up[i], "at_support": near_sup[i], "fwd": fwd[i], "hit": None,
                               "target_atr": np.nan, "invalid_atr": np.nan})
    base = pd.concat(fwd_rows)
    # Like-for-like baselines: stock returns are right-skewed, so an event's MEAN must be
    # compared with the day's MEAN (a mean-vs-median comparison flatters every pattern,
    # bearish ones included), and its median with the day's median.
    day = base[base.ok].groupby("date").fwd
    mean, med = day.mean(), day.median()
    ev = pd.DataFrame(events)
    ev["excess"] = ev.fwd - ev.date.map(mean)
    ev["excess_med"] = ev.fwd - ev.date.map(med)
    ev["period"] = np.where(ev.date < SPLIT, "train", "test")
    ev.to_pickle(OUT)

    print(f"{len(ev):,} events saved to {OUT}")
    report(ev, H)


def _summ(g):
    t = g.excess.mean() / g.excess.std() * np.sqrt(len(g)) if len(g) > 2 else np.nan
    r = {"n": len(g), "excess%": round(100 * g.excess.mean(), 2), "t": round(t, 1),
         "median excess%": round(100 * g.excess_med.median(), 2),
         "beat%": round(100 * (g.excess_med > 0).mean(), 1)}  # share beating the day's median stock
    if g.hit.notna().any():
        r["target first%"] = round(100 * (g.hit == "target").mean(), 1)
    return r


def _table(ev, keys, cols):
    rows = [{**dict(zip(keys, k if isinstance(k, tuple) else (k,))), **_summ(g)} for k, g in ev.groupby(keys)]
    t = pd.DataFrame(rows)
    wide = t.pivot_table(index=[k for k in keys if k != "period"], columns="period", values=[c for c in cols if c in t])
    wide.columns = [f"{p} {m}" for m, p in wide.columns]
    order = [f"{p} {m}" for p in ("train", "test") for m in cols if f"{p} {m}" in wide.columns]
    return wide[order]


def report(ev, H):
    pd.set_option("display.width", 220)
    for kind in ("chart", "candle"):
        tab = _table(ev[ev.kind == kind], ["pattern", "period"], ["n", "excess%", "t", "median excess%", "beat%", "target first%"])
        print(f"\n=== {kind} patterns: {H}-day excess return vs the median stock that day ===")
        print(tab.sort_values("train excess%", ascending=False).to_string())
    print("\nBullish events by context: uptrend = close > SMA200; at_support = low within 0.5 ATR of EMA20 or SMA50")
    print(_table(ev[ev.dir == 1], ["kind", "uptrend", "at_support", "period"], ["n", "excess%", "t"]).to_string())


if __name__ == "__main__":
    main()
