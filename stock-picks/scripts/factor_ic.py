"""Which screener factors actually predict forward returns? (no LLM)

For each signal date, the rank correlation (Spearman IC) between a factor and every
eligible stock's forward return (next open to the close `hold` days later).
A factor worth weighting has a mean IC above zero in BOTH periods and a t-stat
above about 2. Used to set and re-check the score weights (Phase 4 re-tuning).

    python factor_ic.py [--hold 15] [--every 5]
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import screener as sc  # noqa: E402
from backtest_screener import SPLIT, Market  # noqa: E402

FACTORS = {
    "score (current)": lambda x: x.score,
    "RS percentile (3-12m)": lambda x: x.rs_pct,
    "return 1m": lambda x: x.r21,
    "return 3m": lambda x: x.r63,
    "return 6m": lambda x: x.r126,
    "return 12m": lambda x: x.r252,
    "return 12m skip 1m": lambda x: (1 + x.r252) / (1 + x.r21) - 1,
    "near 52w high": lambda x: x.close / x.hi52,
    "above SMA200": lambda x: x.close / x.sma200,
    "SMA50 slope": lambda x: x.sma50_slope,
    "ADX": lambda x: x.adx,
    "RSI": lambda x: x.rsi,
    "volume ratio": lambda x: x.vol_ratio,
    "up/down volume": lambda x: x.updown_vol,
    "OBV slope": lambda x: x.obv_slope,
    "low volatility (-ATR%)": lambda x: -x.atr_pct,
    "extension (ATR above EMA20)": lambda x: x.ext_atr,
    "TV technical rating": lambda x: x.tv_rating,
    "sector strength": lambda x: x.sector_pct,
    "tight base (-range)": lambda x: -x.base_range,
    "1-week reversal (-r5)": lambda x: -x.r5,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=int, default=15)
    ap.add_argument("--every", type=int, default=5)
    a = ap.parse_args()
    panel = sc.build_features()
    reg, sec = sc.market_context(panel)
    mkt = Market(panel)
    dates = list(mkt.dates[300:-a.hold - 1])[::a.every]
    rows = []
    for d in dates:
        x = sc.screen(panel[panel.date == d], reg.loc[d], sec.loc[d], sc.Config())
        x = x[x.veto.isin(["", "below falling SMA200", "extended"])]  # liquid, clean data
        i = mkt.pos[d]
        fwd = mkt.c.iloc[i + a.hold] / mkt.o.iloc[i + 1] - 1
        x = x.assign(fwd=x.symbol.map(fwd)).dropna(subset=["fwd"])
        for name, f in FACTORS.items():
            v = f(x)
            ok = v.notna()
            if ok.sum() > 50:
                rows.append({"date": d, "factor": name, "regime": reg.loc[d].regime,
                             "ic": v[ok].rank().corr(x.fwd[ok].rank())})
    ic = pd.DataFrame(rows)
    ic["period"] = np.where(ic.date < SPLIT, "train", "test")
    t = lambda s: s.mean() / s.std() * np.sqrt(len(s))
    out = ic.groupby(["factor", "period"]).ic.agg(["mean", t]).unstack("period")
    out.columns = [f"{p} {m}" for m, p in out.columns]
    out = out[["train mean", "train <lambda_0>", "test mean", "test <lambda_0>"]]
    out.columns = ["train IC", "train t", "test IC", "test t"]
    pd.set_option("display.width", 200)
    print(f"Forward {a.hold}-day rank IC, {len(dates)} dates (train < {SPLIT} <= test)\n")
    print(out.sort_values("train IC", ascending=False).round(3).to_string())
    by_reg = ic.groupby(["factor", "regime"]).ic.mean().unstack().round(3)
    print("\nMean IC by regime (all dates):\n", by_reg.sort_values("risk-on", ascending=False).to_string())


if __name__ == "__main__":
    main()
