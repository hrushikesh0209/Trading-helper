"""Measure how each level type behaves, on the TRAINING period only (no LLM).

For eligible uptrend stocks every 5 trading days before the train/test split:
- support of type T at distance d (in ATR) "held" if no low in the next 20 bars went
  below it by more than 0.5 ATR (a stop placed there survived);
- resistance of type T at distance d was "reached" if a high in the next 20 bars touched it;
- baseline: the same two questions for an ordinary price at fixed ATR distances.
Writes market\\level_stats.json, which levels.py (adaptive mode) reads.

    python calibrate_levels.py
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import levels as lv  # noqa: E402
import patterns as pt  # noqa: E402
import screener as sc  # noqa: E402
from backtest_screener import SPLIT  # noqa: E402

FWD = 20
BASE_D = [1.25, 1.75, 2.25, 2.75, 3.5, 4.5, 5.75, 7.25, 10.0, 14.0]


def main():
    panel = sc.build_features()
    stocks = panel[~panel.symbol.str.startswith("^")]
    days = sorted(panel[panel.symbol == sc.NIFTY].date)
    sample = set([d for d in days[300:] if d < SPLIT][::5])
    sup, res = {}, {}
    def add(tab, typ, b, ok):
        cell = tab.setdefault(typ, {}).setdefault(b, [0, 0])
        cell[0] += 1
        cell[1] += int(ok)
    n_samples = 0
    for sym, d in stocks.groupby("symbol", sort=False):
        d = d.sort_values("date").reset_index(drop=True)
        o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        atr = d.atr.to_numpy(float)
        dates = d.date.to_numpy()
        weeks = lv.week_ids(dates)
        events = pt.scan(o, h, l, c, atr)
        elig = ((d.traded_value >= 1e8) & (d.bars >= sc.MIN_BARS) & (d.close >= 50) & (d.close > d.sma200)
                & ~(d.bars_since_jump < sc.JUMP_LOOKBACK)).to_numpy()
        for i in np.flatnonzero(elig & d.date.isin(sample).to_numpy()):
            if i + FWD >= len(c):
                continue
            a, e = atr[i], c[i]
            lo_f, hi_f = np.nanmin(l[i + 1:i + FWD + 1]), np.nanmax(h[i + 1:i + FWD + 1])
            ev = [(k, p) for k, p in events if i - 10 <= k <= i]
            S, R = lv.candidates(dates, h, l, c, i, a, d.ema20[i], d.sma50[i], d.prior_high_close20[i], weeks, ev)
            ctx = lv.context(h, c, i, a)
            cs, cr = sup.setdefault(ctx, {}), res.setdefault(ctx, {})
            for p, typ, _ in S:
                dist = (e - p) / a
                if 0.5 <= dist <= 12:
                    add(cs, typ, lv.bucket(dist), lo_f > p - 0.5 * a)
            for p, typ, _ in R:
                dist = (p - e) / a
                if 0.5 <= dist <= 15:
                    add(cr, typ, lv.bucket(dist), hi_f >= p)
            for dd in BASE_D:
                add(cs, "baseline", lv.bucket(dd), lo_f > e - dd * a - 0.5 * a)
                add(cr, "baseline", lv.bucket(dd), hi_f >= e + dd * a)
            n_samples += 1
    out = {"period": f"train, before {SPLIT}", "forward_bars": FWD, "samples": n_samples,
           "support": sup, "resistance": res}
    lv.STATS.write_text(json.dumps(out, indent=1))
    print(f"{n_samples:,} stock-days calibrated -> {lv.STATS}")
    buckets = [lv.bucket(x) for x in BASE_D]
    for name, full in (("SUPPORTS: share that held", sup), ("RESISTANCES: share reached in 20 days", res)):
        for ctx, tab in sorted(full.items()):
            print(f"\n{name} | context: {ctx} (n>=50), vs an ordinary price at the same distance")
            print(f"{'type':22}" + "".join(f"{b:>9}" for b in buckets))
            for typ in ["baseline"] + sorted(t for t in tab if t != "baseline"):
                row = ""
                for b in buckets:
                    cell = tab.get(typ, {}).get(b)
                    row += f"{(cell[1] / cell[0]):>9.0%}" if cell and cell[0] >= 50 else f"{'·':>9}"
                print(f"{typ:22}{row}")


if __name__ == "__main__":
    main()
