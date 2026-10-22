"""Why did the screen pick what it picked (or nothing)? Data, funnel, code and history checks.

    python diagnose.py [--date YYYY-MM-DD] [--history]

1. Data sanity for the day: bars present, zero volume, stale prices.
2. Funnel: how many stocks survive each rule, in order, and who is cut by the last one.
3. Independent recomputation of the regime and sector numbers (catches code bugs).
4. --history: picks per signal date under the live rules vs without the risk-off sector
   rule, and the backtest of both by regime (train / test).
"""

import argparse
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import screener as sc  # noqa: E402


def data_checks(day):
    con = sqlite3.connect(sc.DB)
    uni = pd.read_sql("SELECT symbol FROM universe WHERE active=1", con).symbol
    p = pd.read_sql("SELECT symbol, date, close, volume FROM prices WHERE date >= date(?, '-14 day')", con, params=(day,))
    today = p[p.date == day]
    missing = sorted(set(uni) - set(today.symbol))
    zero_vol = sorted(today[(today.volume <= 0) & today.symbol.isin(uni)].symbol)
    last5 = p[p.symbol.isin(uni)].sort_values("date").groupby("symbol").tail(5)
    stale = sorted(s for s, g in last5.groupby("symbol") if len(g) == 5 and g.close.nunique() == 1)
    print(f"DATA {day}: {today.symbol.isin(uni).sum()}/{len(uni)} stocks have a bar | missing: {missing[:10] or 'none'}"
          f" | zero volume: {zero_vol[:10] or 'none'} | price unchanged 5 days: {stale[:10] or 'none'}")


def funnel(x, reg, cfg):
    steps = [("universe", pd.Series(True, index=x.index))]
    for why in ["short history", "data jump in lookback", "illiquid", "low price", "circuit hit", "extended", "below falling SMA200"]:
        steps.append((f"after veto: {why}", ~x.veto.isin([w for _, w in []]) & True))
    alive = pd.Series(True, index=x.index)
    print("\nFUNNEL")
    print(f"  {'universe':45} {len(x):>4}")
    for why in ["short history", "data jump in lookback", "illiquid", "low price", "circuit hit", "extended", "below falling SMA200"]:
        alive &= x.veto != why
        print(f"  {'- ' + why:45} {int(alive.sum()):>4}")
    s = alive & (x.setups != "")
    print(f"  {'has setup A (trend template) or E (momentum)':45} {int(s.sum()):>4}   (A: {int((alive & x.setups.str.contains('A')).sum())}, E: {int((alive & x.setups.str.contains('E')).sum())})")
    s2 = s & (x.stop_pct <= cfg.max_stop_pct)
    print(f"  {'stop within 10%':45} {int(s2.sum()):>4}")
    if reg.regime == "risk-off":
        s3 = s2 & x.quadrant.isin(["Leading", "Improving"])
        print(f"  {'RISK-OFF rule: sector Leading/Improving':45} {int(s3.sum()):>4}   <- regime today: {reg.regime}")
        cut = x[s2 & ~s3].sort_values("score", ascending=False)
        if len(cut):
            print("\n  Cut ONLY by the risk-off sector rule (top 12 by score):")
            print(cut[["symbol", "industry", "quadrant", "setups", "score", "r21", "r63", "r252", "stop_pct"]].head(12)
                  .to_string(index=False, float_format=lambda v: f"{v:,.3f}"))
    print("\n  Sector quadrants:", x.groupby("quadrant").industry.unique().map(list).to_dict())


def recompute(panel, day, reg_row, sec_day):
    """Regime and one sector's RS from raw closes, independent of market_context()."""
    d = panel[panel.date <= day]
    n = d[d.symbol == sc.NIFTY].set_index("date").close
    vs200 = n.iloc[-1] / n.tail(200).mean() - 1
    st = d[~d.symbol.str.startswith("^")]
    last = st[st.date == day].set_index("symbol")
    sma50 = st.groupby("symbol").close.apply(lambda s: s.tail(50).mean() if len(s) >= 50 else np.nan)
    a50 = (last.close > sma50.reindex(last.index)).mean()
    print(f"\nRECOMPUTE regime: Nifty vs SMA200 {vs200:+.2%} (code {reg_row.nifty_vs200:+.2%}); "
          f"breadth above SMA50 {a50:.1%} (code {reg_row.a50:.1%})")
    piv = st.pivot(index="date", columns="symbol", values="close")
    r = lambda k: piv.iloc[-1] / piv.iloc[-1 - k] - 1
    nr = lambda k: n.iloc[-1] / n.iloc[-1 - k] - 1
    ind = last.industry
    for sector in ["Information Technology", "Healthcare", "Financial Services"]:
        m = ind[ind == sector].index
        rs = 0.4 * (r(21)[m].median() - nr(21)) + 0.4 * (r(63)[m].median() - nr(63)) + 0.2 * (r(126)[m].median() - nr(126))
        print(f"  {sector:24} RS {rs:+.2%} (code {sec_day.loc[sector].rs:+.2%}), quadrant {sec_day.loc[sector].quadrant}")


def history(panel, reg, sec):
    import backtest_screener as bt
    mkt = bt.Market(panel)
    dates = list(mkt.dates[300:-21])[::5]
    rows = []
    for label, cfg in (("live rules", sc.Config()), ("no risk-off sector rule", replace(sc.Config(), regime_filter=False))):
        counts = []
        for d in dates:
            x = sc.screen(panel[panel.date == d], reg.loc[d], sec.loc[d], cfg)
            counts.append(min(len(sc.pick_list(x, reg.loc[d], cfg)), int(reg.loc[d].picks)))
        c = pd.Series(counts, index=dates)
        off = reg.loc[dates].regime == "risk-off"
        print(f"\nHISTORY {label}: avg picks/date {c.mean():.1f}; dates with ZERO picks {int((c == 0).sum())}/{len(c)} "
              f"(risk-off dates: {int((c[off] == 0).sum())}/{int(off.sum())} zero)")
        t = bt.run(panel, reg, sec, mkt, cfg, dates, "regime", 20)
        t["half"] = np.where(t.date < bt.SPLIT, "train", "test")
        for (h, rg), g in t.groupby(["half", "regime"]):
            rows.append({"rules": label, "period": h, "regime": rg, **bt.stats(g)})
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print("\nBACKTEST by regime (trades, profit factor, avg %, alpha %):")
    print(out.pivot_table(index=["regime", "period"], columns="rules", values=["trades", "PF", "avg%", "alpha%"]).to_string())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--history", action="store_true")
    a = ap.parse_args()
    panel = sc.build_features()
    reg, sec = sc.market_context(panel)
    day = a.date or reg.index.max()
    data_checks(day)
    cfg = sc.Config()
    x = sc.screen(panel[panel.date == day], reg.loc[day], sec.loc[day], cfg)
    funnel(x, reg.loc[day], cfg)
    recompute(panel, day, reg.loc[day], sec.loc[day])
    if a.history:
        history(panel, reg, sec)


if __name__ == "__main__":
    main()
