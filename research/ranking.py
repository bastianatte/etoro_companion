import pandas as pd
import numpy as np

def _to_float(x):
    import pandas as pd, numpy as np
    if pd.api.types.is_scalar(x):
        return float(x)

    if hasattr(x, "item"):
        try:
            return float(x.item())
        except Exception:
            pass

    if hasattr(x, "iloc"):
        if len(x) > 0:
            val = x.iloc[0]
            # se è numpy, converti, se è già float Python, ritorna
            return float(val)

    arr = np.asarray(x).ravel()
    if arr.size:
        return float(arr[0])
    return np.nan


def compute_momentum_rank(df: pd.DataFrame, lookback_days: int = 126, skip_recent_days: int = 5) -> float:
    """
    Momentum = rendimento percentuale dall'inizio finestra (lookback)
    fino a 'oggi - skip_recent_days'. Se la finestra è corta → NaN.
    """
    if df.empty or "close" not in df.columns:
        return np.nan

    end_date = df.index.max() - pd.Timedelta(days=skip_recent_days)
    start_date = end_date - pd.Timedelta(days=lookback_days)
    dfw = df.loc[(df.index >= start_date) & (df.index <= end_date)]
    if dfw.shape[0] < max(20, int(lookback_days * 0.5)):
        return np.nan

    start_px = _to_float(dfw["close"].iloc[:1])  # primo valore
    end_px   = _to_float(dfw["close"].iloc[-1:]) # ultimo valore
    if not np.isfinite(start_px) or start_px <= 0:
        return np.nan
    return (end_px / start_px) - 1.0

def rank_universe(df_by_symbol: dict, lookback_days: int, skip_recent_days: int) -> pd.DataFrame:
    rows = []
    for sym, df in df_by_symbol.items():
        mom = compute_momentum_rank(df, lookback_days, skip_recent_days)
        rows.append({"Symbol": sym, "Momentum": mom})
    out = pd.DataFrame(rows)
    out["Rank"] = out["Momentum"].rank(ascending=False, method="dense")
    return out.sort_values(["Rank","Symbol"]).reset_index(drop=True)
