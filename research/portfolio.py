from pathlib import Path
import pandas as pd

DEFAULT_PORTFOLIO = pd.DataFrame(columns=["Symbol","TargetWeight"])

def load_portfolio(csv_path: Path) -> pd.DataFrame:
    if csv_path.exists():
        try:
            df = pd.read_csv(csv_path)
            if {"Symbol","TargetWeight"}.issubset(df.columns):
                return df
        except Exception:
            pass
    return DEFAULT_PORTFOLIO.copy()

def save_portfolio(df: pd.DataFrame, csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)

def diff_portfolios(current: pd.DataFrame, target: pd.DataFrame):
    cur = {r.Symbol: r.TargetWeight for r in current.itertuples(index=False)}
    tgt = {r.Symbol: r.TargetWeight for r in target.itertuples(index=False)}
    sell = [s for s in cur.keys() if s not in tgt]
    buy = [s for s in tgt.keys() if s not in cur]
    hold = [s for s in cur.keys() if s in tgt]
    return buy, sell, hold
