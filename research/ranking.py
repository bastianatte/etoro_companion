import pandas as pd
import numpy as np

def _series_last(s: pd.Series):
    # scalare sicuro dall'ultima osservazione
    return s.iat[-1] if len(s) else np.nan

def compute_momentum(df: pd.DataFrame, lookback_days: int, skip_recent_days: int) -> float:
    if df.empty or "close" not in df.columns:
        return np.nan
    end_date = df.index.max() - pd.Timedelta(days=skip_recent_days)
    start_date = end_date - pd.Timedelta(days=lookback_days)
    dfw = df.loc[(df.index >= start_date) & (df.index <= end_date)]
    if dfw.shape[0] < max(20, int(lookback_days * 0.5)):
        return np.nan
    start_px = dfw["close"].iloc[:1].iat[0]
    end_px   = dfw["close"].iloc[-1:].iat[0]
    if not np.isfinite(start_px) or start_px <= 0:
        return np.nan
    return (end_px / start_px) - 1.0

def compute_recent_drawdown(df: pd.DataFrame, window_days: int) -> float:
    if df.empty or "close" not in df.columns:
        return np.nan
    start_date = df.index.max() - pd.Timedelta(days=window_days)
    d = df.loc[df.index >= start_date, ["close"]].copy()
    if d.empty:
        return np.nan
    cummax = d["close"].cummax()
    dd = d["close"] / cummax - 1.0
    return dd.min()  # es. -0.32 = -32%

def compute_volatility(df: pd.DataFrame, window_days: int) -> float:
    if df.empty or "close" not in df.columns:
        return np.nan
    start_date = df.index.max() - pd.Timedelta(days=window_days)
    d = df.loc[df.index >= start_date, ["close"]].copy()
    if d.shape[0] < max(10, int(window_days * 0.5)):
        return np.nan
    ret = d["close"].pct_change().dropna()
    return float(ret.std()) if len(ret) else np.nan

def rank_universe(df_by_symbol: dict, lookback_days: int, skip_recent_days: int,
                  dd_window_days: int, vol_window_days: int) -> pd.DataFrame:
    rows = []
    for sym, df in df_by_symbol.items():
        mom = compute_momentum(df, lookback_days, skip_recent_days)
        dd  = compute_recent_drawdown(df, dd_window_days)
        vol = compute_volatility(df, vol_window_days)
        rows.append({"Symbol": sym, "Momentum": mom, "Drawdown": dd, "Volatility": vol})
    out = pd.DataFrame(rows)
    out["Rank"] = out["Momentum"].rank(ascending=False, method="dense")
    return out.sort_values(["Rank","Symbol"]).reset_index(drop=True)
