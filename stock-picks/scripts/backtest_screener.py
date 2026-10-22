"""Backtest the screener rules on stored history (no LLM, no tokens).

Signals on a day's close; entry at the next day's open; exit at the stop, the
target, or the close of day `hold` (time stop). A day that touches both stop and
target counts as a stop (conservative); a gap through a level fills at the open.
Round-trip costs of 0.25% (STT, brokerage, GST, stamp duty) come off every trade.

    python backtest_screener.py                 # baseline config, train and test periods
    python backtest_screener.py --variants      # baseline vs variants, picked on train, checked on test

Caveat printed with every result: the universe is today's Nifty 500, so stocks
that fell out of the index are missing from past years (survivorship bias);
absolute returns are flattered, comparisons between configs much less so.
"""

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import screener as sc  # noqa: E402

COST = 0.0025
SPLIT = "2025-04-01"  # train before, test from (never used to choose a config)


class Market:
    def __init__(self, panel):
        stocks = panel[~panel.symbol.str.startswith("^")]
        self.dates = np.array(sorted(panel[panel.symbol == sc.NIFTY].date))
        self.pos = {d: i for i, d in enumerate(self.dates)}
        piv = lambda col: stocks.pivot(index="date", columns="symbol", values=col).reindex(self.dates)
        self.o, self.h, self.l, self.c = (piv(k) for k in ("open", "high", "low", "close"))
        self.nifty = panel[panel.symbol == sc.NIFTY].set_index("date").close.reindex(self.dates)

    def trade(self, sym, day, stop, target, hold, trail=None, atr=None, partial_r=None, partial_frac=0.5):
        """trail=None: fixed stop + target. trail=k: no target; the stop ratchets up to
        the highest close since entry minus k x ATR (ATR as of the signal day).
        partial_r=R: with a trail, book `partial_frac` of the position at entry + R x risk
        (the target) and trail the rest; the result is the blended return."""
        if partial_r is not None and trail is not None:
            full = self.trade(sym, day, stop, target, hold, trail, atr)
            if full is None:
                return None
            i = self.pos[day]
            o, h = self.o[sym].to_numpy(), self.h[sym].to_numpy()
            entry = o[i + 1]
            tgt = entry + partial_r * (entry - stop)
            last = i + full["days"]
            hit = next((k for k in range(i + 1, last + 1) if h[k] >= tgt), None)
            # Booked only if the target trades before the trailing exit's day (a same-day
            # touch counts only when the exit was not a stop, the conservative order).
            if hit is not None and (hit < last or full["exit"] != "stop"):
                booked = max(o[hit], tgt) if hit > i + 1 else tgt
                part_ret = booked / entry - 1 - COST
                ret = partial_frac * part_ret + (1 - partial_frac) * full["ret"]
                n_ret = full["ret"] - full["alpha"]
                return {**full, "ret": ret, "alpha": ret - n_ret,
                        "R": partial_frac * partial_r + (1 - partial_frac) * full["R"], "exit": "target+trail"}
            return full
        i = self.pos[day]
        if i + 1 >= len(self.dates) or sym not in self.o:
            return None
        o, h, l, c = (m[sym].to_numpy() for m in (self.o, self.h, self.l, self.c))
        entry = o[i + 1]
        if np.isnan(entry) or entry <= stop:
            return None
        init_stop = stop
        last = min(i + hold, len(self.dates) - 1)
        exit_px, j, why = c[last], last, "time"
        best = entry
        for k in range(i + 1, last + 1):
            if l[k] <= stop:
                exit_px, j, why = (min(o[k], stop) if k > i + 1 else stop), k, "stop"
                break
            if trail is None and h[k] >= target:
                exit_px, j, why = (max(o[k], target) if k > i + 1 else target), k, "target"
                break
            if trail is not None:
                best = max(best, c[k])
                stop = max(stop, best - trail * atr)  # takes effect from the next bar
        stop = init_stop
        ret = exit_px / entry - 1 - COST
        n_ret = self.nifty.iloc[j] / self.nifty.iloc[i] - 1
        return {"ret": ret, "alpha": ret - n_ret, "R": (exit_px - entry) / (entry - stop), "exit": why, "days": j - i}


def path_trade(mkt, sym, day, stop, hold, trail_atr=None, atr=None, t1=None, t1_frac=0.5, t2=None):
    """General exit engine: initial stop, optional ATR trail, optional partial at t1,
    optional hard exit of the remainder at t2. Conservative ordering within a bar:
    stop first, then targets. Prices are absolute levels (from levels.py or ATR)."""
    i = mkt.pos[day]
    if i + 1 >= len(mkt.dates) or sym not in mkt.o:
        return None
    o, h, l, c = (m[sym].to_numpy() for m in (mkt.o, mkt.h, mkt.l, mkt.c))
    entry = o[i + 1]
    if np.isnan(entry) or entry <= stop:
        return None
    risk0, last = entry - stop, min(i + hold, len(mkt.dates) - 1)
    pos, pnl, best, booked, why, j = 1.0, 0.0, entry, False, "time", last
    for k in range(i + 1, last + 1):
        fill = lambda lvl, up: (max(o[k], lvl) if up else min(o[k], lvl)) if k > i + 1 else lvl
        if l[k] <= stop:
            pnl += pos * (fill(stop, False) / entry - 1); pos, why, j = 0.0, "stop" if not booked else "T1+stop", k
            break
        if t1 is not None and not booked and h[k] >= t1:
            pnl += t1_frac * (fill(t1, True) / entry - 1); pos -= t1_frac; booked = True
        if t2 is not None and h[k] >= t2:
            pnl += pos * (fill(t2, True) / entry - 1); pos, why, j = 0.0, "T2", k
            break
        if trail_atr is not None:
            best = max(best, c[k])
            stop = max(stop, best - trail_atr * atr)
    if pos > 0:
        pnl += pos * (c[j] / entry - 1)
    ret = pnl - COST
    n_ret = mkt.nifty.iloc[j] / mkt.nifty.iloc[i] - 1
    return {"ret": ret, "alpha": ret - n_ret, "R": pnl * entry / risk0, "exit": why, "days": j - i}


def run_levels(panel, reg, sec, mkt, cfg, dates, mode, take="regime", hold=20):
    """Same picks as run(); stops/targets per `mode`:
    atr = 2 ATR stop, 2 ATR trail (current) | ta = technical stop, 2 ATR trail |
    ta_t1 = technical stop, half at technical T1, trail rest | atr_t1 = ATR stop, half at technical T1, trail rest |
    ta_t1t2 = technical stop, half at T1, rest at T2 (trail as backup) | ta_fixed = technical stop, all out at T1."""
    import levels as lv
    import patterns as pt
    weeks = lv.week_ids(mkt.dates)
    if not hasattr(mkt, "_pat"):
        mkt._pat = {}
    lmode = "adaptive" if mode.startswith("ad_") else "fixed"
    rows = []
    for d in dates:
        x = sc.screen(panel[panel.date == d], reg.loc[d], sec.loc[d], cfg)
        picks = sc.pick_list(x, reg.loc[d], cfg)
        n = int(reg.loc[d].picks) if take == "regime" else int(take)
        i = mkt.pos[d]
        for p in picks.head(n).itertuples():
            o, h, l, c = (m[p.symbol].to_numpy(float) for m in (mkt.o, mkt.h, mkt.l, mkt.c))
            if p.symbol not in mkt._pat:  # chart patterns for this stock, scanned once (look-ahead free)
                a_full = panel[panel.symbol == p.symbol].set_index("date").atr.reindex(mkt.dates).to_numpy(float)
                mkt._pat[p.symbol] = pt.scan(o, h, l, c, a_full)
            ev = [(k, q) for k, q in mkt._pat[p.symbol] if i - 10 <= k <= i]
            L = lv.levels(mkt.dates, h, l, c, i, float(p.atr), float(p.ema20), float(p.sma50), float(p.prior_high_close20),
                          mode=lmode, weeks=weeks, pattern_events=ev)
            atr_stop = p.close - cfg.stop_atr * p.atr
            ta_stop = L["stop"]
            base = mode[3:] if mode.startswith("ad_") else mode
            plan = {"atr": (atr_stop, 2.0, None, None), "ta": (ta_stop, 2.0, None, None),
                    "ta_t1": (ta_stop, 2.0, L["t1"], None), "atr_t1": (atr_stop, 2.0, L["t1"], None),
                    "ta_t1t2": (ta_stop, 2.0, L["t1"], L["t2"]), "ta_fixed": (ta_stop, None, None, L["t1"])}[base]
            stop, trail, t1, t2 = plan
            t = path_trade(mkt, p.symbol, d, stop, hold, trail, float(p.atr), t1, 0.5, t2)
            if t:
                rows.append({"date": d, "symbol": p.symbol, "regime": reg.loc[d].regime, **t})
    return pd.DataFrame(rows)


def run(panel, reg, sec, mkt, cfg, dates, take="regime", hold=15):
    rows = []
    for d in dates:
        x = sc.screen(panel[panel.date == d], reg.loc[d], sec.loc[d], cfg)
        picks = sc.pick_list(x, reg.loc[d], cfg)
        n = int(reg.loc[d].picks) if take == "regime" else int(take)
        for p in picks.head(n).itertuples():
            trail = cfg.trail_atr if cfg.exit_mode == "trail" else None
            t = mkt.trade(p.symbol, d, p.stop, p.target, hold, trail, p.atr)
            if t:
                rows.append({"date": d, "symbol": p.symbol, "setups": p.setups, "regime": reg.loc[d].regime, **t})
    return pd.DataFrame(rows)


def stats(t: pd.DataFrame) -> dict:
    if t.empty:
        return {"trades": 0}
    win = t.ret > 0
    gains, losses = t.ret[win].sum(), -t.ret[~win].sum()
    return {"trades": len(t), "win%": round(100 * win.mean(), 1), "avg%": round(100 * t.ret.mean(), 2),
            "alpha%": round(100 * t.alpha.mean(), 2), "avgR": round(t.R.mean(), 2),
            "PF": round(gains / losses, 2) if losses else np.inf,
            "stop%": round(100 * (t.exit == "stop").mean()), "target%": round(100 * (t.exit == "target").mean())}


def universe_baseline(panel, mkt, dates, hold=15):
    """What an average liquid stock did over the same windows: the bar to beat."""
    out = []
    for d in dates:
        i = mkt.pos[d]
        j = min(i + hold, len(mkt.dates) - 1)
        if i + 1 >= len(mkt.dates):
            continue
        r = mkt.c.iloc[j] / mkt.o.iloc[i + 1] - 1 - COST
        n_ret = mkt.nifty.iloc[j] / mkt.nifty.iloc[i] - 1
        out.append({"ret": r.median(), "alpha": (r - n_ret).median()})
    b = pd.DataFrame(out)
    return {"median stock 15d%": round(100 * b.ret.mean(), 2), "median alpha%": round(100 * b.alpha.mean(), 2)}


V1 = {"setups": ("A", "B", "C", "D", "E"), "score_mode": "playbook", "exit_mode": "fixed",
      "trail_atr": 3.0, "max_stop_pct": 0.08}  # the original playbook config, for comparison
VARIANTS = {
    "baseline": V1,
    "no regime filter": {"regime_filter": False},
    "stop 2.5 ATR": {"stop_atr": 2.5},
    "stop 1.5 ATR": {"stop_atr": 1.5},
    "target 2R": {"target_r": 2.0, "min_rr": 1.5},
    "target 4R": {"target_r": 4.0},
    "breakout vol 2x": {"breakout_volume": 2.0},
    "RS heavier": {"weights": {"rs": 0.40, "trend": 0.15, "volume": 0.10, "sector": 0.15, "setup": 0.10, "tv": 0.05, "risk": -0.10}},
    "sector heavier": {"weights": {"rs": 0.25, "trend": 0.15, "volume": 0.10, "sector": 0.30, "setup": 0.10, "tv": 0.05, "risk": -0.10}},
    "no TV rating": {"weights": {"rs": 0.30, "trend": 0.20, "volume": 0.15, "sector": 0.15, "setup": 0.15, "tv": 0.0, "risk": -0.10}},
    "only A+E": {"setups": ("A", "E")},
    "only B+C+D": {"setups": ("B", "C", "D")},
    "max 2 per sector": {"max_per_sector": 2},
}
VARIANTS = {k: {**V1, **v} for k, v in VARIANTS.items()}  # each is a change to v1

# v2 candidates built from the training-period factor study (factor_ic.py) and the
# stop-out diagnosis: momentum score, wider ATR stops, trailing exits.
MOM = {**V1, "score_mode": "momentum", "setups": ("A", "E")}
VARIANTS_V2 = {
    "baseline (v1)": V1,
    "momentum score, v1 exits": MOM,
    "momentum, trail 3ATR, stop 2.5ATR": {**MOM, "exit_mode": "trail", "stop_atr": 2.5, "trail_atr": 3.0, "max_stop_pct": 0.10},
    "momentum, trail 3ATR, stop 3ATR": {**MOM, "exit_mode": "trail", "stop_atr": 3.0, "trail_atr": 3.0, "max_stop_pct": 0.12},
    "momentum, trail 2ATR, stop 2ATR": {**MOM, "exit_mode": "trail", "stop_atr": 2.0, "trail_atr": 2.0, "max_stop_pct": 0.10},
    "momentum, trail 3ATR, pullback entry": {**MOM, "exit_mode": "trail", "stop_atr": 2.5, "trail_atr": 3.0, "max_stop_pct": 0.10, "entry_filter": "pullback"},
    "momentum, trail 3ATR, no regime filter": {**MOM, "exit_mode": "trail", "stop_atr": 2.5, "trail_atr": 3.0, "max_stop_pct": 0.10, "regime_filter": False},
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", action="store_true")
    ap.add_argument("--v2", action="store_true", help="the momentum / trailing-exit candidates")
    ap.add_argument("--levels", action="store_true", help="ATR vs technical (support/resistance) stops and targets")
    ap.add_argument("--portfolio", action="store_true", help="equity curve, CAGR, Sharpe and drawdown of the live rules")
    ap.add_argument("--every", type=int, default=5, help="trading days between signal dates")
    ap.add_argument("--hold", type=int, default=15)
    ap.add_argument("--take", default="regime", help="'regime' (3/6/10 by regime) or a fixed number")
    a = ap.parse_args()

    panel = sc.build_features()
    reg, sec = sc.market_context(panel)
    mkt = Market(panel)
    # Skip the first 300 sessions: SMA200, 52-week and 12-month returns need the warm-up.
    dates = list(mkt.dates[300:-a.hold - 1])[::a.every]
    train = [d for d in dates if d < SPLIT]
    test = [d for d in dates if d >= SPLIT]
    print(f"signal dates: {len(train)} train ({train[0]} to {train[-1]}), {len(test)} test ({test[0]} to {test[-1]}); "
          f"hold {a.hold} days, picks per date = {a.take}")
    print("bar to beat (train):", universe_baseline(panel, mkt, train, a.hold),
          "| (test):", universe_baseline(panel, mkt, test, a.hold))

    if a.portfolio:
        import portfolio
        return portfolio.report(panel, reg, sec, mkt, SPLIT)
    if a.levels:
        modes = {"atr": "ATR stop 2x, trail 2 ATR", "ta": "fixed technical stop, trail 2 ATR (v3)",
                 "ad_ta": "ADAPTIVE stop, trail 2 ATR",
                 "ta_t1": "fixed: half at T1, trail rest", "ad_ta_t1": "ADAPTIVE: half at T1, trail rest",
                 "ta_fixed": "fixed: all out at T1", "ad_ta_fixed": "ADAPTIVE: all out at T1",
                 "ta_t1t2": "fixed: half T1, rest T2", "ad_ta_t1t2": "ADAPTIVE: half T1, rest T2"}
        res = []
        for m, label in modes.items():
            tr = run_levels(panel, reg, sec, mkt, sc.Config(), train, m)
            te = run_levels(panel, reg, sec, mkt, sc.Config(), test, m)
            res.append({"exit plan": label, **{f"train {k}": v for k, v in stats(tr).items()},
                        **{f"test {k}": v for k, v in stats(te).items()}})
            print(f"  done: {label}", file=sys.stderr)
        pd.set_option("display.width", 250)
        cols = ["trades", "win%", "avg%", "alpha%", "avgR", "PF"]
        out = pd.DataFrame(res).set_index("exit plan")
        print(out[[f"{h} {c}" for h in ("train", "test") for c in cols]].to_string())
        return
    names = VARIANTS_V2 if a.v2 else VARIANTS if a.variants else {"baseline": {}}
    res = []
    for name, over in names.items():
        cfg = replace(sc.Config(), **over)
        hold = a.hold if cfg.exit_mode == "fixed" else max(a.hold, 20)  # trailing exits get up to 4 weeks
        tr = run(panel, reg, sec, mkt, cfg, train, a.take, hold)
        te = run(panel, reg, sec, mkt, cfg, test, a.take, hold)
        res.append({"variant": name, **{f"train {k}": v for k, v in stats(tr).items()},
                    **{f"test {k}": v for k, v in stats(te).items()}})
        if name.startswith("baseline"):
            base_tr, base_te = tr, te
        print(f"  done: {name}", file=sys.stderr)
    out = pd.DataFrame(res).set_index("variant")
    pd.set_option("display.width", 250)
    print(out.to_string())
    for label, t in (("train", base_tr), ("test", base_te)):
        if not t.empty:
            print(f"\nbaseline {label} by regime:", t.groupby("regime").apply(lambda g: stats(g)).to_dict())
            print(f"baseline {label} by setup:", t.assign(s=t.setups.str[0]).groupby("s").apply(lambda g: stats(g)).to_dict())
    print("\nCaveat: universe = today's Nifty 500 (survivorship bias); one signal per stock per date; "
          "overlapping trades; figures are per trade, not a portfolio equity curve.")


if __name__ == "__main__":
    main()
