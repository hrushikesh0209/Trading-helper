"""Chart and candlestick pattern detection on daily bars (no look-ahead).

Chart patterns are read from an ATR zigzag: a swing high or low is confirmed only
once price has reversed `k` x ATR from it, so every pattern found at bar i uses
data up to bar i alone. Tolerances scale with the stock's ATR, so a "level"
means the same thing for a calm stock and a volatile one.

Bullish: double bottom, inverse head & shoulders, ascending triangle, bull flag,
         cup & handle, falling wedge (all on a breakout close)
Bearish: double top, head & shoulders, descending triangle, rising wedge
         (on a breakdown close)
Candles (TA-Lib): engulfing, hammer, inverted hammer, morning/evening star,
         piercing, dark cloud, shooting star, three white soldiers / black crows

Each chart pattern returns its measured-move target and its invalidation level,
which levels.py uses as target and stop candidates.
"""

import numpy as np
import talib

ZIG_ATR = 2.0          # reversal needed to confirm a swing
FRESH = 3              # a breakout counts for this many bars after it happens


def zigzag(h, l, c, atr, k=ZIG_ATR):
    """Confirmed swing points as (bar, price, +1 high / -1 low, confirmed_at_bar)."""
    piv = []
    n = len(c)
    ok = np.flatnonzero(~np.isnan(atr) & ~np.isnan(h))
    if len(ok) < 2:
        return piv
    i0 = ok[0]
    trend, hi_i, hi, lo_i, lo = 0, i0, h[i0], i0, l[i0]
    for i in range(i0 + 1, n):
        a = atr[i]
        if np.isnan(a) or np.isnan(h[i]):
            continue
        if trend == 0:  # until the first swing, track both extremes
            if h[i] > hi:
                hi_i, hi = i, h[i]
            if l[i] < lo:
                lo_i, lo = i, l[i]
            if hi_i < i and hi - l[i] >= k * a:
                piv.append((hi_i, hi, 1, i))
                trend, lo_i, lo = -1, i, l[i]
            elif lo_i < i and h[i] - lo >= k * a:
                piv.append((lo_i, lo, -1, i))
                trend, hi_i, hi = 1, i, h[i]
        elif trend == 1:  # rising leg: extend the high, or confirm it on a k x ATR drop
            if h[i] >= hi:
                hi_i, hi = i, h[i]
            elif hi - l[i] >= k * a:
                piv.append((hi_i, hi, 1, i))
                trend, lo_i, lo = -1, i, l[i]
        else:  # falling leg
            if l[i] <= lo:
                lo_i, lo = i, l[i]
            elif h[i] - lo >= k * a:
                piv.append((lo_i, lo, -1, i))
                trend, hi_i, hi = 1, i, h[i]
    return piv


def _fresh_cross_up(c, i, level):
    return c[i] > level and np.nanmin(c[max(0, i - FRESH):i]) <= level if i >= 1 else False


def _fresh_cross_down(c, i, level):
    return c[i] < level and np.nanmax(c[max(0, i - FRESH):i]) >= level if i >= 1 else False


def chart_patterns(h, l, c, atr, i, piv):
    """Patterns completing at bar i. `piv` = zigzag points confirmed by bar i."""
    out = []
    a = atr[i]
    if np.isnan(a) or len(piv) < 3:
        return out
    tol = max(1.0 * a, 0.03 * c[i])
    P = piv[-6:]
    kinds = [p[2] for p in P]

    # Double bottom: low, high, low (lows within tol), break above the middle high
    if len(P) >= 3 and kinds[-3:] == [-1, 1, -1]:
        (i1, l1, _, _), (ih, hh, _, _), (i2, l2, _, _) = P[-3:]
        if abs(l1 - l2) <= tol and hh - max(l1, l2) >= 3 * a and 10 <= i2 - i1 <= 150 and _fresh_cross_up(c, i, hh):
            out.append({"name": "double bottom", "dir": 1, "target": hh + (hh - min(l1, l2)),
                        "invalid": min(l1, l2), "neckline": hh})
    # Double top: high, low, high, break below the middle low
    if len(P) >= 3 and kinds[-3:] == [1, -1, 1]:
        (i1, h1, _, _), (il, ll, _, _), (i2, h2, _, _) = P[-3:]
        if abs(h1 - h2) <= tol and min(h1, h2) - ll >= 3 * a and 10 <= i2 - i1 <= 150 and _fresh_cross_down(c, i, ll):
            out.append({"name": "double top", "dir": -1, "target": ll - (max(h1, h2) - ll),
                        "invalid": max(h1, h2), "neckline": ll})
    # Inverse head & shoulders: L H L H L, middle low lowest, shoulders level, break above neckline
    if len(P) >= 5 and kinds[-5:] == [-1, 1, -1, 1, -1]:
        (a1, s1, *_), (b1, n1, *_), (a2, hd, *_), (b2, n2, *_), (a3, s2, *_) = P[-5:]
        if hd < min(s1, s2) - a and abs(s1 - s2) <= 1.5 * tol and a3 - a1 <= 200:
            neck = n1 + (n2 - n1) * (i - b1) / max(b2 - b1, 1)
            if _fresh_cross_up(c, i, neck):
                out.append({"name": "inverse head & shoulders", "dir": 1, "target": neck + (neck - hd),
                            "invalid": s2, "neckline": neck})
    # Head & shoulders top: H L H L H, middle high highest, break below neckline
    if len(P) >= 5 and kinds[-5:] == [1, -1, 1, -1, 1]:
        (a1, s1, *_), (b1, n1, *_), (a2, hd, *_), (b2, n2, *_), (a3, s2, *_) = P[-5:]
        if hd > max(s1, s2) + a and abs(s1 - s2) <= 1.5 * tol and a3 - a1 <= 200:
            neck = n1 + (n2 - n1) * (i - b1) / max(b2 - b1, 1)
            if _fresh_cross_down(c, i, neck):
                out.append({"name": "head & shoulders", "dir": -1, "target": neck - (hd - neck),
                            "invalid": s2, "neckline": neck})
    highs = [p for p in P if p[2] == 1][-3:]
    lows = [p for p in P if p[2] == -1][-3:]
    if len(highs) >= 2 and len(lows) >= 2 and i - min(highs[0][0], lows[0][0]) <= 120:
        top = max(p[1] for p in highs)
        flat_top = max(p[1] for p in highs) - min(p[1] for p in highs) <= tol
        flat_bot = max(p[1] for p in lows) - min(p[1] for p in lows) <= tol
        rising_lows = all(lows[k][1] > lows[k - 1][1] + 0.5 * a for k in range(1, len(lows)))
        falling_highs = all(highs[k][1] < highs[k - 1][1] - 0.5 * a for k in range(1, len(highs)))
        falling_lows = all(lows[k][1] < lows[k - 1][1] - 0.5 * a for k in range(1, len(lows)))
        rising_highs = all(highs[k][1] > highs[k - 1][1] + 0.5 * a for k in range(1, len(highs)))
        height = top - min(p[1] for p in lows)
        if flat_top and rising_lows and _fresh_cross_up(c, i, top):
            out.append({"name": "ascending triangle", "dir": 1, "target": top + height, "invalid": lows[-1][1], "neckline": top})
        bot = min(p[1] for p in lows)
        if flat_bot and falling_highs and _fresh_cross_down(c, i, bot):
            out.append({"name": "descending triangle", "dir": -1, "target": bot - height, "invalid": highs[-1][1], "neckline": bot})
        # Wedges: both sides slope the same way and converge; trade the break against the slope
        (hx0, hy0), (hx1, hy1) = (highs[-2][0], highs[-2][1]), (highs[-1][0], highs[-1][1])
        (lx0, ly0), (lx1, ly1) = (lows[-2][0], lows[-2][1]), (lows[-1][0], lows[-1][1])
        hs = (hy1 - hy0) / max(hx1 - hx0, 1)
        ls = (ly1 - ly0) / max(lx1 - lx0, 1)
        upper = hy1 + hs * (i - hx1)
        lower = ly1 + ls * (i - lx1)
        if falling_highs and falling_lows and hs < ls < 0 and _fresh_cross_up(c, i, upper):
            out.append({"name": "falling wedge", "dir": 1, "target": highs[0][1], "invalid": lows[-1][1], "neckline": upper})
        if rising_highs and rising_lows and 0 < hs < ls and _fresh_cross_down(c, i, lower):
            out.append({"name": "rising wedge", "dir": -1, "target": lows[0][1], "invalid": highs[-1][1], "neckline": lower})

    # Bull flag: a pole of >= max(8%, 4 ATR) within 15 bars, a 5-20 bar flag retracing <= 50%, break above the flag
    for flag_len in (5, 8, 12, 16, 20):
        p = i - flag_len
        if p - 15 < 0:
            break
        pole_lo = np.nanmin(l[p - 15:p + 1])
        pole_hi = np.nanmax(h[p - 3:p + 1])
        pole = pole_hi - pole_lo
        if pole < max(0.08 * pole_hi, 4 * a):
            continue
        flag_hi, flag_lo = np.nanmax(h[p + 1:i]), np.nanmin(l[p + 1:i])
        if flag_hi <= pole_hi + 0.5 * a and pole_hi - flag_lo <= 0.5 * pole and (flag_hi - flag_lo) <= 0.5 * pole \
                and _fresh_cross_up(c, i, flag_hi):
            out.append({"name": "bull flag", "dir": 1, "target": flag_hi + pole, "invalid": flag_lo, "neckline": flag_hi})
            break

    # Cup & handle: two rims within 5%, 30-150 bars apart, 12-35% deep, a shallow handle, break above the rim
    rims = [p for p in piv if p[2] == 1 and i - p[0] <= 170]
    if len(rims) >= 2:
        (r1i, r1, *_), (r2i, r2, *_) = rims[-2], rims[-1]
        if 30 <= r2i - r1i <= 150 and abs(r1 - r2) <= 0.05 * max(r1, r2):
            cup_lo = np.nanmin(l[r1i:r2i + 1])
            depth = (max(r1, r2) - cup_lo) / max(r1, r2)
            handle_lo = np.nanmin(l[r2i:i + 1]) if i > r2i else r2
            rim = max(r1, r2)
            if 0.12 <= depth <= 0.35 and rim - handle_lo <= (rim - cup_lo) / 3 and 3 <= i - r2i <= 25 \
                    and _fresh_cross_up(c, i, rim):
                out.append({"name": "cup & handle", "dir": 1, "target": rim + (rim - cup_lo),
                            "invalid": handle_lo, "neckline": rim})
    return out


CANDLES = {  # TA-Lib function -> (bullish name, bearish name)
    "CDLENGULFING": ("bullish engulfing", "bearish engulfing"),
    "CDLHAMMER": ("hammer", None),
    "CDLINVERTEDHAMMER": ("inverted hammer", None),
    "CDLMORNINGSTAR": ("morning star", None),
    "CDLEVENINGSTAR": (None, "evening star"),
    "CDLPIERCING": ("piercing line", None),
    "CDLDARKCLOUDCOVER": (None, "dark cloud cover"),
    "CDLSHOOTINGSTAR": (None, "shooting star"),
    "CDL3WHITESOLDIERS": ("three white soldiers", None),
    "CDL3BLACKCROWS": (None, "three black crows"),
    "CDLHANGINGMAN": (None, "hanging man"),
}


def candle_signals(o, h, l, c):
    """{name: array of bools} for every candlestick pattern, all bars at once (TA-Lib)."""
    out = {}
    for fn, (bull, bear) in CANDLES.items():
        v = getattr(talib, fn)(o, h, l, c)
        if bull:
            out[bull] = v > 0
        if bear:
            out[bear] = v < 0
    return out


def scan(o, h, l, c, atr):
    """Every chart pattern event over a stock's full history, look-ahead free:
    [(bar, pattern dict)]. Pivots are added only once confirmed."""
    piv_all = zigzag(h, l, c, atr)
    events, confirmed, j = [], [], 0
    for i in range(len(c)):
        while j < len(piv_all) and piv_all[j][3] <= i:
            confirmed.append(piv_all[j])
            j += 1
        for p in chart_patterns(h, l, c, atr, i, confirmed):
            events.append((i, p))
    return events
