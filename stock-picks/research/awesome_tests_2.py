"""Second round of awesome-systematic-trading ideas (v3-research branch).

    python awesome_tests_2.py timing | adaptive | dsr | all

timing    Market-exposure timing on the Nifty 50, to attack the measured weakness (max drawdown
          -27% vs Nifty -16%, caused by being long in falling markets):
          - RSRS (QuantsPlaybook / Everbright Securities): 18-day slope of high on low,
            z-scored over M days, and the R2-weighted version; long when > +0.7, out when < -0.7
          - EWMAC trend (pysystemtrade / Carver): EMA16 vs EMA64 of the Nifty
          - Breadth floor (QuantsPlaybook diffusion index): no new entries below X% breadth
          Exposure scales NEW entries only; open positions run their exits.
adaptive  "Pick the factors working now" (Inalpha): factor weights from each factor's trailing
          6-month IC (only ICs whose 15-day window has closed), vs the fixed momentum score.
dsr       Deflated Sharpe Ratio (Bailey & Lopez de Prado; Advances in Financial ML /
          Hudson & Thames): is the live Sharpe still positive after the number of
          variants we tried?

Run with the research venv. Choose on train (before 2025-04-01), confirm on test.
"""

import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))
import backtest_screener as bt  # noqa: E402
import portfolio as pf  # noqa: E402
import screener as sc  # noqa: E402

OUT = Path(r"D:\TradingAgentsData\research")
OUT.mkdir(parents=True, exist_ok=True)
pd.set_option("display.width", 220)


def load():
    panel = sc.build_features()
    reg, sec = sc.market_context(panel)
    return panel, reg, sec, bt.Market(panel)


def live_trades(panel, reg, sec, mkt):
    p = OUT / "live_trades_v3.pkl"
    if p.exists():
        return pd.read_pickle(p)
    dates = list(mkt.dates[300:-21])[::5]
    tr = pf.trades_with_paths(panel, reg, sec, mkt, sc.Config(), dates)
    tr.to_pickle(p)
    return tr


def simulate_scaled(trades, mkt, scale, start, end):
    """portfolio.simulate with new-entry risk multiplied by scale[signal date] (0 = skip)."""
    t = trades.copy()
    s = scale.reindex(t.date).fillna(1.0).to_numpy()
    t = t[s > 0].copy()
    t["stop_pct"] = t.stop_pct / s[s > 0]  # risk-based weight = risk / stop_pct, so this scales the weight
    return pf.simulate(t, mkt, start, end)[0]


# ---------- market timing ----------

def rsrs(h, l, n=18, m=250):
    beta, r2 = np.full(len(h), np.nan), np.full(len(h), np.nan)
    for i in range(n - 1, len(h)):
        x, y = l[i - n + 1:i + 1], h[i - n + 1:i + 1]
        if np.isnan(x).any() or np.isnan(y).any():
            continue
        b, a = np.polyfit(x, y, 1)
        beta[i] = b
        yhat = a + b * x
        ss = ((y - y.mean()) ** 2).sum()
        r2[i] = 1 - ((y - yhat) ** 2).sum() / ss if ss else np.nan
    b = pd.Series(beta)
    z = (b - b.rolling(m, min_periods=m // 2).mean()) / b.rolling(m, min_periods=m // 2).std()
    return z.to_numpy(), (z * pd.Series(r2)).to_numpy()


def hysteresis(sig, on=0.7, off=-0.7):
    """1 after crossing above `on`, 0 after crossing below `off`, else hold the last state."""
    out, state = np.ones(len(sig)), 1.0
    for i, v in enumerate(sig):
        if not np.isnan(v):
            if v > on:
                state = 1.0
            elif v < off:
                state = 0.0
        out[i] = state
    return out


def test_timing(panel, reg, sec, mkt):
    trades = live_trades(panel, reg, sec, mkt)
    n = panel[panel.symbol == sc.NIFTY].set_index("date").reindex(mkt.dates)
    h, l, c = n.high.to_numpy(float), n.low.to_numpy(float), n.close.to_numpy(float)
    idx = pd.Index(mkt.dates)
    schemes = {"none (live)": pd.Series(1.0, index=idx)}
    for m in (250, 600):
        z, zr2 = rsrs(h, l, 18, m)
        schemes[f"RSRS z (M={m}): out below -0.7"] = pd.Series(hysteresis(z), index=idx)
        schemes[f"RSRS z*R2 (M={m}): out below -0.7"] = pd.Series(hysteresis(zr2), index=idx)
        schemes[f"RSRS z*R2 (M={m}): half size when out"] = pd.Series(0.5 + 0.5 * hysteresis(zr2), index=idx)
    e16, e64 = pd.Series(c).ewm(span=16).mean(), pd.Series(c).ewm(span=64).mean()
    schemes["EWMAC 16/64: out when EMA16 < EMA64"] = pd.Series(np.where(e16 > e64, 1.0, 0.0), index=idx)
    schemes["EWMAC 16/64: half size when EMA16 < EMA64"] = pd.Series(np.where(e16 > e64, 1.0, 0.5), index=idx)
    for floor in (0.20, 0.30):
        schemes[f"breadth floor: no entries below {floor:.0%}"] = (reg.a50.reindex(idx) >= floor).astype(float)
    rows = []
    for name, s in schemes.items():
        s = s.shift(0)  # signal known at the signal day's close; entries happen next open
        for label, a, b in (("train", trades.date.min(), bt.SPLIT), ("test", bt.SPLIT, mkt.dates[-1])):
            eq = simulate_scaled(trades, mkt, s, a, b)
            on = s.loc[a:b]
            rows.append({"scheme": name, "period": label, **pf.metrics(eq), "time invested%": round(100 * (on > 0).mean())})
    t = pd.DataFrame(rows).pivot_table(index="scheme", columns="period", values=["CAGR%", "Sharpe", "maxDD%", "Calmar", "time invested%"])
    print("\nMARKET-EXPOSURE TIMING (portfolio level; signal scales new entries)")
    print(t.to_string())
    best = t["Calmar"]["train"].drop("none (live)").idxmax()
    print(f"\nChosen on TRAIN Calmar: {best} -> test Calmar {t['Calmar']['test'][best]} vs live {t['Calmar']['test']['none (live)']}, "
          f"test maxDD {t['maxDD%']['test'][best]} vs live {t['maxDD%']['test']['none (live)']}")
    return t


# ---------- adaptive factor weights ----------

def test_adaptive(panel, reg, sec, mkt, hold=15):
    from factor_ic import FACTORS
    dates = list(mkt.dates[300:-hold - 1])[::5]
    recs = {}
    for d in dates:
        x = sc.screen(panel[panel.date == d], reg.loc[d], sec.loc[d], sc.Config())
        x = x[x.veto.isin(["", "below falling SMA200", "extended"])]
        i = mkt.pos[d]
        fwd = mkt.c.iloc[i + hold] / mkt.o.iloc[i + 1] - 1
        x = x.assign(fwd=x.symbol.map(fwd)).dropna(subset=["fwd"]).reset_index(drop=True)
        f = pd.DataFrame({k: fn(x) for k, fn in FACTORS.items() if k != "score (current)"})
        recs[d] = (x[["symbol", "fwd", "score"]], f.rank(pct=True))
    ic = pd.DataFrame({d: {k: v.corr(xs.fwd.rank()) for k, v in fr.items()} for d, (xs, fr) in recs.items()}).T
    lag = int(np.ceil(hold / 5)) + 1  # an IC is usable only once its 15-day window has closed
    out = []
    for j, d in enumerate(dates):
        if j < 26 + lag:
            continue
        w = ic.iloc[j - lag - 26:j - lag].mean().clip(lower=0)
        if w.sum() == 0:
            continue
        xs, fr = recs[d]
        ad = (fr * (w / w.sum())).sum(axis=1)
        top_ad = xs.loc[ad.nlargest(10).index, "fwd"].mean() - xs.fwd.mean()
        top_fx = xs.loc[xs.score.nlargest(10).index, "fwd"].mean() - xs.fwd.mean()
        out.append({"date": d, "ic_adaptive": ad.rank().corr(xs.fwd.rank()), "ic_fixed": xs.score.rank().corr(xs.fwd.rank()),
                    "top10_adaptive": top_ad, "top10_fixed": top_fx, "top_w": w.sort_values().index[-1]})
    o = pd.DataFrame(out)
    o["period"] = np.where(o.date < bt.SPLIT, "train", "test")
    tt = lambda s: s.mean() / s.std() * np.sqrt(len(s))
    print("\nADAPTIVE FACTOR WEIGHTS (trailing 6-month IC) vs FIXED momentum score")
    for per, g in o.groupby("period"):
        print(f"  {per:5}: adaptive IC {g.ic_adaptive.mean():+.3f} (t {tt(g.ic_adaptive):+.1f}), top-10 {100 * g.top10_adaptive.mean():+.2f}% | "
              f"fixed IC {g.ic_fixed.mean():+.3f} (t {tt(g.ic_fixed):+.1f}), top-10 {100 * g.top10_fixed.mean():+.2f}%")
    print("  factor most often given the largest weight:", o.top_w.value_counts().head(4).to_dict())


# ---------- deflated Sharpe ratio ----------

def deflated_sharpe(returns: pd.Series, n_trials: int, sr_var: float):
    r = returns.dropna()
    sr = r.mean() / r.std()
    T = len(r)
    skew = ((r - r.mean()) ** 3).mean() / r.std() ** 3
    kurt = ((r - r.mean()) ** 4).mean() / r.std() ** 4
    g = 0.5772156649
    z = NormalDist().inv_cdf
    sr0 = np.sqrt(sr_var) * ((1 - g) * z(1 - 1 / n_trials) + g * z(1 - 1 / (n_trials * np.e)))
    dsr = NormalDist().cdf((sr - sr0) * np.sqrt(T - 1) / np.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    psr = NormalDist().cdf(sr * np.sqrt(T - 1) / np.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    return sr, sr0, psr, dsr


def test_dsr(panel, reg, sec, mkt):
    from dataclasses import replace
    dates = list(mkt.dates[300:-21])[::5]
    variants = {
        "live": {},
        "v1 playbook": {"setups": ("A", "B", "C", "D", "E"), "score_mode": "playbook", "exit_mode": "fixed", "max_stop_pct": 0.08},
        "trail 3 ATR": {"stop_atr": 3.0, "trail_atr": 3.0, "max_stop_pct": 0.12},
        "no regime filter": {"regime_filter": False},
        "old risk-off rule": {"riskoff_quadrants": ("Leading", "Improving")},
        "all setups, momentum": {"setups": ("A", "B", "C", "D", "E")},
        "max 2 per sector": {"max_per_sector": 2},
        "stop 1.5 ATR": {"stop_atr": 1.5, "trail_atr": 1.5},
    }
    srs, live_eq = {}, None
    for name, over in variants.items():
        cfg = replace(sc.Config(), **over)
        hold = 15 if cfg.exit_mode == "fixed" else 20
        tr = pf.trades_with_paths(panel, reg, sec, mkt, cfg, dates, hold) if name != "live" else live_trades(panel, reg, sec, mkt)
        eq = pf.simulate(tr, mkt, dates[0], mkt.dates[-1])[0]
        r = eq.pct_change().dropna()
        srs[name] = r.mean() / r.std()
        if name == "live":
            live_eq = eq
        print(f"  {name:22} daily Sharpe {srs[name]:+.4f} (annual {srs[name] * np.sqrt(248):+.2f})", file=sys.stderr)
    var = np.var(list(srs.values()), ddof=1)
    r = live_eq.pct_change().dropna()
    rf_daily = (1 + pf.RF) ** (1 / 248) - 1
    print("\nDEFLATED SHARPE RATIO (live rules, all years, daily returns)")
    for n_trials in (8, 45):
        for label, ret in (("raw returns", r), ("excess over 6.5% risk-free", r - rf_daily)):
            sr, sr0, psr, dsr = deflated_sharpe(ret, n_trials, var)
            print(f"  trials={n_trials:2} {label:27}: annual Sharpe {sr * np.sqrt(248):+.2f}; luck bar {sr0 * np.sqrt(248):+.2f}; "
                  f"P(Sharpe>0) {psr:.0%}; deflated P(true skill) {dsr:.0%}")
    print(f"  (variance of annual Sharpe across the {len(srs)} re-run variants: {var * 248:.3f}; 45 = all variants tried in this project)")


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    panel, reg, sec, mkt = load()
    if which in ("timing", "all"):
        test_timing(panel, reg, sec, mkt)
    if which in ("adaptive", "all"):
        test_adaptive(panel, reg, sec, mkt)
    if which in ("dsr", "all"):
        test_dsr(panel, reg, sec, mkt)


if __name__ == "__main__":
    main()
