"""RSRS market-timing overlay: when to take new swing entries at all (no LLM).

RSRS (resistance-support relative strength; Everbright Securities, reproduced in
hugo2046/QuantsPlaybook) measures how firmly the Nifty 50's support is rising
against its resistance:
  beta  = slope of the daily high regressed on the daily low over N = 18 days
  z     = beta's z-score over the last M = 600 days
  score = z x R-squared of that regression (the "modified" RSRS)
State: "in" after the score rises above +0.7, "stand aside" after it falls below
-0.7; in between, the last state holds. While standing aside, no new entries are
taken; open trades keep running their own stops.

Backtest (research/REPORT_awesome_round2.md): chosen on the training period;
on the test period max drawdown -8.2% vs -15.6% and CAGR 9.4% vs 5.8%; lower
drawdown in 27 of 27 parameter settings tried.

    python timing.py            # today's state and recent history
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DB = Path(r"D:\TradingAgentsData\market\market.db")
N, M, ON, OFF = 18, 600, 0.7, -0.7


def rsrs_score(high: np.ndarray, low: np.ndarray, n: int = N, m: int = M) -> np.ndarray:
    beta, r2 = np.full(len(high), np.nan), np.full(len(high), np.nan)
    for i in range(n - 1, len(high)):
        x, y = low[i - n + 1:i + 1], high[i - n + 1:i + 1]
        if np.isnan(x).any() or np.isnan(y).any():
            continue
        b, a = np.polyfit(x, y, 1)
        ss = ((y - y.mean()) ** 2).sum()
        beta[i] = b
        r2[i] = 1 - ((y - (a + b * x)) ** 2).sum() / ss if ss else np.nan
    s = pd.Series(beta)
    z = (s - s.rolling(m, min_periods=m // 2).mean()) / s.rolling(m, min_periods=m // 2).std()
    return (z * pd.Series(r2)).to_numpy()


def states(score: np.ndarray, on: float = ON, off: float = OFF) -> np.ndarray:
    out, state = np.ones(len(score)), 1.0
    for i, v in enumerate(score):
        if not np.isnan(v):
            if v > on:
                state = 1.0
            elif v < off:
                state = 0.0
        out[i] = state
    return out


def timing_series(db: Path = DB) -> pd.DataFrame:
    """Per NSE trading day: RSRS score and state (1 = take entries, 0 = stand aside)."""
    con = sqlite3.connect(db)
    n = pd.read_sql("SELECT date, high, low FROM prices WHERE symbol='^NSEI' ORDER BY date", con, index_col="date")
    score = rsrs_score(n.high.to_numpy(float), n.low.to_numpy(float))
    return pd.DataFrame({"score": score, "state": states(score)}, index=n.index)


def timing_on(day: str, ts: pd.DataFrame | None = None) -> dict:
    """The state on `day` (or the last trading day before it), with when it last changed."""
    ts = timing_series() if ts is None else ts
    ts = ts[ts.index <= day]
    st = ts.state.iloc[-1]
    flips = ts.index[ts.state.diff().fillna(0) != 0]
    since = flips[-1] if len(flips) else ts.index[0]
    return {"date": ts.index[-1], "take_entries": bool(st == 1.0), "score": round(float(ts.score.iloc[-1]), 2),
            "since": since, "rule": f"RSRS {N}/{M}: stand aside below {OFF}, re-enter above {ON}"}


def main():
    ts = timing_series()
    t = timing_on(ts.index[-1], ts)
    word = "TAKE ENTRIES" if t["take_entries"] else "STAND ASIDE (no new entries)"
    print(f"{t['date']}: {word} | RSRS score {t['score']:+.2f} | state since {t['since']} | {t['rule']}")
    last = ts.tail(250)
    print(f"last 250 sessions: in the market {100 * last.state.mean():.0f}% of days; "
          f"switches: {int((last.state.diff().abs() > 0).sum())}")
    print(ts.tail(10).round(2).to_string())


if __name__ == "__main__":
    sys.exit(main())
