import pandas as pd
import numpy as np

def _close_series(df: pd.DataFrame) -> pd.Series:
    """Ritorna SEMPRE una Series 'close' anche se ci sono colonne duplicate."""
    obj = df.loc[:, "close"] if "close" in df.columns else None
    if obj is None:
        return pd.Series(dtype=float, name="close")
    return obj.iloc[:, 0] if isinstance(obj, pd.DataFrame) else obj # type: ignore

def compute_momentum(df: pd.DataFrame, lookback_days: int, skip_recent_days: int) -> float:
    if df.empty or "close" not in df.columns:
        return np.nan
    end_date = df.index.max() - pd.Timedelta(days=skip_recent_days)
    start_date = end_date - pd.Timedelta(days=lookback_days)
    dfw = df.loc[(df.index >= start_date) & (df.index <= end_date)]
    if dfw.shape[0] < max(20, int(lookback_days * 0.5)):
        return np.nan
    s = _close_series(dfw).dropna()
    if s.empty:
        return np.nan
    start_px = s.iloc[0]
    end_px   = s.iloc[-1]
    if not np.isfinite(start_px) or start_px <= 0:
        return np.nan
    return (float(end_px) / float(start_px)) - 1.0

def compute_recent_drawdown(df: pd.DataFrame, window_days: int) -> float:
    if df.empty or "close" not in df.columns:
        return np.nan
    start_date = df.index.max() - pd.Timedelta(days=window_days)
    s = _close_series(df.loc[df.index >= start_date]).dropna()
    if s.empty:
        return np.nan
    dd = s / s.cummax() - 1.0
    mn = dd.min()
    return float(mn) if np.isscalar(mn) else float(mn.iloc[0])  # type: ignore

def compute_volatility(df: pd.DataFrame, window_days: int) -> float:
    if df.empty or "close" not in df.columns:
        return np.nan
    start_date = df.index.max() - pd.Timedelta(days=window_days)
    s = _close_series(df.loc[df.index >= start_date]).dropna()
    if s.shape[0] < max(10, int(window_days * 0.5)):
        return np.nan
    ret = s.pct_change().dropna()
    std = ret.std()
    return float(std) if np.isscalar(std) else float(std.iloc[0]) # type: ignore

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
