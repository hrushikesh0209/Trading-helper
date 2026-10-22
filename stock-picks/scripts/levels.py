"""Support / resistance levels for stop-loss and targets, chosen adaptively.

Candidates (every one carries a type and a reason):
  supports     confirmed swing lows (60 bars), EMA20, SMA50, prior week's pivot S1/S2,
               breakout level, invalidation level of a fresh bullish chart pattern
  resistances  confirmed swing highs (250 bars), 52-week high, weekly pivot R1/R2,
               Fibonacci 1.272 / 1.618 extensions (near highs), measured-move target of
               a fresh bullish chart pattern (double bottom, flag, triangle, ...)

Choice:
- fixed (v3): stop 0.5 ATR below the highest support 1-3.5 ATR under entry; T1 = first
  resistance >= 1.5R, T2 = the next.
- adaptive (v4): uses level_stats.json, measured on the TRAINING period only
  (calibrate_levels.py): for each level type and distance (in ATR), how often a support
  held and how often a resistance was reached within 20 trading days, against an
  ordinary price at the same distance. Stop = the support whose type held best
  relative to that baseline (falls back to 2 ATR when none beats it); T1 / T2 = the
  resistances with the highest expected gain (hit rate x distance in R). So the level
  and its method change with the numbers: a swing high one day, a measured move or a
  Fibonacci extension another.
"""

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

SWING = 3
STATS = Path(r"D:\TradingAgentsData\market\level_stats.json")
BUCKETS = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.5, 8.0, 12.0]  # ATR-distance bucket edges


MIN_LIFT = 0.02  # a support type must hold 2 points more often than an ordinary price to be preferred


def context(h, c, i, atr) -> str:
    """Calibration context: at the 52-week high (no overhead supply) or below it."""
    hi52 = np.nanmax(h[max(0, i - 249):i + 1])
    return "at 52w high" if c[i] >= hi52 - atr else "below 52w high"


def bucket(d_atr: float) -> str:
    for edge in BUCKETS:
        if d_atr <= edge:
            return f"<={edge:g}"
    return f">{BUCKETS[-1]:g}"


def _swings(h, l, end, look_lo=60, look_hi=250):
    lows, highs = [], []
    for k in range(max(SWING, end - look_hi), end - SWING + 1):
        if k >= end - look_lo and l[k] == np.nanmin(l[k - SWING:k + SWING + 1]):
            lows.append(k)
        if h[k] == np.nanmax(h[k - SWING:k + SWING + 1]):
            highs.append(k)
    return lows, highs


def week_ids(dates) -> np.ndarray:
    return np.array([date.fromisoformat(d).isocalendar()[0] * 100 + date.fromisoformat(d).isocalendar()[1] for d in dates])


def _weekly_pivots(weeks, h, l, c, end):
    this = weeks[end]
    prev_mask = weeks[:end + 1] < this
    if not prev_mask.any():
        return {}
    prev = weeks[:end + 1][prev_mask].max()
    ks = np.flatnonzero(weeks[:end + 1] == prev)
    H, L, C = np.nanmax(h[ks]), np.nanmin(l[ks]), c[ks[-1]]
    P = (H + L + C) / 3
    return {"R1": 2 * P - L, "R2": P + (H - L), "S1": 2 * P - H, "S2": P - (H - L)}


def candidates(dates, h, l, c, i, atr, ema20=None, sma50=None, breakout=None, weeks=None, pattern_events=None):
    """All support and resistance candidates at bar i: lists of (price, type, reason)."""
    entry = c[i]
    weeks = week_ids(dates) if weeks is None else weeks
    lows, highs = _swings(h, l, i)
    piv = _weekly_pivots(weeks, h, l, c, i)
    sup = [(l[k], "swing low", f"swing low {dates[k]}") for k in lows]
    if ema20 is not None and not np.isnan(ema20):
        sup.append((ema20, "EMA20", "EMA20"))
    if sma50 is not None and not np.isnan(sma50):
        sup.append((sma50, "SMA50", "SMA50"))
    for name in ("S1", "S2"):
        if name in piv:
            sup.append((piv[name], f"pivot {name}", f"weekly pivot {name}"))
    if breakout is not None and not np.isnan(breakout) and entry > breakout:
        sup.append((breakout, "breakout level", "breakout level (prior 20-day closing high)"))
    res = [(h[k], "swing high", f"swing high {dates[k]}") for k in highs if h[k] > entry]
    hi52 = np.nanmax(h[max(0, i - 249):i + 1])
    if hi52 > entry:
        res.append((hi52, "52-week high", "52-week high"))
    for name in ("R1", "R2"):
        if name in piv and piv[name] > entry:
            res.append((piv[name], f"pivot {name}", f"weekly pivot {name}"))
    if lows and highs:
        k0 = lows[-1]
        top = np.nanmax(h[k0:i + 1])
        span = top - l[k0]
        if span > 0 and entry >= top - atr:
            res.append((l[k0] + 1.272 * span, "fib 1.272", "Fibonacci 1.272 extension"))
            res.append((l[k0] + 1.618 * span, "fib 1.618", "Fibonacci 1.618 extension"))
    for k, p in (pattern_events or []):  # bullish chart patterns completed in the last 10 bars
        if i - 10 <= k <= i and p["dir"] == 1:
            if p["target"] > entry:
                res.append((p["target"], "measured move", f"{p['name']} measured move"))
            if p["invalid"] < entry:
                sup.append((p["invalid"], "pattern invalidation", f"{p['name']} invalidation level"))
    return sup, res


_STATS_CACHE = {}


def load_stats():
    if "s" not in _STATS_CACHE:
        _STATS_CACHE["s"] = json.loads(STATS.read_text()) if STATS.exists() else None
    return _STATS_CACHE["s"]


def _rate(table, typ, b, min_n=50):
    cell = (table.get(typ) or {}).get(b)
    return None if not cell or cell[0] < min_n else cell[1] / cell[0]


def levels(dates, h, l, c, i, atr, ema20=None, sma50=None, breakout=None, mode="adaptive", weeks=None,
           pattern_events=None, min_gap_atr=1.0, buffer_atr=0.5, fallback_atr=2.0, max_gap_atr=3.5,
           max_stop_pct=0.10, t1_min_r=1.5, stop_mode=None):
    """Stop and targets for an entry at close c[i]: prices, reasons, and (adaptive) hit rates.

    stop_mode defaults to "fixed" even in adaptive mode: no support type held better than
    an ordinary price at the same distance (calibration), and adaptive stops tested no
    better (backtest_report.md). Targets are adaptive, which helped in both periods."""
    stop_mode = stop_mode or "fixed"
    entry = c[i]
    sup, res = candidates(dates, h, l, c, i, atr, ema20, sma50, breakout, weeks, pattern_events)
    stats = load_stats() if mode == "adaptive" else None
    if stats:
        ctx = context(h, c, i, atr)
        stats = {"support": stats["support"].get(ctx, {}), "resistance": stats["resistance"].get(ctx, {})}
    lo_ok, hi_ok = entry - max_gap_atr * atr, entry - min_gap_atr * atr
    in_range = [s for s in sup if lo_ok <= s[0] <= hi_ok]
    stop, stop_why, stop_hold = entry - fallback_atr * atr, f"{fallback_atr:g} ATR below entry", None
    if stats and stop_mode == "adaptive":
        scored = []
        for p, typ, why in in_range:
            b = bucket((entry - p) / atr)
            r, base = _rate(stats["support"], typ, b), _rate(stats["support"], "baseline", b, 1)
            if r is not None and base is not None:
                scored.append((r - base, p, why, r))
        if scored:
            lift, p, why, r = max(scored)
            if lift >= MIN_LIFT:
                stop, stop_why, stop_hold = p - buffer_atr * atr, f"{buffer_atr:g} ATR below {why} (₹{p:,.2f})", r
        if stop_hold is None:
            stop_why = f"{fallback_atr:g} ATR below entry (no support type here held better than average)"
    elif in_range:
        p, _, why = max(in_range)
        stop, stop_why = p - buffer_atr * atr, f"{buffer_atr:g} ATR below {why} (₹{p:,.2f})"
    else:
        stop_why = f"{fallback_atr:g} ATR below entry (no support {min_gap_atr:g}-{max_gap_atr:g} ATR below)"
    if (entry - stop) / entry > max_stop_pct:
        stop, stop_why = entry * (1 - max_stop_pct), f"capped at {max_stop_pct:.0%} below entry"
    risk = entry - stop

    # Resistances, deduplicated by price; R multiples as fallbacks
    seen = {}
    for p, typ, why in sorted(res):
        seen.setdefault(round(p, 2), (typ, why))
    for m in (2.0, 3.0):
        seen.setdefault(round(entry + m * risk, 2), ("R multiple", f"{m:g}R (no nearer resistance)"))
    cands = [(p, t, w) for p, (t, w) in sorted(seen.items()) if p >= entry + t1_min_r * risk]

    def hit(p, typ):
        if not stats:
            return None
        b = bucket((p - entry) / atr)
        r = _rate(stats["resistance"], typ, b)
        return r if r is not None else _rate(stats["resistance"], "baseline", b, 1)

    if stats:
        ev = [((hit(p, t) or 0) * (p - entry) / risk, p, t, w) for p, t, w in cands]
        best = max(ev) if ev else None
        t1, t1_type, t1_why = (best[1], best[2], best[3]) if best else (entry + 2 * risk, "R multiple", "2R")
        later = [e for e in ev if e[1] >= t1 + 0.5 * risk]
        b2 = max(later) if later else None
        t2, t2_type, t2_why = (b2[1], b2[2], b2[3]) if b2 else (t1 + risk, "R multiple", "1R beyond T1")
    else:
        t1, t1_type, t1_why = cands[0] if cands else (entry + 2 * risk, "R multiple", "2R")
        rest = [x for x in cands if x[0] >= t1 + 0.5 * risk]
        t2, t2_type, t2_why = rest[0] if rest else (t1 + risk, "R multiple", "1R beyond T1")
    return {"entry": entry, "stop": stop, "stop_why": stop_why, "stop_hold": stop_hold, "risk_pct": risk / entry,
            "t1": t1, "t1_why": t1_why, "t1_hit": hit(t1, t1_type), "t2": t2, "t2_why": t2_why, "t2_hit": hit(t2, t2_type),
            "rr1": (t1 - entry) / risk, "rr2": (t2 - entry) / risk}


def for_symbol(panel: pd.DataFrame, symbol: str, day: str, mode="adaptive", **kw) -> dict:
    """Levels for one stock on one stored day, from the feature panel (patterns scanned on the fly)."""
    import patterns as pt
    d = panel[(panel.symbol == symbol) & (panel.date <= day)].sort_values("date")
    o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    atr = d.atr.to_numpy(float)
    i = len(d) - 1
    row = d.iloc[-1]
    ev = [(k, p) for k, p in pt.scan(o, h, l, c, atr) if k >= i - 10]
    out = levels(d.date.to_numpy(), h, l, c, i, float(row.atr), float(row.ema20), float(row.sma50),
                 float(row.prior_high_close20), mode=mode, pattern_events=ev, **kw)
    out["patterns"] = sorted({p["name"] for k, p in ev})
    return out
