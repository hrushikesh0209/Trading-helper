"""TradingView-matching indicators on daily OHLCV (pandas).

Each function follows the reference implementation in TradingView's Pine Script
documentation (ta.rma, ta.ema, ta.rsi, ta.atr, ta.dmi, ta.supertrend, ...), so
values line up with a TradingView chart once past the warm-up bars. Inputs are
pandas Series on a date index; outputs are Series (or a tuple of Series).
"""

import numpy as np
import pandas as pd


# ---------- moving averages ----------

def sma(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(n, min_periods=n).mean()


def ema(x: pd.Series, n: int) -> pd.Series:
    """ta.ema: alpha = 2/(n+1), seeded with the first value (Pine reference)."""
    return x.ewm(alpha=2 / (n + 1), adjust=False).mean()


def rma(x: pd.Series, n: int) -> pd.Series:
    """ta.rma (Wilder): seeded with the SMA of the first n values, then alpha = 1/n."""
    v = x.to_numpy(dtype=float)
    out = np.full(len(v), np.nan)
    valid = np.flatnonzero(~np.isnan(v))
    if len(valid) < n:
        return pd.Series(out, index=x.index)
    start = valid[0]
    seed = start + n - 1
    out[seed] = v[start:seed + 1].mean()
    a = 1.0 / n
    for i in range(seed + 1, len(v)):
        xi = v[i]
        out[i] = out[i - 1] if np.isnan(xi) else a * xi + (1 - a) * out[i - 1]
    return pd.Series(out, index=x.index)


def wma(x: pd.Series, n: int) -> pd.Series:
    w = np.arange(1, n + 1, dtype=float)
    return x.rolling(n, min_periods=n).apply(lambda a: np.dot(a, w) / w.sum(), raw=True)


def hma(x: pd.Series, n: int = 9) -> pd.Series:
    return wma(2 * wma(x, n // 2) - wma(x, n), int(round(np.sqrt(n))))


def vwma(close: pd.Series, volume: pd.Series, n: int = 20) -> pd.Series:
    return sma(close * volume, n) / sma(volume, n)


# ---------- momentum ----------

def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    ch = close.diff()
    up, down = rma(ch.clip(lower=0), n), rma((-ch).clip(lower=0), n)
    rs = up / down
    out = 100 - 100 / (1 + rs)
    return out.where(down != 0, 100.0).where(up.notna())


def macd(close: pd.Series, fast=12, slow=26, signal=9):
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def stoch(close, high, low, n=14, smooth_k=3, smooth_d=3):
    ll, hh = low.rolling(n).min(), high.rolling(n).max()
    raw = 100 * (close - ll) / (hh - ll)
    k = sma(raw, smooth_k)
    return k, sma(k, smooth_d)


def stoch_rsi(close, smooth_k=3, smooth_d=3, rsi_n=14, stoch_n=14):
    r = rsi(close, rsi_n)
    return stoch(r, r, r, stoch_n, smooth_k, smooth_d)


def cci(high, low, close, n=20):
    tp = (high + low + close) / 3
    mean = sma(tp, n)
    mad = tp.rolling(n).apply(lambda a: np.abs(a - a.mean()).mean(), raw=True)
    return (tp - mean) / (0.015 * mad)


def williams_r(close, high, low, n=14):
    hh, ll = high.rolling(n).max(), low.rolling(n).min()
    return 100 * (close - hh) / (hh - ll)


def awesome(high, low):
    hl2 = (high + low) / 2
    return sma(hl2, 5) - sma(hl2, 34)


def momentum(close, n=10):
    return close - close.shift(n)


def ultimate(close, high, low, a=7, b=14, c=28):
    prev = close.shift(1)
    bp = close - np.minimum(low, prev)
    tr = np.maximum(high, prev) - np.minimum(low, prev)
    avg = lambda n: bp.rolling(n).sum() / tr.rolling(n).sum()
    return 100 * (4 * avg(a) + 2 * avg(b) + avg(c)) / 7


def bull_bear_power(close, high, low, n=13):
    e = ema(close, n)
    return high - e, low - e


# ---------- volatility / trend ----------

def true_range(high, low, close):
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    tr.iloc[0] = high.iloc[0] - low.iloc[0]
    return tr


def atr(high, low, close, n=14):
    return rma(true_range(high, low, close), n)


def dmi(high, low, close, n=14, adx_n=14):
    """ta.dmi: returns (+DI, -DI, ADX)."""
    up, down = high.diff(), -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=high.index).where(up.notna())
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=high.index).where(down.notna())
    tr = rma(true_range(high, low, close), n)
    plus = (100 * rma(plus_dm, n) / tr).ffill()
    minus = (100 * rma(minus_dm, n) / tr).ffill()
    s = (plus + minus).replace(0, 1)
    adx = 100 * rma((plus - minus).abs() / s, adx_n)
    return plus, minus, adx


def supertrend(high, low, close, factor=3.0, n=10):
    """ta.supertrend: returns (line, direction); direction -1 = uptrend, +1 = downtrend."""
    a = atr(high, low, close, n).to_numpy()
    hl2 = ((high + low) / 2).to_numpy()
    c = close.to_numpy()
    up, lo = hl2 + factor * a, hl2 - factor * a
    m = len(c)
    upper, lower = np.full(m, np.nan), np.full(m, np.nan)
    st, d = np.full(m, np.nan), np.full(m, np.nan)
    for i in range(m):
        if np.isnan(a[i]):
            continue
        pl = lower[i - 1] if i and not np.isnan(lower[i - 1]) else 0.0
        pu = upper[i - 1] if i and not np.isnan(upper[i - 1]) else 0.0
        lower[i] = lo[i] if (lo[i] > pl or c[i - 1] < pl) else pl
        upper[i] = up[i] if (up[i] < pu or c[i - 1] > pu) else pu
        if i == 0 or np.isnan(a[i - 1]):
            d[i] = 1
        elif st[i - 1] == upper[i - 1]:
            d[i] = -1 if c[i] > upper[i] else 1
        else:
            d[i] = 1 if c[i] < lower[i] else -1
        st[i] = lower[i] if d[i] == -1 else upper[i]
    return pd.Series(st, index=close.index), pd.Series(d, index=close.index)


def bollinger(close, n=20, mult=2.0):
    basis = sma(close, n)
    dev = mult * close.rolling(n, min_periods=n).std(ddof=0)  # ta.stdev is the population stdev
    return basis - dev, basis, basis + dev


def keltner(high, low, close, n=20, mult=1.5, atr_n=20):
    """Keltner as used by the common squeeze definition: EMA basis ± mult × ATR."""
    basis = ema(close, n)
    a = atr(high, low, close, atr_n)
    return basis - mult * a, basis, basis + mult * a


def donchian_high(high, n):
    """Highest high of the PRIOR n bars (today excluded): a breakout compares against it."""
    return high.shift(1).rolling(n).max()


def chandelier_long(high, low, close, n=22, mult=3.0):
    return high.rolling(n).max() - mult * atr(high, low, close, n)


def obv(close, volume):
    return (np.sign(close.diff()).fillna(0) * volume).cumsum()


def ichimoku(high, low, conv=9, base=26, span_b=52):
    mid = lambda n: (high.rolling(n).max() + low.rolling(n).min()) / 2
    c, b = mid(conv), mid(base)
    return c, b, (c + b) / 2, mid(span_b)  # conversion, base, lead A, lead B (undisplaced)


# ---------- TradingView Technical Ratings ----------

def technical_rating(o, h, l, c, v) -> pd.DataFrame:
    """TradingView's published Technical Ratings: MA group, oscillator group, overall.

    Rules from TradingView's Help Center ("Technical Ratings"). Two details the page
    leaves open are fixed here: "uptrend" = close above EMA50 (Stoch RSI and Bull Bear
    Power votes), and Ichimoku lead lines are compared undisplaced.
    """
    votes_ma = []
    for n in (10, 20, 30, 50, 100, 200):
        for m in (sma(c, n), ema(c, n)):
            votes_ma.append(np.sign(c - m))
    votes_ma.append(np.sign(c - hma(c, 9)))
    votes_ma.append(np.sign(c - vwma(c, v, 20)))
    conv, base, la, lb = ichimoku(h, l)
    buy = (la > lb) & (base > la) & (conv > base) & (c > conv)
    sell = (la < lb) & (base < la) & (conv < base) & (c < conv)
    votes_ma.append(buy.astype(int) - sell.astype(int))

    up = c > ema(c, 50)
    osc = []
    r = rsi(c, 14)
    osc.append(((r < 30) & (r > r.shift())).astype(int) - ((r > 70) & (r < r.shift())).astype(int))
    k, d = stoch(c, h, l, 14, 3, 3)
    osc.append(((k < 20) & (d < 20) & (k > d)).astype(int) - ((k > 80) & (d > 80) & (k < d)).astype(int))
    cc = cci(h, l, c, 20)
    osc.append(((cc < -100) & (cc > cc.shift())).astype(int) - ((cc > 100) & (cc < cc.shift())).astype(int))
    pdi, mdi, adx = dmi(h, l, c, 14, 14)
    osc.append(((pdi > mdi) & (adx > 20) & (adx > adx.shift())).astype(int)
               - ((pdi < mdi) & (adx > 20) & (adx < adx.shift())).astype(int))
    ao = awesome(h, l)
    ao_up = ((ao > 0) & (ao.shift() <= 0)) | ((ao > 0) & (ao.shift() > 0) & (ao > ao.shift()) & (ao.shift() < ao.shift(2)))
    ao_dn = ((ao < 0) & (ao.shift() >= 0)) | ((ao < 0) & (ao.shift() < 0) & (ao < ao.shift()) & (ao.shift() > ao.shift(2)))
    osc.append(ao_up.astype(int) - ao_dn.astype(int))
    mo = momentum(c, 10)
    osc.append(np.sign(mo - mo.shift()))
    ml, ms, _ = macd(c)
    osc.append(np.sign(ml - ms))
    sk, sd = stoch_rsi(c)
    osc.append(((~up) & (sk < 20) & (sd < 20) & (sk > sd)).astype(int) - (up & (sk > 80) & (sd > 80) & (sk < sd)).astype(int))
    wr = williams_r(c, h, l, 14)
    osc.append(((wr < -80) & (wr > wr.shift())).astype(int) - ((wr > -20) & (wr < wr.shift())).astype(int))
    bull, bear = bull_bear_power(c, h, l, 13)
    osc.append((up & (bear < 0) & (bear > bear.shift())).astype(int) - ((~up) & (bull > 0) & (bull < bull.shift())).astype(int))
    uo = ultimate(c, h, l)
    osc.append((uo > 70).astype(int) - (uo < 30).astype(int))

    ma_r = pd.concat(votes_ma, axis=1).mean(axis=1)
    osc_r = pd.concat(osc, axis=1).mean(axis=1)
    return pd.DataFrame({"tv_ma": ma_r, "tv_osc": osc_r, "tv_rating": (ma_r + osc_r) / 2})


def rating_label(x: float) -> str:
    if pd.isna(x):
        return "n/a"
    return ("Strong Buy" if x > 0.5 else "Buy" if x > 0.1 else "Neutral" if x >= -0.1
            else "Sell" if x >= -0.5 else "Strong Sell")
