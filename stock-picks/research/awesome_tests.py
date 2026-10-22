"""Tests of ideas from wangzhe3224/awesome-systematic-trading against our screener (v2 branch).

    python awesome_tests.py portfolio | cluster | volmanaged | hurst | ml | all

portfolio   quantstats/pyfolio-style portfolio metrics for the live (v1) rules: equity curve,
            CAGR, Sharpe, max drawdown vs Nifty, with capital and position limits.
cluster     honest-signals / Lacuna idea: date-clustered t-stats for the pattern study
            (events on the same day are not independent).
volmanaged  pysystemtrade-style volatility management (Barroso & Santa-Clara): scale
            exposure by the momentum factor's own recent volatility or trend.
hurst       Hurst exponent (trending vs mean-reverting) as a factor: rank IC.
ml          Qlib-style ML ranking: gradient boosting on our features, trained on the
            training period only, vs the momentum score on the test period.

Run with the research venv (scikit-learn): C:\\Users\\Dell\\research\\.venv\\Scripts\\python.exe
Reads market.db / features.pkl; writes nothing outside D:\\TradingAgentsData\\research.
"""

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backtest_screener as bt  # noqa: E402
import screener as sc  # noqa: E402

OUT = Path(r"D:\TradingAgentsData\research")
OUT.mkdir(parents=True, exist_ok=True)
pd.set_option("display.width", 220)


def load():
    panel = sc.build_features()
    reg, sec = sc.market_context(panel)
    return panel, reg, sec, bt.Market(panel)


# ---------- 1. portfolio simulation ----------

def picks_with_paths(panel, reg, sec, mkt, cfg, dates, hold=20):
    """Live-rule trades with entry/exit bars, for a day-by-day portfolio."""
    rows = []
    for d in dates:
        x = sc.screen(panel[panel.date == d], reg.loc[d], sec.loc[d], cfg)
        picks = sc.pick_list(x, reg.loc[d], cfg)
        for p in picks.head(int(reg.loc[d].picks)).itertuples():
            t = mkt.trade(p.symbol, d, p.stop, p.target, hold, cfg.trail_atr, p.atr)
            if t:
                i = mkt.pos[d]
                rows.append({"date": d, "symbol": p.symbol, "i_in": i + 1, "i_out": i + t["days"], "ret": t["ret"],
                             "stop_pct": float(p.stop_pct), "a50": float(reg.loc[d].a50), "regime": reg.loc[d].regime})
    return pd.DataFrame(rows)


def simulate(trades, mkt, scale=None, max_pos=10, max_w=0.20, start=None, end=None):
    """Day-by-day equity: risk-based sizing (1% risk above 60% breadth, else 0.5%), weight
    capped at 20%, at most 10 positions and 100% invested; returns daily equity series."""
    o, c = mkt.o, mkt.c
    dates = mkt.dates
    lo = 0 if start is None else int(np.searchsorted(dates, start))
    hi = len(dates) - 1 if end is None else int(np.searchsorted(dates, end))
    eq, cash, open_pos = [], 1.0, []
    by_entry = trades.groupby("i_in")
    for k in range(lo, hi + 1):
        if k in by_entry.groups:
            for t in by_entry.get_group(k).itertuples():
                value = cash + sum(p["sh"] * c[p["sym"]].iloc[k - 1] for p in open_pos)
                risk = 0.01 if t.a50 > 0.6 else 0.005
                if scale is not None:
                    risk *= float(scale.get(t.date, 1.0))
                w = min(risk / max(t.stop_pct, 1e-4), max_w)
                if len(open_pos) >= max_pos or w * value > cash or w <= 0:
                    continue
                px = o[t.symbol].iloc[k]
                cost = w * value
                open_pos.append({"sym": t.symbol, "sh": cost * (1 - bt.COST / 2) / px, "out": t.i_out,
                                 "exit_px": px * (1 + t.ret + bt.COST)})
                cash -= cost
        still = []
        for p in open_pos:
            if k >= p["out"]:
                cash += p["sh"] * p["exit_px"] * (1 - bt.COST / 2)
            else:
                still.append(p)
        open_pos = still
        mtm = sum(p["sh"] * (c[p["sym"]].iloc[k] if not np.isnan(c[p["sym"]].iloc[k]) else p["exit_px"]) for p in open_pos)
        eq.append(cash + mtm)
    return pd.Series(eq, index=dates[lo:hi + 1])


def metrics(eq, rf=0.065):
    r = eq.pct_change().dropna()
    yrs = len(r) / 248
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(248)
    dd = (eq / eq.cummax() - 1).min()
    sharpe = (r.mean() * 248 - rf) / vol if vol else np.nan
    return {"CAGR%": round(100 * cagr, 1), "vol%": round(100 * vol, 1), "Sharpe(rf 6.5%)": round(sharpe, 2),
            "maxDD%": round(100 * dd, 1), "Calmar": round(cagr / -dd, 2) if dd else np.nan}


def test_portfolio(panel, reg, sec, mkt):
    dates = list(mkt.dates[300:-21])[::5]
    tr = picks_with_paths(panel, reg, sec, mkt, sc.Config(), dates)
    tr.to_pickle(OUT / "live_trades.pkl")
    rows = []
    for label, s, e in (("train", dates[0], bt.SPLIT), ("test", bt.SPLIT, mkt.dates[-1]), ("all", dates[0], mkt.dates[-1])):
        eq = simulate(tr, mkt, start=s, end=e)
        nifty = mkt.nifty.loc[eq.index[0]:eq.index[-1]]
        exposure = None
        rows.append({"period": label, **{f"strategy {k}": v for k, v in metrics(eq).items()},
                     **{f"Nifty {k}": v for k, v in metrics(nifty).items() if k in ("CAGR%", "maxDD%", "Sharpe(rf 6.5%)")}})
    print("\nPORTFOLIO (live v1 rules, ₹ equity from 1.0, risk sizing, max 10 positions, 0.25% round-trip costs)")
    print(pd.DataFrame(rows).set_index("period").T.to_string())
    return tr


# ---------- 2. date-clustered pattern statistics ----------

def test_cluster():
    ev = pd.read_pickle(sc.ROOT / "market" / "pattern_events.pkl")
    rows = []
    for (pat, per), g in ev.groupby(["pattern", "period"]):
        pooled_t = g.excess.mean() / g.excess.std() * np.sqrt(len(g)) if len(g) > 2 else np.nan
        daily = g.groupby("date").excess.mean()
        clus_t = daily.mean() / daily.std() * np.sqrt(len(daily)) if len(daily) > 2 else np.nan
        rows.append({"pattern": pat, "period": per, "events": len(g), "days": len(daily),
                     "excess%": round(100 * g.excess.mean(), 2), "pooled t": round(pooled_t, 1), "clustered t": round(clus_t, 1)})
    t = pd.DataFrame(rows).pivot_table(index="pattern", columns="period", values=["excess%", "pooled t", "clustered t", "days"])
    print("\nPATTERNS: pooled t (every event independent) vs date-clustered t (one observation per day)")
    print(t.round(2).to_string())
    sig = pd.DataFrame(rows)
    both = sig.pivot_table(index="pattern", columns="period", values="clustered t")
    print("\nPatterns with |clustered t| >= 2 in BOTH periods and the same sign:",
          [p for p, r in both.iterrows() if abs(r.get("train", 0)) >= 2 and abs(r.get("test", 0)) >= 2 and np.sign(r["train"]) == np.sign(r["test"])] or "none")


# ---------- 3. volatility-managed momentum ----------

def momentum_factor(panel, mkt):
    """Daily long-short proxy: equal-weight top decile by 12-1 momentum minus the universe mean (liquid stocks)."""
    st = panel[~panel.symbol.str.startswith("^") & (panel.traded_value >= 1e8)].copy()
    st["mom"] = (1 + st.r252) / (1 + st.r21) - 1
    nxt = (mkt.c.shift(-1) / mkt.c - 1).stack().rename("fwd1").reset_index().rename(columns={"level_0": "date", "level_1": "symbol"})
    nxt.columns = ["date", "symbol", "fwd1"]
    st = st.merge(nxt, on=["date", "symbol"], how="inner").dropna(subset=["mom", "fwd1"])
    st["dec"] = st.groupby("date").mom.rank(pct=True)
    top = st[st.dec >= 0.9].groupby("date").fwd1.mean()
    allm = st.groupby("date").fwd1.mean()
    f = (top - allm).shift(1).dropna()  # the return earned on day t from a signal at t-1, known after day t
    return f


def test_volmanaged(panel, reg, sec, mkt, trades=None):
    if trades is None:
        p = OUT / "live_trades.pkl"
        trades = pd.read_pickle(p) if p.exists() else picks_with_paths(panel, reg, sec, mkt, sc.Config(), list(mkt.dates[300:-21])[::5])
    f = momentum_factor(panel, mkt)
    vol = f.rolling(126).std() * np.sqrt(248)
    longrun = vol.expanding(250).median()
    trend = f.rolling(63).sum()
    schemes = {
        "none (live)": pd.Series(1.0, index=f.index),
        "vol target: scale = median vol / current vol, 0.25-1": (longrun / vol).clip(0.25, 1.0),
        "vol filter: half size when vol > 1.25 x median": np.where(vol > 1.25 * longrun, 0.5, 1.0),
        "factor trend: half size when 3m momentum-factor return < 0": np.where(trend < 0, 0.5, 1.0),
        "factor trend: skip when 3m momentum-factor return < 0": np.where(trend < 0, 0.0, 1.0),
    }
    rows = []
    for name, s in schemes.items():
        s = pd.Series(s, index=f.index) if not isinstance(s, pd.Series) else s
        s = s.reindex(mkt.dates).ffill().fillna(1.0)
        for label, a, b in (("train", trades.date.min(), bt.SPLIT), ("test", bt.SPLIT, mkt.dates[-1])):
            eq = simulate(trades, mkt, scale=s, start=a, end=b)
            rows.append({"scheme": name, "period": label, **metrics(eq)})
    t = pd.DataFrame(rows).pivot_table(index="scheme", columns="period", values=["CAGR%", "Sharpe(rf 6.5%)", "maxDD%", "Calmar"])
    print("\nVOLATILITY-MANAGED MOMENTUM (portfolio level, same picks, exposure scaled)")
    print(t.to_string())
    yr = f.groupby(f.index.str[:4]).agg(["sum", "std"])
    print("\nMomentum factor by year (sum of daily long-short returns, daily std):\n", yr.round(4).to_string())


# ---------- 4. Hurst exponent ----------

def hurst_rs(x):
    x = x[~np.isnan(x)]
    if len(x) < 64:
        return np.nan
    ns, rs = [8, 16, 32, 64], []
    for n in ns:
        k = len(x) // n
        vals = []
        for j in range(k):
            s = x[j * n:(j + 1) * n]
            z = np.cumsum(s - s.mean())
            sd = s.std()
            if sd > 0:
                vals.append((z.max() - z.min()) / sd)
        rs.append(np.mean(vals) if vals else np.nan)
    ok = ~np.isnan(rs)
    return np.polyfit(np.log(np.array(ns)[ok]), np.log(np.array(rs)[ok]), 1)[0] if ok.sum() >= 3 else np.nan


def test_hurst(panel, reg, sec, mkt):
    dates = list(mkt.dates[300:-16])[::5]
    lr = np.log(mkt.c).diff()
    rows = []
    for d in dates:
        i = mkt.pos[d]
        x = sc.screen(panel[panel.date == d], reg.loc[d], sec.loc[d], sc.Config())
        x = x[x.veto.isin(["", "below falling SMA200", "extended"])]
        fwd = mkt.c.iloc[i + 15] / mkt.o.iloc[i + 1] - 1
        win = lr.iloc[i - 127:i + 1]
        h = pd.Series({s: hurst_rs(win[s].to_numpy()) for s in x.symbol if s in win})
        df = pd.DataFrame({"h": h, "fwd": fwd.reindex(h.index), "mom": x.set_index("symbol").score.reindex(h.index)}).dropna()
        if len(df) > 50:
            rows.append({"date": d, "ic_h": df.h.rank().corr(df.fwd.rank()), "ic_mom": df.mom.rank().corr(df.fwd.rank()),
                         "ic_h_in_mom": df[df.mom >= df.mom.quantile(0.8)].pipe(lambda z: z.h.rank().corr(z.fwd.rank()))})
    ic = pd.DataFrame(rows)
    ic["period"] = np.where(ic.date < bt.SPLIT, "train", "test")
    t = lambda s: s.mean() / s.std() * np.sqrt(len(s))
    print("\nHURST EXPONENT (128-day R/S) as a factor: 15-day rank IC")
    for col, name in (("ic_h", "Hurst, all stocks"), ("ic_h_in_mom", "Hurst, within top-20% momentum score"), ("ic_mom", "momentum score (reference)")):
        g = ic.groupby("period")[col]
        print(f"  {name:40} train IC {g.mean()['train']:+.3f} (t {t(ic[ic.period == 'train'][col]):+.1f}) | "
              f"test IC {g.mean()['test']:+.3f} (t {t(ic[ic.period == 'test'][col]):+.1f})")


# ---------- 5. ML ranking ----------

FEATS = ["r1", "r5", "r21", "r63", "r126", "r189", "r252", "rsi", "adx", "pdi", "mdi", "atr_pct", "macd_hist",
         "vol_ratio", "close_pos", "base_range", "updown_vol", "obv_slope", "ext_atr", "tv_rating", "sma50_slope"]


def ml_frame(panel, mkt, dates, hold=15):
    rows = []
    st = panel[~panel.symbol.str.startswith("^")]
    for d in dates:
        i = mkt.pos[d]
        x = st[(st.date == d) & (st.traded_value >= 1e8) & (st.bars >= sc.MIN_BARS) & (st.close >= 50)].copy()
        x["above200"] = x.close / x.sma200
        x["near_hi"] = x.close / x.hi52
        x["off_lo"] = x.close / x.lo52
        x["mom12_1"] = (1 + x.r252) / (1 + x.r21) - 1
        fwd = mkt.c.iloc[i + hold] / mkt.o.iloc[i + 1] - 1
        x["fwd"] = x.symbol.map(fwd)
        x = x.dropna(subset=["fwd"])
        x["y"] = x.fwd.rank(pct=True)  # cross-sectional rank: removes the market's move
        x["date"] = d
        rows.append(x)
    return pd.concat(rows, ignore_index=True)


def test_ml(panel, reg, sec, mkt):
    from sklearn.ensemble import HistGradientBoostingRegressor
    dates = list(mkt.dates[300:-16])[::5]
    df = ml_frame(panel, mkt, dates)
    feats = FEATS + ["above200", "near_hi", "off_lo", "mom12_1"]
    split_i = int(np.searchsorted(mkt.dates, bt.SPLIT))
    purge = mkt.dates[split_i - 16]  # training labels must end before the test starts
    tr, te = df[df.date < purge], df[df.date >= bt.SPLIT]
    model = HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=200,
                                          l2_regularization=1.0, random_state=0)
    model.fit(tr[feats], tr.y)
    te = te.assign(pred=model.predict(te[feats]))
    # reference: the live momentum score's raw ingredients, ranked the same way
    te["mom_ref"] = (0.35 * te.groupby("date").mom12_1.rank(pct=True) + 0.25 * te.groupby("date").near_hi.rank(pct=True)
                     + 0.10 * te.groupby("date").above200.rank(pct=True) + 0.20 * te.groupby("date").r252.rank(pct=True))
    out = []
    for d, g in te.groupby("date"):
        top_ml = g.nlargest(10, "pred").fwd.mean() - g.fwd.mean()
        top_mom = g.nlargest(10, "mom_ref").fwd.mean() - g.fwd.mean()
        out.append({"date": d, "ic_ml": g.pred.rank().corr(g.fwd.rank()), "ic_mom": g.mom_ref.rank().corr(g.fwd.rank()),
                    "top10_ml": top_ml, "top10_mom": top_mom})
    o = pd.DataFrame(out)
    t = lambda s: s.mean() / s.std() * np.sqrt(len(s))
    print(f"\nML RANKING (gradient boosting, {len(tr):,} training rows before {purge}, tested on {o.date.nunique()} test dates)")
    print(f"  ML model        test IC {o.ic_ml.mean():+.3f} (t {t(o.ic_ml):+.1f}) | top-10 excess {100 * o.top10_ml.mean():+.2f}% per 15 days")
    print(f"  momentum score  test IC {o.ic_mom.mean():+.3f} (t {t(o.ic_mom):+.1f}) | top-10 excess {100 * o.top10_mom.mean():+.2f}% per 15 days")
    print(f"  ML beat momentum on {100 * (o.ic_ml > o.ic_mom).mean():.0f}% of test dates")
    imp = pd.Series(np.abs(np.corrcoef(np.c_[tr[feats].fillna(0).to_numpy(), tr.y.to_numpy()].T)[-1, :-1]), index=feats)
    print("  strongest single-feature correlations with the training label:", imp.sort_values(ascending=False).head(6).round(3).to_dict())


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which == "cluster":
        return test_cluster()
    panel, reg, sec, mkt = load()
    trades = None
    if which in ("portfolio", "all"):
        trades = test_portfolio(panel, reg, sec, mkt)
    if which in ("cluster", "all"):
        test_cluster()
    if which in ("volmanaged", "all"):
        test_volmanaged(panel, reg, sec, mkt, trades)
    if which in ("hurst", "all"):
        test_hurst(panel, reg, sec, mkt)
    if which in ("ml", "all"):
        test_ml(panel, reg, sec, mkt)


if __name__ == "__main__":
    main()
