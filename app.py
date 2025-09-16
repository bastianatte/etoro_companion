import argparse
import yaml
from pathlib import Path
import pandas as pd
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

def _clip_weights(w: pd.Series, wmin: float, wmax: float) -> pd.Series:
    w = w.clip(lower=wmin, upper=wmax)
    s = w.sum()
    return w / s if s > 0 else w

def cmd_rebalance(cfg):
    import pandas as pd
    from pathlib import Path
    from etl.market_data import load_universe_data
    from research.ranking import rank_universe
    from research.portfolio import load_portfolio, save_portfolio, diff_portfolios

    # ---- Parametri da config ----
    rb = cfg["rebalance"]
    lookback = rb["lookback_days"]
    skip = rb["skip_recent_days"]
    top_n = rb["top_n"]
    min_mom = rb["min_momentum"]
    target_weight_mode = rb["target_weight"]     # "equal" | "momentum"
    trade_unit = rb["trade_unit"]
    dd_window = rb["dd_window_days"]
    dd_limit  = float(rb["dd_limit"])            # escludi se Drawdown < -dd_limit (=> drawdown > dd_limit)
    vol_window= rb["vol_window_days"]
    wmax = float(rb["max_weight"])
    wmin = float(rb["min_weight"])

    # ---- Helper pesi ----
    def _clip_weights_series(w: pd.Series, wmin: float, wmax: float) -> pd.Series:
        w = w.clip(lower=wmin, upper=wmax)
        s = w.sum()
        return w / s if s > 0 else w

    # ---- Dati ----
    df_by_symbol = load_universe_data(cfg, use_cache=True)
    ranking = rank_universe(df_by_symbol, lookback, skip, dd_window, vol_window)

    # ---- Filtro drawdown (robusto a colonne duplicate) ----
    filt = ranking.dropna(subset=["Momentum", "Drawdown"]).copy()
    col = filt.loc[:, "Drawdown"]
    if isinstance(col, pd.DataFrame):
        col = col.iloc[:, 0] # type: ignore # usa la prima se ci fossero duplicati di nome
    dd_series = col.astype(float)
    filt = filt[dd_series >= -dd_limit]       # tiene strumenti con drawdown >= -limite

    # ---- Selezione TOP per Momentum ----
    ranked = filt.sort_values("Momentum", ascending=False)
    ranked = ranked[ranked["Momentum"] >= min_mom]
    top = ranked.head(top_n).copy()

    # ---- Target Weights ----
    if len(top) > 0:
        if target_weight_mode == "equal":
            w = round(1.0 / len(top), 4)
            top["TargetWeight"] = w
        else:
            mom = top["Momentum"].clip(lower=0)
            if mom.sum() == 0:
                top["TargetWeight"] = round(1.0 / len(top), 4)
            else:
                w = mom / mom.sum()
                w = _clip_weights_series(w, wmin, wmax)
                top["TargetWeight"] = w.round(4)
    else:
        top["TargetWeight"] = 0.0

    # ---- Portfolio locale e suggerimenti ----
    out_dir = Path(cfg['paths']['outputs'])
    out_dir.mkdir(parents=True, exist_ok=True)

    pf_path = out_dir / "portfolio.csv"
    current = load_portfolio(pf_path)
    target = top[["Symbol", "TargetWeight"]].reset_index(drop=True)

    buy, sell, hold = diff_portfolios(current, target)
    suggestions = []
    for s in buy:
        suggestions.append({"Action": "BUY",  "Symbol": s, "Qty": trade_unit, "Note": "new in top"})
    for s in sell:
        suggestions.append({"Action": "SELL", "Symbol": s, "Qty": trade_unit, "Note": "out of top"})
    for s in hold:
        suggestions.append({"Action": "HOLD", "Symbol": s, "Qty": 0,           "Note": "remain in top"})

    sugg_df = pd.DataFrame(suggestions).sort_values(["Action", "Symbol"])

    # ---- Salvataggi ----
    rank_fp = out_dir / "weekly_ranking.csv"
    top_fp  = out_dir / "weekly_top.csv"
    sugg_fp = out_dir / "weekly_suggestions.csv"

    ranked.to_csv(rank_fp, index=False)
    top.to_csv(top_fp, index=False)
    sugg_df.to_csv(sugg_fp, index=False)
    save_portfolio(target, pf_path)

    # ---- Report TXT umano ----
    report = out_dir / "weekly_report.txt"
    with open(report, "w", encoding="utf-8") as f:
        f.write("WEEKLY REBALANCE REPORT\n")
        f.write(f"Top selected (N={len(top)}):\n")
        for r in top.itertuples(index=False):
            mom = getattr(r, "Momentum", float("nan"))
            dd  = getattr(r, "Drawdown", float("nan"))
            wt  = getattr(r, "TargetWeight", float("nan"))
            f.write(f"  - {r.Symbol}: wt={wt:.3f}, mom={mom:.3f}, dd={dd:.3f}\n")
        f.write("\nSuggestions:\n")
        for r in sugg_df.itertuples(index=False):
            f.write(f"  {r.Action:>4}  {r.Symbol}  qty={r.Qty}  {r.Note}\n")

    print(
        f"Rebalance OK.\n"
        f"Ranking → {rank_fp}\n"
        f"Top → {top_fp}\n"
        f"Suggerimenti → {sugg_fp}\n"
        f"Portfolio aggiornato → {pf_path}\n"
        f"Report → {report}"
    )


def cmd_weekly(cfg):
    # comodo: aggiorna dati e poi rebalance
    cmd_download(cfg)
    cmd_rebalance(cfg)

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

    sub.add_parser("rebalance", help="Calcola ranking momentum con filtri rischio e suggerimenti")
    sub.add_parser("weekly", help="Aggiorna dati e poi calcola il rebalance settimanale")



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
    elif args.cmd == "weekly":
        cmd_weekly(cfg)


if __name__ == "__main__":
    main()
