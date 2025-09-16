import pandas as pd

def make_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out['ma50'] = out['close'].rolling(50).mean()
    out['ma200'] = out['close'].rolling(200).mean()
    out['signal_buy'] = (out['ma50'].shift(1) <= out['ma200'].shift(1)) & (out['ma50'] > out['ma200'])
    out['signal_sell'] = (out['ma50'].shift(1) >= out['ma200'].shift(1)) & (out['ma50'] < out['ma200'])
    return out.dropna().copy()
