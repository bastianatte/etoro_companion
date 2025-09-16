from dataclasses import asdict, dataclass
import pandas as pd
import numpy as np

@dataclass
class OrderProposal:
    symbol: str
    side: str          # 'buy' / 'sell'
    qty: float
    stop_loss: float|None
    take_profit: float|None
    rationale: str

def _to_float(x):
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

def proposals_from_signals(df: pd.DataFrame, strat_fn, symbol: str):
    row = df.iloc[-1]
    px = _to_float(row['close'])
    sig = strat_fn(row)

    if sig.buy:
        return asdict(OrderProposal(
            symbol=symbol, side='buy', qty=10,
            stop_loss=round(px*0.95, 2), take_profit=round(px*1.05, 2),
            rationale='MA50>MA200 crossover (buy)'))
    if sig.sell:
        return asdict(OrderProposal(
            symbol=symbol, side='sell', qty=10,
            stop_loss=round(px*1.05, 2), take_profit=round(px*0.95, 2),
            rationale='MA50<MA200 crossover (sell)'))
    return None
