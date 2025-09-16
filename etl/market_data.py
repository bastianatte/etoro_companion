from pathlib import Path
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
import yaml

def _today_str():
    return datetime.now(timezone.utc).date().isoformat()

def load_universe_data(cfg, use_cache=True):
    symbols = cfg['main']['universe']
    tf = cfg['main']['timeframe']
    start = cfg['main']['start_date']
    end = cfg['main']['end_date'] or _today_str()
    p_raw = Path(cfg['paths']['data_raw'])
    p_proc = Path(cfg['paths']['data_processed'])
    p_proc.mkdir(parents=True, exist_ok=True)

    result = {}
    for sym in symbols:
        fp = p_proc / f"{sym}_{tf}.parquet"
        if fp.exists() and use_cache:
            df = pd.read_parquet(fp)
        else:
            df = yf.download(sym, start=start, end=end, interval=tf, auto_adjust=True, progress=False)
            df = df.rename(columns=str.lower)
            df = df[['open','high','low','close','volume']].dropna().copy()
            df.index.name = 'date'
            df.to_parquet(fp)
        result[sym] = result.get(sym, df)
    return result
