from dataclasses import dataclass
import pandas as pd

@dataclass
class StrategySignal:
    buy: bool
    sell: bool

def _to_bool(x) -> bool:
    # Gestisce scalari pandas/numpy e Series lunghe 1
    if pd.api.types.is_scalar(x):
        return bool(x)
    if hasattr(x, "item"):
        try:
            return bool(x.item())
        except Exception:
            pass
    # fallback: ultima posizione
    if hasattr(x, "iloc"):
        return bool(x.iloc[-1])
    return bool(x)

def ma_crossover_signal(row) -> StrategySignal:
    buy = _to_bool(row["signal_buy"])
    sell = _to_bool(row["signal_sell"])
    return StrategySignal(buy=buy, sell=sell)

def get_strategy(name: str):
    if name == 'ma_crossover':
        return ma_crossover_signal
    raise ValueError(f"Strategia non supportata: {name}")
