"""Portfolio-level backtest of the live rules: equity curve, CAGR, Sharpe, drawdown (no LLM).

Per-trade statistics hide what a real account feels: overlapping positions, a
cash limit, and the depth of the worst losing stretch. This replays the live
picks day by day the way the playbook sizes them (risk 1% of equity per trade
above 60% breadth, else 0.5%; weight capped at 20%; at most 10 positions; never
more than 100% invested; 0.25% round-trip costs) and reports quantstats-style
metrics against the Nifty 50. Idea from the portfolio-analytics tools in
wangzhe3224/awesome-systematic-trading (quantstats, pyfolio, ffn).

    python backtest_screener.py --portfolio
"""

import numpy as np
import pandas as pd

import screener as sc

COST = 0.0025
RF = 0.065  # Indian risk-free rate (approx. 91-day T-bill), for the Sharpe ratio


def trades_with_paths(panel, reg, sec, mkt, cfg, dates, hold=20):
    rows = []
    for d in dates:
        x = sc.screen(panel[panel.date == d], reg.loc[d], sec.loc[d], cfg)
        picks = sc.pick_list(x, reg.loc[d], cfg)
        for p in picks.head(int(reg.loc[d].picks)).itertuples():
            t = mkt.trade(p.symbol, d, p.stop, p.target, hold, cfg.trail_atr, p.atr)
            if t:
                i = mkt.pos[d]
                rows.append({"date": d, "symbol": p.symbol, "i_in": i + 1, "i_out": i + t["days"], "ret": t["ret"],
                             "stop_pct": float(p.stop_pct), "a50": float(reg.loc[d].a50)})
    return pd.DataFrame(rows)


def simulate(trades, mkt, start=None, end=None, max_pos=10, max_w=0.20):
    o, c, dates = mkt.o, mkt.c, mkt.dates
    lo = 0 if start is None else int(np.searchsorted(dates, start))
    hi = len(dates) - 1 if end is None else int(np.searchsorted(dates, end))
    eq, cash, held, exposure = [], 1.0, [], []
    by_entry = trades.groupby("i_in")
    for k in range(lo, hi + 1):
        if k in by_entry.groups:
            for t in by_entry.get_group(k).itertuples():
                value = cash + sum(p["sh"] * c[p["sym"]].iloc[k - 1] for p in held)
                w = min((0.01 if t.a50 > 0.6 else 0.005) / max(t.stop_pct, 1e-4), max_w)
                if len(held) >= max_pos or w * value > cash:
                    continue
                px = o[t.symbol].iloc[k]
                cost = w * value
                held.append({"sym": t.symbol, "sh": cost * (1 - COST / 2) / px, "out": t.i_out,
                             "exit_px": px * (1 + t.ret + COST)})
                cash -= cost
        keep = []
        for p in held:
            if k >= p["out"]:
                cash += p["sh"] * p["exit_px"] * (1 - COST / 2)
            else:
                keep.append(p)
        held = keep
        mtm = sum(p["sh"] * (c[p["sym"]].iloc[k] if not np.isnan(c[p["sym"]].iloc[k]) else p["exit_px"]) for p in held)
        eq.append(cash + mtm)
        exposure.append(mtm / (cash + mtm))
    return pd.Series(eq, index=dates[lo:hi + 1]), float(np.mean(exposure))


def metrics(eq):
    r = eq.pct_change().dropna()
    yrs = len(r) / 248
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(248)
    dd = (eq / eq.cummax() - 1).min()
    return {"CAGR%": round(100 * cagr, 1), "vol%": round(100 * vol, 1),
            "Sharpe": round((r.mean() * 248 - RF) / vol, 2) if vol else np.nan,
            "maxDD%": round(100 * dd, 1), "Calmar": round(cagr / -dd, 2) if dd else np.nan}


def report(panel, reg, sec, mkt, split, hold=20):
    dates = list(mkt.dates[300:-hold - 1])[::5]
    tr = trades_with_paths(panel, reg, sec, mkt, sc.Config(), dates, hold)
    rows = []
    for label, s, e in (("train", dates[0], split), ("test", split, mkt.dates[-1]), ("all", dates[0], mkt.dates[-1])):
        eq, expo = simulate(tr, mkt, s, e)
        n = mkt.nifty.loc[eq.index[0]:eq.index[-1]]
        rows.append({"period": label, **{f"strategy {k}": v for k, v in metrics(eq).items()},
                     "strategy avg exposure%": round(100 * expo), **{f"Nifty {k}": v for k, v in metrics(n).items()}})
    print("\nPORTFOLIO (live rules; risk sizing; max 10 positions; 0.25% costs; Sharpe vs 6.5% risk-free)")
    print(pd.DataFrame(rows).set_index("period").T.to_string())
