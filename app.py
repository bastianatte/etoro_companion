import argparse
import yaml
from pathlib import Path
from etl.market_data import load_universe_data
from research.features import make_features
from research.strategies import get_strategy
from research.backtest import run_backtest
from execution.trade_assist import proposals_from_signals
from research.ranking import rank_universe
from research.portfolio import load_portfolio, save_portfolio, diff_portfolios


def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)    

def _ensure_outputs(cfg):
    out_dir = Path(cfg['paths']['outputs'])
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir

def cmd_rebalance(cfg):
    # parametri
    lookback = cfg["rebalance"]["lookback_days"]
    skip = cfg["rebalance"]["skip_recent_days"]
    top_n = cfg["rebalance"]["top_n"]
    min_mom = cfg["rebalance"]["min_momentum"]
    target_weight_mode = cfg["rebalance"]["target_weight"]
    trade_unit = cfg["rebalance"]["trade_unit"]

    # dati
    df_by_symbol = load_universe_data(cfg, use_cache=True)
    ranking = rank_universe(df_by_symbol, lookback, skip)

    # selezione top
    ranked = ranking.dropna(subset=["Momentum"]).sort_values("Momentum", ascending=False)
    ranked = ranked[ranked["Momentum"] >= min_mom]
    top = ranked.head(top_n).copy()

    # target weights
    if target_weight_mode == "equal" and len(top) > 0:
        w = round(1.0 / len(top), 4)
        top["TargetWeight"] = w
    else:
        top["TargetWeight"] = 0.0

    # portfolio corrente (locale, non eToro)
    out_dir = _ensure_outputs(cfg)
    pf_path = out_dir / "portfolio.csv"
    current = load_portfolio(pf_path)
    target = top[["Symbol","TargetWeight"]].reset_index(drop=True)

    # differenze -> suggerimenti di azione
    buy, sell, hold = diff_portfolios(current, target)

    # costruisci tabella suggerimenti
    import pandas as pd
    suggestions = []
    for s in buy:
        suggestions.append({"Action":"BUY", "Symbol":s, "Qty":trade_unit, "Note":"new in top"})
    for s in sell:
        suggestions.append({"Action":"SELL", "Symbol":s, "Qty":trade_unit, "Note":"out of top"})
    for s in hold:
        suggestions.append({"Action":"HOLD", "Symbol":s, "Qty":0, "Note":"remain in top"})

    sugg_df = pd.DataFrame(suggestions).sort_values(["Action","Symbol"])
    # salvataggi
    rank_fp = out_dir / "weekly_ranking.csv"
    top_fp = out_dir / "weekly_top.csv"
    sugg_fp = out_dir / "weekly_suggestions.csv"
    ranked.to_csv(rank_fp, index=False)
    target.to_csv(top_fp, index=False)
    sugg_df.to_csv(sugg_fp, index=False)

    # aggiorna portfolio locale ai nuovi target
    save_portfolio(target, pf_path)

    print(f"Rebalance OK.\nRanking → {rank_fp}\nTop → {top_fp}\nSuggerimenti → {sugg_fp}\nPortfolio aggiornato → {pf_path}")

def cmd_download(cfg):
    df_by_symbol = load_universe_data(cfg)
    print(f"Scaricati {len(df_by_symbol)} strumenti. Salvati in {cfg['paths']['data_processed']}.")

def cmd_backtest(cfg, strategy_name):
    strat = get_strategy(strategy_name)
    df_by_symbol = load_universe_data(cfg, use_cache=True)
    results = []
    for symbol, df in df_by_symbol.items():
        feats = make_features(df)
        res = run_backtest(feats, strat, symbol=symbol, initial_cash=cfg['main']['initial_cash'])
        results.append(res)

    # 👉 assicura che la cartella outputs esista
    from pathlib import Path
    out_dir = Path(cfg['paths']['outputs'])
    out_dir.mkdir(parents=True, exist_ok=True)

    # salva riepilogo
    import pandas as pd
    summary = pd.DataFrame(results).sort_values("CAGR", ascending=False)
    out = out_dir / f"backtest_summary_{strategy_name}.csv"
    summary.to_csv(out, index=False)
    print(f"Backtest completato. Riepilogo: {out}")


def cmd_signals(cfg, strategy_name):
    strat = get_strategy(strategy_name)
    df_by_symbol = load_universe_data(cfg, use_cache=True)
    props = []
    for symbol, df in df_by_symbol.items():
        feats = make_features(df)
        prop = proposals_from_signals(feats, strat, symbol)
        if prop is not None:
            props.append(prop)
    if props:
        from pprint import pprint
        print("Proposte ordine:")
        for p in props:
            pprint(p)
    else:
        print("Nessuna proposta ordine oggi.")

def main():
    parser = argparse.ArgumentParser(description="eToro Companion CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("download", help="Scarica/aggiorna i dati dell'universo dal config")

    p_bt = sub.add_parser("backtest", help="Esegue backtest su tutto l'universo")
    p_bt.add_argument("--strategy", default="ma_crossover")

    p_sig = sub.add_parser("signals", help="Genera proposte ordine sui dati più recenti")
    p_sig.add_argument("--strategy", default="ma_crossover")

    sub.add_parser("rebalance", help="Calcola ranking momentum e suggerimenti di ribilanciamento")


    args = parser.parse_args()
    cfg = load_config()
    if args.cmd == "download":
        cmd_download(cfg)
    elif args.cmd == "backtest":
        cmd_backtest(cfg, args.strategy)
    elif args.cmd == "signals":
        cmd_signals(cfg, args.strategy)
    elif args.cmd == "rebalance":
        cmd_rebalance(cfg)


if __name__ == "__main__":
    main()
