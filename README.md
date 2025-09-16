# eToro Companion (Starter)

Tool Python per analisi, backtest e trade-assist (manuale) focalizzato su **azioni tech USA** in timeframe **daily**.

## Struttura
- `config.yaml` – universi, parametri base
- `etl/market_data.py` – download dati (yfinance)
- `research/features.py` – feature basilari (MA)
- `research/strategies.py` – strategia MA crossover
- `research/backtest.py` – backtest long-only semplice
- `execution/trade_assist.py` – proposta ordine (assistito)
- `app.py` – CLI: scarica dati, backtesta, genera segnali

## Setup rapido
```bash
python -m venv .venv
source .venv/bin/activate  # su Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Esempi
Scarica dati e backtesta:
```bash
python app.py download
python app.py backtest --strategy ma_crossover
```

Genera segnali sul close più recente:
```bash
python app.py signals --strategy ma_crossover
```
I risultati sono in `outputs/`.
