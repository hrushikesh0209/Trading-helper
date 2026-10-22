"""Nifty 500 screener: market regime, sector rotation, setups, score, trade levels.

Implements references/technical_playbook.md and india_sectors.md as code. No LLM.

    python screener.py                 # screen the latest stored day, write D:\\TradingAgentsData\\screens\\
    python screener.py --date 2026-10-21
    python screener.py --rebuild       # recompute the feature cache from market.db

Features for every stock and every day are computed once and cached
(market\\features.pkl), so the daily screen and the backtest use identical numbers.
"""

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indicators as ti  # noqa: E402

ROOT = Path(r"D:\TradingAgentsData")
DB = ROOT / "market" / "market.db"
CACHE = ROOT / "market" / "features.pkl"
SCREENS = ROOT / "screens"
NIFTY, VIX = "^NSEI", "^INDIAVIX"
MIN_BARS = 270
JUMP_LOOKBACK = 260


@dataclass
class Config:
    """Every threshold and weight the playbook names; the backtest varies these."""
    min_traded_value: float = 1e8      # ₹10 crore median daily traded value
    min_price: float = 50.0
    max_extension_atr: float = 3.0     # close more than 3 ATR above EMA20 = extended
    breakout_lookback: int = 20
    breakout_volume: float = 1.5
    breakout_close_pos: float = 0.75
    base_max_range: float = 0.15
    pullback_atr: float = 1.0
    pullback_rsi: tuple = (40.0, 55.0)
    squeeze_volume: float = 1.3
    trend_rs_min: float = 0.70
    stop_atr: float = 2.0
    max_stop_pct: float = 0.10
    min_rr: float = 2.0
    target_r: float = 3.0              # target when no resistance caps it
    weights: dict = field(default_factory=lambda: {
        "rs": 0.30, "trend": 0.20, "volume": 0.15, "sector": 0.15, "setup": 0.10, "tv": 0.05, "risk": -0.10})
    # v2 defaults, chosen by backtest (backtest_report.md): momentum ranking of
    # trend-template / momentum stocks, 2 ATR initial stop trailing at 2 ATR.
    # Setups B, C and D are still tagged for context but no longer qualify a pick:
    # they lost money in both test periods.
    setups: tuple = ("A", "E")
    # "playbook" = the v1 weights above; "momentum" = weights from the factor study
    # (factor_ic.py, training period only): 12m-skip-1m momentum, 52w-high proximity,
    # RS, trend and sector, all of which predicted 15-day returns; volume and
    # oscillator factors did not.
    score_mode: str = "momentum"
    exit_mode: str = "trail"           # "fixed" = stop + target; "trail" = stop trails, no target
    trail_atr: float = 2.0             # trail = highest close since entry - trail_atr x ATR
    max_hold: int = 20                 # swing time stop, trading days
    entry_filter: str = ""             # "" | "pullback": momentum stock within 1.5 ATR of EMA20, RSI up
    regime_filter: bool = True         # risk-off: only A/E in the sector quadrants below
    # Risk-off: sectors still beating the Nifty (RS > 0 = Leading or Weakening). The
    # old Leading+Improving rule was the worst of four variants on the training period
    # (risk-off PF 0.56 vs 0.86) and cut every Healthcare leader on 2026-10-22.
    riskoff_quadrants: tuple = ("Leading", "Weakening")
    max_per_sector: int = 3
    top_n: int = 25


# ---------- features ----------

def _features(d: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c, v = d.open, d.high, d.low, d.close, d.volume
    f = pd.DataFrame(index=d.index)
    f["close"], f["open"], f["high"], f["low"] = c, o, h, l
    for n in (9, 20, 50):
        f[f"ema{n}"] = ti.ema(c, n)
    for n in (50, 150, 200):
        f[f"sma{n}"] = ti.sma(c, n)
    f["sma200_up"] = f.sma200 > f.sma200.shift(20)
    f["sma150_up"] = f.sma150 > f.sma150.shift(20)
    f["sma50_slope"] = f.sma50 / f.sma50.shift(20) - 1
    f["rsi"] = ti.rsi(c)
    f["rsi_prev"] = f.rsi.shift()
    m, s, hist = ti.macd(c)
    f["macd_hist"], f["macd_hist_prev"] = hist, hist.shift()
    pdi, mdi, adx = ti.dmi(h, l, c)
    f["adx"], f["pdi"], f["mdi"] = adx, pdi, mdi
    f["atr"] = ti.atr(h, l, c)
    f["atr_pct"] = f.atr / c
    _, f["st_dir"] = ti.supertrend(h, l, c)
    lo, mid, up = ti.bollinger(c)
    f["bb_up"], f["bb_mid"] = up, mid
    width = (up - lo) / mid
    f["squeeze_prev"] = (width.shift() <= width.shift().rolling(120).min() * 1.05)
    f["prior_high_close20"] = c.shift().rolling(20).max()
    f["prior_high_close55"] = c.shift().rolling(55).max()
    f["vol_ratio"] = v / v.shift().rolling(50).mean()
    f["close_pos"] = ((c - l) / (h - l)).where(h > l, 0.5)
    f["base_range"] = (h.shift().rolling(20).max() - l.shift().rolling(20).min()) / c
    f["hi52"], f["lo52"] = h.rolling(250).max(), l.rolling(250).min()
    for n in (1, 5, 21, 63, 126, 189, 252):
        f[f"r{n}"] = c / c.shift(n) - 1
    f["traded_value"] = (c * v).rolling(20).median()
    up_v = v.where(c > c.shift(), 0).rolling(50).sum()
    dn_v = v.where(c < c.shift(), 0).rolling(50).sum()
    f["updown_vol"] = up_v / dn_v.replace(0, np.nan)
    ob = ti.obv(c, v)
    f["obv_slope"] = (ob - ob.shift(20)) / (v.rolling(20).mean() * 20)
    f["swing_low5"] = l.rolling(5).min()
    f["swing_low10"] = l.rolling(10).min()
    f["ext_atr"] = (c - f.ema20) / f.atr
    f["circuit"] = (f.r1.abs() >= 0.095) & ((c >= h * 0.999) | (c <= l * 1.001))
    tv = ti.technical_rating(o, h, l, c, v)
    f["tv_rating"] = tv.tv_rating
    f["bars"] = np.arange(1, len(d) + 1)
    return f


def build_features(rebuild: bool = False) -> pd.DataFrame:
    """Long panel (date, symbol) of features for every stock and benchmark, cached."""
    if CACHE.exists() and not rebuild and CACHE.stat().st_mtime > DB.stat().st_mtime - 5:
        return pd.read_pickle(CACHE)
    con = sqlite3.connect(DB)
    nse_days = pd.read_sql("SELECT date FROM prices WHERE symbol=? ORDER BY date", con, params=(NIFTY,)).date
    uni = pd.read_sql("SELECT symbol, industry FROM universe", con).set_index("symbol").industry
    jumps = pd.read_sql("SELECT symbol, date FROM suspect", con)
    syms = list(uni.index) + [NIFTY, VIX, "^CRSLDX"]
    frames, t = [], time.time()
    for s in syms:
        d = pd.read_sql("SELECT date, open, high, low, close, volume FROM prices WHERE symbol=? ORDER BY date",
                        con, params=(s,), index_col="date")
        d = d[d.index.isin(nse_days)]  # NSE trading days only (crude/INR trade on holidays)
        if len(d) < 60:
            continue
        f = _features(d)
        f["symbol"] = s
        f["industry"] = uni.get(s, "Benchmark")
        jd = jumps[jumps.symbol == s].date
        if len(jd):
            pos = pd.Series(np.arange(len(f)), index=f.index)
            last_jump = pd.Series(np.nan, index=f.index)
            for j in jd:
                if j in pos.index:
                    last_jump[pos.index >= j] = pos[j]
            f["bars_since_jump"] = pos - last_jump
        else:
            f["bars_since_jump"] = np.nan
        frames.append(f.reset_index())
    panel = pd.concat(frames, ignore_index=True)
    for col in panel.columns:
        if panel[col].dtype == "float64":
            panel[col] = panel[col].astype("float32")
    panel.to_pickle(CACHE)
    print(f"features: {panel.symbol.nunique()} symbols, {len(panel):,} rows, {time.time() - t:.0f}s", file=sys.stderr)
    return panel


# ---------- regime and sectors ----------

def market_context(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-date market regime and per-(date, industry) sector strength."""
    stocks = panel[~panel.symbol.str.startswith("^")]
    n = panel[panel.symbol == NIFTY].set_index("date")
    vix = panel[panel.symbol == VIX].set_index("date").close
    breadth = stocks.assign(a50=stocks.close > stocks.sma50, a200=stocks.close > stocks.sma200) \
        .groupby("date")[["a50", "a200"]].mean()
    reg = pd.DataFrame({
        "nifty": n.close, "nifty_vs200": n.close / n.sma200 - 1, "nifty_vs50": n.close / n.sma50 - 1,
        "nifty_sma200_up": n.sma200_up, "nifty_r21": n.r21, "nifty_r63": n.r63, "nifty_r126": n.r126,
        "nifty_r189": n.r189, "nifty_r252": n.r252,
        "vix": vix, "vix_chg5": vix / vix.shift(5) - 1,
    }).join(breadth)
    on = (reg.nifty_vs200 > 0) & reg.nifty_sma200_up & (reg.nifty_vs50 > 0) & (reg.a50 > 0.6) & (reg.vix < 14)
    off = (reg.nifty_vs200 < -0.02) | (reg.a50 < 0.4) | (reg.vix > 20) | (reg.vix_chg5 > 0.25)
    reg["regime"] = np.where(off, "risk-off", np.where(on, "risk-on", "neutral"))
    reg["picks"] = reg.regime.map({"risk-on": 10, "neutral": 6, "risk-off": 3})

    sec = stocks.groupby(["date", "industry"]).agg(
        n=("r21", "size"), m21=("r21", "median"), m63=("r63", "median"), m126=("r126", "median"))
    above = stocks.assign(a50=stocks.close > stocks.sma50, a200=stocks.close > stocks.sma200) \
        .groupby(["date", "industry"])[["a50", "a200"]].mean()
    sec = sec.join(above).reset_index().merge(reg[["nifty_r21", "nifty_r63", "nifty_r126"]], left_on="date", right_index=True)
    sec["rs"] = 0.4 * (sec.m21 - sec.nifty_r21) + 0.4 * (sec.m63 - sec.nifty_r63) + 0.2 * (sec.m126 - sec.nifty_r126)
    sec = sec.sort_values(["industry", "date"])
    sec["rs_mom"] = sec.rs - sec.groupby("industry").rs.shift(20)
    sec["quadrant"] = np.select(
        [(sec.rs > 0) & (sec.rs_mom > 0), (sec.rs > 0) & (sec.rs_mom <= 0), (sec.rs <= 0) & (sec.rs_mom > 0)],
        ["Leading", "Weakening", "Improving"], "Lagging")
    sec["sector_pct"] = sec.groupby("date").rs.rank(pct=True)
    return reg, sec.set_index(["date", "industry"])


# ---------- screen one day ----------

def screen(x: pd.DataFrame, reg: pd.Series, sec: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Cross-section of one date -> scored candidates with setups and levels (all rows kept, with reasons)."""
    x = x[~x.symbol.str.startswith("^")].copy()
    x = x.join(sec[["rs", "quadrant", "sector_pct", "n"]].rename(columns={"rs": "sector_rs", "n": "sector_n"}), on="industry")
    small = x.sector_n < 5
    # IBD-style weighted relative strength vs Nifty
    x["rs_raw"] = (0.4 * (x.r63 - reg.nifty_r63) + 0.2 * (x.r126 - reg.nifty_r126)
                   + 0.2 * (x.r189 - reg.nifty_r189) + 0.2 * (x.r252 - reg.nifty_r252))
    x["rs_pct"] = x.rs_raw.rank(pct=True)
    x.loc[small, "sector_pct"] = x.loc[small, "rs_pct"]  # tiny sectors: use the stock's own RS

    veto = pd.Series("", index=x.index)
    def mark(cond, why):
        veto.loc[cond & (veto == "")] = why
    mark(x.bars < MIN_BARS, "short history")
    mark(x.bars_since_jump.notna() & (x.bars_since_jump < JUMP_LOOKBACK), "data jump in lookback")
    mark(x.traded_value < cfg.min_traded_value, "illiquid")
    mark(x.close < cfg.min_price, "low price")
    mark(x.circuit, "circuit hit")
    mark(x.ext_atr > cfg.max_extension_atr, "extended")
    mark(~x.sma200_up.astype(bool) & (x.close < x.sma200), "below falling SMA200")
    x["veto"] = veto

    A = (x.close > x.sma50) & (x.sma50 > x.sma150) & (x.sma150 > x.sma200) & x.sma200_up \
        & (x.close >= 1.3 * x.lo52) & (x.close >= 0.75 * x.hi52) & (x.rs_pct >= cfg.trend_rs_min)
    prior = x.prior_high_close20 if cfg.breakout_lookback == 20 else x.prior_high_close55
    B = (x.close > prior) & (x.vol_ratio >= cfg.breakout_volume) & (x.close_pos >= cfg.breakout_close_pos) \
        & (x.base_range <= cfg.base_max_range)
    near = ((x.close - x.ema20).abs() <= cfg.pullback_atr * x.atr) | ((x.close - x.sma50).abs() <= cfg.pullback_atr * x.atr)
    C = (x.close > x.sma200) & (x.sma50 > x.sma200) & near & x.rsi.between(*cfg.pullback_rsi) \
        & (x.rsi > x.rsi_prev) & (x.close > x.open)
    D = x.squeeze_prev & (x.close > x.bb_up) & (x.vol_ratio >= cfg.squeeze_volume)
    mom = 0.4 * x.r63 + 0.3 * x.r126 + 0.3 * x.r252
    E = (mom.rank(pct=True) >= 0.9) & (x.close > x.sma200)
    flags = {"A": A, "B": B, "C": C, "D": D, "E": E}
    names = {"A": "trend template", "B": "breakout", "C": "pullback", "D": "squeeze breakout", "E": "momentum leader"}
    x["setups"], x["tags"] = "", ""
    for k in "ABCDE":
        hit = flags[k].fillna(False)
        x.loc[hit, "tags"] += k
        if k in cfg.setups:
            x.loc[hit, "setups"] += k
    x["setup_names"] = x.tags.map(lambda s: ", ".join(names[c] for c in s))

    p = lambda s: s.rank(pct=True)
    trend = (p(x.adx) + p(x.sma50_slope) + p(x.close / x.sma200)) / 3
    volume = (p(x.vol_ratio) + p(x.updown_vol) + p(x.obv_slope)) / 3
    setup_q = (p(x.vol_ratio).where(B, 0) + p(-(x.close - x.ema20).abs() / x.atr).where(C, 0)
               + p(x.close / x.hi52).where(A | E, 0)).clip(upper=1)
    risk = (p(x.atr_pct) + p(x.ext_atr)) / 2
    tv = (x.tv_rating + 1) / 2
    w = cfg.weights
    if cfg.score_mode == "momentum":
        mom12_1 = (1 + x.r252) / (1 + x.r21) - 1
        raw = (0.35 * p(mom12_1) + 0.25 * p(x.close / x.hi52) + 0.20 * x.rs_pct
               + 0.10 * p(x.close / x.sma200) + 0.10 * x.sector_pct)
        x["score"] = (100 * raw).round(1)
    else:
        raw = (w["rs"] * x.rs_pct + w["trend"] * trend + w["volume"] * volume + w["sector"] * x.sector_pct
               + w["setup"] * setup_q + w["tv"] * tv + w["risk"] * risk)
        lo_, hi_ = w["risk"], sum(v for k, v in w.items() if k != "risk")
        x["score"] = (100 * (raw - lo_) / (hi_ - lo_)).round(1)
    x["pullback_ok"] = ((x.close - x.ema20).abs() <= 1.5 * x.atr) & (x.rsi > x.rsi_prev) & (x.close > x.sma50)

    # Trade levels (playbook section 5)
    structure = np.where(B, prior - 0.5 * x.atr, np.where(C, x.swing_low5, np.maximum(x.sma50, x.swing_low10)))
    x["entry"] = x.close
    if cfg.exit_mode == "trail":
        x["stop"] = x.close - cfg.stop_atr * x.atr  # plain ATR stop: structure stops proved too tight
    else:
        x["stop"] = np.maximum(x.close - cfg.stop_atr * x.atr, structure)
        x.loc[x.stop >= x.close - 0.5 * x.atr, "stop"] = x.close - x.atr  # structure too tight: one ATR
    risk_ps = x.entry - x.stop
    resistance = x.hi52.where(x.hi52 > x.entry * 1.02)
    if cfg.exit_mode == "trail":
        # Target 1 (2R): optionally book half there. Backtest: half-at-2R costs ~0.04 PF
        # versus trailing everything, and locks gains on about 1 trade in 5.
        x["target"] = x.entry + 2 * risk_ps
        x["target2"] = x.entry + 3 * risk_ps
    else:
        x["target"] = np.where(resistance.notna(), np.minimum(resistance, x.entry + cfg.target_r * risk_ps),
                               x.entry + cfg.target_r * risk_ps)
    x["rr"] = (x.target - x.entry) / risk_ps
    x["stop_pct"] = risk_ps / x.entry
    return x


def pick_list(x: pd.DataFrame, reg: pd.Series, cfg: Config) -> pd.DataFrame:
    """Apply vetoes, setups, risk rules, regime and sector caps -> the ranked list."""
    c = x[(x.veto == "") & (x.setups != "") & (x.stop_pct <= cfg.max_stop_pct)]
    if cfg.exit_mode == "fixed":
        c = c[c.rr >= cfg.min_rr]
    if cfg.entry_filter == "pullback":
        c = c[c.pullback_ok]
    if cfg.regime_filter and reg.regime == "risk-off":
        c = c[c.setups.str.contains("A|E") & c.quadrant.isin(list(cfg.riskoff_quadrants))]
    c = c.sort_values("score", ascending=False)
    c = c.groupby("industry", group_keys=False).head(cfg.max_per_sector)
    return c.sort_values("score", ascending=False).head(cfg.top_n)


POSITIONAL = dict(stop_atr=3.0, trail_atr=3.0, max_stop_pct=0.15, max_hold=60, top_n=10)


def positional_list(x: pd.DataFrame, reg: pd.Series, cfg: Config) -> pd.DataFrame:
    """Positional (up to 60 trading days): 3 ATR stop trailing at 3 ATR, the same rules
    the backtest ran. Provisional: the only tested setting profitable in both periods,
    and it was chosen after seeing both."""
    from dataclasses import replace
    pcfg = replace(cfg, **POSITIONAL)
    c = x.copy()
    c["stop"] = c.close - pcfg.stop_atr * c.atr
    c["stop_pct"] = (c.close - c.stop) / c.close
    c["target"] = c.close + 2 * (c.close - c.stop)
    c["target2"] = c.close + 3 * (c.close - c.stop)
    return pick_list(c, reg, pcfg)


# ---------- output ----------

COLS = ["symbol", "industry", "quadrant", "setup_names", "score", "close", "entry", "stop", "stop_pct", "stop_why",
        "atr", "target", "t1_why", "t1_hit", "target2", "t2_why", "t2_hit", "rr", "size", "patterns", "rsi", "adx",
        "vol_ratio", "rs_pct", "tv_rating", "r21", "r63", "r252"]


def write_outputs(day: str, x, picks, pos, reg_row, sec_day):
    SCREENS.mkdir(parents=True, exist_ok=True)
    # Breadth above 60% was the one market condition that helped in both test periods,
    # so it sets position size (risk 1% of capital, else 0.5%) rather than skipping days.
    size = "full (1% risk)" if reg_row.a50 > 0.6 else "half (0.5% risk)"
    picks = picks.assign(size=size)
    # Reports are swing-only by the user's choice; positional_list() stays for backtests.
    picks[COLS].to_csv(SCREENS / f"{day}_swing25.csv", index=False, float_format="%.4f")
    r = reg_row
    import timing
    t = timing.timing_on(day)
    timing_line = ("TAKE ENTRIES" if t["take_entries"] else "STAND ASIDE: no new entries today") + \
        f" (RSRS score {t['score']:+.2f}; state since {t['since']}; {t['rule']})"
    regime_md = (f"# Market regime {day}: {r.regime.upper()} (show up to {r.picks if t['take_entries'] else 0} picks)\n\n"
                 f"**Market timing:** {timing_line}\n\n"
                 f"| Signal | Value |\n|---|---|\n| Nifty 50 | {r.nifty:,.2f} |\n"
                 f"| vs SMA200 | {r.nifty_vs200:+.1%} (SMA200 {'rising' if r.nifty_sma200_up else 'falling'}) |\n"
                 f"| vs SMA50 | {r.nifty_vs50:+.1%} |\n| % of Nifty 500 above SMA50 | {r.a50:.0%} |\n"
                 f"| % above SMA200 | {r.a200:.0%} |\n| India VIX | {r.vix:.2f} ({r.vix_chg5:+.0%} in 5 days) |\n")
    (SCREENS / f"{day}_regime.md").write_text(regime_md, encoding="utf-8")
    s = sec_day.sort_values("rs", ascending=False)
    lines = [f"# Sector snapshot {day}\n", "| Sector | Stocks | Quadrant | RS vs Nifty | RS momentum (4w) | 1M | 3M | % > SMA50 | % > SMA200 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for ind, q in s.iterrows():
        lines.append(f"| {ind} | {int(q.n)} | {q.quadrant} | {q.rs:+.1%} | {q.rs_mom:+.1%} | {q.m21:+.0%} | {q.m63:+.0%} | {q.a50:.0%} | {q.a200:.0%} |")
    (SCREENS / "sector_snapshot.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (SCREENS / f"{day}_sectors.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    vetoes = x.veto.replace("", "passed").value_counts().to_dict()
    summary = {"date": day, "regime": r.regime, "picks": int(r.picks) if t["take_entries"] else 0,
               "timing": {**t, "text": timing_line}, "universe": int(len(x)),
               "vetoes": vetoes, "with_setup": int((x.setups != "").sum()),
               "swing_list": int(len(picks))}
    (SCREENS / f"{day}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def add_levels(panel: pd.DataFrame, picks: pd.DataFrame, day: str, cfg: Config) -> pd.DataFrame:
    """Replace ATR stops/targets with technical levels (levels.py): stop 0.5 ATR below the
    nearest support at least 1 ATR away, T1/T2 at the next resistances. Backtest
    (backtest_report.md, "Technical levels"): same profit factor as the 2 ATR stop,
    with a reason a chart can show."""
    import levels as lv
    out = picks.copy()
    for col in ("stop", "target", "target2", "stop_pct", "rr"):
        out[col] = out[col].astype("float64")  # the feature cache is float32
    for col in ("stop_why", "t1_why", "t2_why", "patterns"):
        out[col] = ""
    for col in ("t1_hit", "t2_hit"):
        out[col] = np.nan
    for idx, r in picks.iterrows():
        L = lv.for_symbol(panel, r.symbol, day, max_stop_pct=cfg.max_stop_pct)
        out.loc[idx, ["stop", "target", "target2"]] = [L["stop"], L["t1"], L["t2"]]
        out.loc[idx, ["stop_why", "t1_why", "t2_why"]] = [L["stop_why"], L["t1_why"], L["t2_why"]]
        out.loc[idx, ["t1_hit", "t2_hit"]] = [L["t1_hit"], L["t2_hit"]]
        out.loc[idx, "patterns"] = ", ".join(L["patterns"])
        out.loc[idx, "stop_pct"] = L["risk_pct"]
        out.loc[idx, "rr"] = L["rr1"]
    return out


def run_day(day: str | None = None, rebuild: bool = False):
    """Screen one stored day and write its files; returns (summary, swing, positional)."""
    panel = build_features(rebuild)
    reg, sec = market_context(panel)
    day = day or reg.index.max()
    x = screen(panel[panel.date == day], reg.loc[day], sec.loc[day], Config())
    picks = add_levels(panel, pick_list(x, reg.loc[day], Config()), day, Config())
    return write_outputs(day, x, picks, None, reg.loc[day], sec.loc[day]), picks, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    summary, picks, pos = run_day(a.date, a.rebuild)
    print(json.dumps(summary, indent=2))
    print("\nSWING")
    show = picks[["symbol", "industry", "quadrant", "setup_names", "score", "entry", "stop", "stop_pct", "target", "target2"]]
    print(show.to_string(index=False, float_format=lambda v: f"{v:,.2f}") if len(picks) else "  (none today)")


if __name__ == "__main__":
    main()
