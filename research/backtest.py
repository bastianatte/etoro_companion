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
        return float(x.iloc[0]) if getattr(x, "shape", (0,))[0] > 0 else float(x)
    arr = np.asarray(x).ravel()
    return float(arr[-1])

def run_backtest(df: pd.DataFrame, strat_fn, symbol: str, initial_cash: float=100000.0):
    # Long-only, entra su buy, esce su sell, size = all-in
    cash = initial_cash
    position = 0.0
    entry_price = 0.0
    equity_curve = []

    for dt, row in df.iterrows():
        px = _to_float(row['close'])
        sig = strat_fn(row)

        # Exit on sell
        if sig.sell and position > 0:
            cash = position * px
            position = 0.0

        # Enter on buy
        if sig.buy and position == 0:
            position = cash / px
            entry_price = px
            cash = 0.0

        # Mark-to-market
        equity = cash + position * px
        equity_curve.append((dt, equity))

    # Close any open position at last price
    last_px = _to_float(df['close'].iloc[-1])
    if position > 0:
        equity = cash + position * last_px
    else:
        equity = cash

    curve = pd.DataFrame(equity_curve, columns=['date','equity']).set_index('date')
    curve['returns'] = curve['equity'].pct_change().fillna(0.0)

    # Metrics
    tot_ret = curve['equity'].iloc[-1] / initial_cash - 1.0
    years = max((curve.index[-1] - curve.index[0]).days / 365.25, 1e-9)
    cagr = (1.0 + tot_ret) ** (1/years) - 1.0 if years > 0 else 0.0
    dd = (curve['equity'] / curve['equity'].cummax() - 1.0).min()
    sharpe = np.sqrt(252) * (curve['returns'].mean() / (curve['returns'].std() + 1e-9))

    return {
        'Symbol': symbol,
        'TotalReturn': round(tot_ret, 4),
        'CAGR': round(cagr, 4),
        'MaxDrawdown': round(dd, 4),
        'Sharpe': round(sharpe, 2),
        'TradesApprox': int(df['signal_buy'].sum())  # proxy
    }
