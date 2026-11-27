"""CLI del trader autonomo. Tutte le regole di rischio sono applicate qui, prima di ogni ordine.

Uso (dalla cartella del progetto):
  python -m trader.cli status
  python -m trader.cli search NVDA
  python -m trader.cli history NVDA
  python -m trader.cli buy NVDA 25 --sl 0.12 --reason "..."
  python -m trader.cli sell 3128298535 --reason "..."        (per positionId)
  python -m trader.cli set-sl 3128298535 --pct 0.15 --reason "..."
  python -m trader.cli note "testo"
Aggiungi --dry-run per simulare senza inviare ordini.
Se esiste il file STOP nella cartella del progetto, ogni ordine viene rifiutato.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from pathlib import Path

import yaml

from trader.etoro import EtoroClient, EtoroError, ORDER_STATUS, ROOT

JOURNAL_DIR = ROOT / "journal"
TRADES_CSV = JOURNAL_DIR / "trades.csv"
STOP_FILE = ROOT / "STOP"
TRADE_FIELDS = ["timestamp", "action", "symbol", "instrument_id", "position_id", "amount_usd",
                "units", "stop_loss", "status", "order_id", "reason", "approved_by_user", "price"]


def rules() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["trader"]


def now() -> dt.datetime:
    return dt.datetime.now()


# ---------------- Journal ----------------
def log_trade(row: dict) -> None:
    JOURNAL_DIR.mkdir(exist_ok=True)
    new = not TRADES_CSV.exists()
    with open(TRADES_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in TRADE_FIELDS})


def append_daily(text: str) -> Path:
    JOURNAL_DIR.mkdir(exist_ok=True)
    fp = JOURNAL_DIR / f"{now():%Y-%m-%d}.md"
    with open(fp, "a", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n\n")
    return fp


def orders_count() -> tuple[int, int]:
    """Ordini (buy/sell) inviati oggi e nella settimana ISO corrente, esclusi quelli rifiutati e quelli approvati dall'utente."""
    if not TRADES_CSV.exists():
        return 0, 0
    today = now().date()
    week = today.isocalendar()[:2]
    d = w = 0
    with open(TRADES_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["action"] not in ("BUY", "SELL") or r["status"] in ("Rejected", "DRY-RUN", "ERROR"):
                continue
            if r.get("approved_by_user") == "yes":
                continue
            t = dt.datetime.fromisoformat(r["timestamp"]).date()
            if t == today:
                d += 1
            if t.isocalendar()[:2] == week:
                w += 1
    return d, w


# ---------------- Portfolio snapshot ----------------
def snapshot(c: EtoroClient) -> dict:
    p = c.portfolio()
    cash = float(p.get("credit", 0.0))
    pos = []
    for x in p.get("positions", []):
        u = x.get("unrealizedPnL", {})
        info = c.instrument_by_id(x["instrumentID"])
        value = float(u.get("exposureInAccountCurrency", x["amount"]))
        pos.append({
            "positionId": x["positionID"], "instrumentId": x["instrumentID"], "symbol": info["symbol"],
            "name": info["name"], "invested": float(x["amount"]), "value": value,
            "pnl": float(u.get("pnL", 0.0)), "units": float(x["units"]), "openRate": float(x["openRate"]),
            "price": float(u.get("closeRate", 0.0)), "stopLoss": float(x["stopLossRate"]),
            "leverage": x["leverage"], "isBuy": x["isBuy"], "opened": x["openDateTime"][:10],
        })
    equity = cash + sum(q["value"] for q in pos)
    for q in pos:
        q["weight"] = q["value"] / equity if equity else 0
        q["pnlPct"] = q["pnl"] / q["invested"] if q["invested"] else 0
        q["slDistance"] = (1 - q["stopLoss"] / q["price"]) if q["price"] else None
    return {"cash": cash, "equity": equity, "positions": pos,
            "pending_orders": len(p.get("ordersForOpen", [])) + len(p.get("orders", []))}


# ---------------- Rule checks ----------------
def check_buy(c: EtoroClient, snap: dict, inst: dict, amount: float, sl_pct: float, approved: bool) -> list[str]:
    R = rules()
    errs = []
    name = f"{inst.get('internalSymbolFull')} {inst.get('internalInstrumentDisplayName')}"
    if STOP_FILE.exists():
        errs.append("file STOP presente: trading sospeso")
    if inst.get("internalExchangeName") in R["blocked_exchanges"]:
        errs.append(f"{name}: borsa/tipo '{inst.get('internalExchangeName')}' non consentito (CFD)")
    if any(k.lower() in name.lower() for k in R["blocked_keywords"]):
        errs.append(f"{name}: strumento escluso (conflitto di interessi)")
    if not inst.get("isCurrentlyTradable") or not inst.get("isBuyEnabled", True):
        errs.append(f"{name}: non acquistabile ora")
    if amount < R["min_order_usd"]:
        errs.append(f"importo ${amount:.2f} sotto il minimo ${R['min_order_usd']}")
    if amount > snap["cash"]:
        errs.append(f"importo ${amount:.2f} superiore alla liquidità ${snap['cash']:.2f}")
    if not (R["stop_loss_min_pct"] <= sl_pct <= R["stop_loss_max_pct"]):
        errs.append(f"stop-loss {sl_pct:.0%} fuori dall'intervallo {R['stop_loss_min_pct']:.0%}-{R['stop_loss_max_pct']:.0%}")
    if snap["equity"] < R["min_equity_usd"]:
        errs.append(f"conto ${snap['equity']:.2f} sotto la soglia ${R['min_equity_usd']}: solo vendite")
    existing = sum(p["value"] for p in snap["positions"] if p["instrumentId"] == inst["internalInstrumentId"])
    w = (existing + amount) / snap["equity"] if snap["equity"] else 1
    if w > R["max_position_weight"] + 1e-9:
        errs.append(f"peso dopo l'acquisto {w:.0%} > massimo {R['max_position_weight']:.0%}")
    errs += check_counts(approved)
    return errs


def check_counts(approved: bool) -> list[str]:
    if approved:
        return []
    R = rules()
    d, w = orders_count()
    errs = []
    if d >= R["max_orders_per_day"]:
        errs.append(f"limite giornaliero raggiunto ({d}/{R['max_orders_per_day']})")
    if w >= R["max_orders_per_week"]:
        errs.append(f"limite settimanale raggiunto ({w}/{R['max_orders_per_week']})")
    return errs


# ---------------- Commands ----------------
def cmd_status(c, a):
    s = snapshot(c)
    d, w = orders_count()
    R = rules()
    if a.json:
        s["orders_today"], s["orders_week"] = d, w
        print(json.dumps(s, indent=1, ensure_ascii=False))
        return
    print(f"Conto: ${s['equity']:.2f}  | liquidità: ${s['cash']:.2f}  | ordini in sospeso: {s['pending_orders']}")
    print(f"Ordini usati: oggi {d}/{R['max_orders_per_day']}, settimana {w}/{R['max_orders_per_week']}"
          + ("  | ATTENZIONE: file STOP presente" if STOP_FILE.exists() else ""))
    print(f"{'simbolo':<10}{'posId':>12}{'investito':>10}{'valore':>9}{'pnl%':>8}{'peso':>7}{'prezzo':>10}{'SL':>10}{'SLdist':>8}  aperta")
    for p in sorted(s["positions"], key=lambda q: -q["value"]):
        sld = f"{p['slDistance']:.0%}" if p["slDistance"] is not None and p["stopLoss"] > 0.01 else "nessuno"
        print(f"{p['symbol']:<10}{p['positionId']:>12}{p['invested']:>10.2f}{p['value']:>9.2f}{p['pnlPct']:>8.1%}"
              f"{p['weight']:>7.1%}{p['price']:>10.2f}{p['stopLoss']:>10.2f}{sld:>8}  {p['opened']}")


def cmd_search(c, a):
    for it in c.search_symbol(a.symbol)[:a.limit]:
        print(f"{it.get('internalSymbolFull'):<12} {it.get('internalInstrumentDisplayName','')[:40]:<40} "
              f"id={it.get('internalInstrumentId'):<7} ${it.get('currentRate')}  {it.get('internalExchangeName')}  "
              f"tradable={it.get('isCurrentlyTradable')}  1w={it.get('weeklyPriceChange') or 0:.1f}%  "
              f"1m={it.get('monthlyPriceChange') or 0:.1f}%  1y={it.get('oneYearPriceChange') or 0:.1f}%")


def cmd_history(c, a):
    inst = c.instrument(a.symbol)
    cs = c.candles(inst["internalInstrumentId"], count=a.days)
    if not cs:
        print("nessun dato"); return
    closes = [x["close"] for x in cs]
    last = closes[-1]

    def chg(n):
        return f"{last / closes[-n - 1] - 1:+.1%}" if len(closes) > n else "n/d"
    peak = max(closes)
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))][-20:]
    vol = (sum(r * r for r in rets) / max(len(rets), 1)) ** 0.5 * (252 ** 0.5)
    ma50 = sum(closes[-50:]) / min(50, len(closes))
    ma200 = sum(closes[-200:]) / min(200, len(closes))
    print(f"{inst['internalSymbolFull']} ({inst['internalInstrumentDisplayName']}) ultimo={last:.2f} "
          f"[{cs[-1]['fromDate'][:10]}]")
    print(f"  variazione: 1g {chg(1)}  1s {chg(5)}  1m {chg(21)}  3m {chg(63)}  6m {chg(126)}  1a {chg(252)}")
    print(f"  dal massimo del periodo: {last / peak - 1:+.1%}   vol. annua (20g): {vol:.0%}")
    print(f"  MA50={ma50:.2f}  MA200={ma200:.2f}  prezzo {'sopra' if last > ma50 else 'sotto'} MA50, "
          f"{'sopra' if last > ma200 else 'sotto'} MA200")


def cmd_buy(c, a):
    inst = c.instrument(a.symbol)
    snap = snapshot(c)
    price = float(inst.get("currentRate") or 0)
    rate = c.rates([inst["internalInstrumentId"]]).get(inst["internalInstrumentId"])
    if rate:
        price = float(rate.get("ask") or price)
    if price <= 0:
        sys.exit(f"RIFIUTATO: prezzo non disponibile per {a.symbol}")
    errs = check_buy(c, snap, inst, a.amount, a.sl, a.approved_by_user)
    if errs:
        sys.exit("RIFIUTATO dalle regole:\n  - " + "\n  - ".join(errs))
    sl_rate = round(price * (1 - a.sl), 4 if price < 10 else 2)
    tp_rate = round(price * (1 + a.tp), 2) if a.tp else None
    row = {"timestamp": now().isoformat(timespec="seconds"), "action": "BUY", "symbol": inst["internalSymbolFull"],
           "instrument_id": inst["internalInstrumentId"], "amount_usd": a.amount, "stop_loss": sl_rate, "price": price,
           "reason": a.reason, "approved_by_user": "yes" if a.approved_by_user else ""}
    if a.dry_run:
        row["status"] = "DRY-RUN"; log_trade(row)
        print(f"[DRY-RUN] BUY {inst['internalSymbolFull']} ${a.amount:.2f} @~{price} SL {sl_rate} ({-a.sl:.0%})")
        return
    try:
        resp = c.open_buy(inst["internalInstrumentId"], a.amount, sl_rate, tp_rate)
        res = c.wait_order(order_id=resp.get("orderId"), reference_id=resp.get("referenceId"))
        st = res.get("status") or {}
        row.update(order_id=resp.get("orderId"), status=ORDER_STATUS.get(st.get("id"), str(st.get("id"))))
        if st.get("errorMessage"):
            row["status"] += f" ({st.get('errorMessage')})"
    except EtoroError as e:
        row.update(status="ERROR"); log_trade(row)
        sys.exit(f"ERRORE: {e}")
    log_trade(row)
    print(f"BUY {inst['internalSymbolFull']} ${a.amount:.2f} SL {sl_rate} -> {row['status']} (orderId {row['order_id']})")


def _find_position(snap, pid):
    for p in snap["positions"]:
        if str(p["positionId"]) == str(pid):
            return p
    sys.exit(f"RIFIUTATO: posizione {pid} non trovata")


def cmd_sell(c, a):
    snap = snapshot(c)
    p = _find_position(snap, a.position_id)
    errs = (["file STOP presente: trading sospeso"] if STOP_FILE.exists() else []) + check_counts(a.approved_by_user)
    if errs:
        sys.exit("RIFIUTATO dalle regole:\n  - " + "\n  - ".join(errs))
    row = {"timestamp": now().isoformat(timespec="seconds"), "action": "SELL", "symbol": p["symbol"],
           "instrument_id": p["instrumentId"], "position_id": p["positionId"], "amount_usd": round(p["value"], 2),
           "units": a.units or p["units"], "price": p["price"], "reason": a.reason, "approved_by_user": "yes" if a.approved_by_user else ""}
    if a.dry_run:
        row["status"] = "DRY-RUN"; log_trade(row)
        print(f"[DRY-RUN] SELL {p['symbol']} pos {p['positionId']} valore ${p['value']:.2f} pnl {p['pnlPct']:+.1%}")
        return
    try:
        resp = c.close_position(p["positionId"], p["instrumentId"], a.units)
        oid = (resp.get("orderForClose") or {}).get("orderID") or resp.get("orderId")
        row.update(order_id=oid, status="Submitted")
        if oid:
            st = c.close_order_status(int(oid))
            if st.get("statusID") is not None:
                row["status"] = ORDER_STATUS.get(st["statusID"], str(st["statusID"]))
            if (st.get("positions") or [{}])[0].get("rate"):
                row["price"] = st["positions"][0]["rate"]
            if st.get("proceeds") is not None:
                row["amount_usd"] = st["proceeds"]  # incasso netto effettivo
    except EtoroError as e:
        row.update(status="ERROR"); log_trade(row)
        sys.exit(f"ERRORE: {e}")
    log_trade(row)
    print(f"SELL {p['symbol']} pos {p['positionId']} (~${p['value']:.2f}) -> {row['status']}, incasso ${row['amount_usd']} (orderId {row['order_id']})")


def cmd_set_sl(c, a):
    R = rules()
    snap = snapshot(c)
    p = _find_position(snap, a.position_id)
    if STOP_FILE.exists():
        sys.exit("RIFIUTATO: file STOP presente")
    if not (R["stop_loss_min_pct"] <= a.pct <= R["stop_loss_max_pct"]):
        sys.exit(f"RIFIUTATO: stop-loss {a.pct:.0%} fuori intervallo")
    rate = round(p["price"] * (1 - a.pct), 4 if p["price"] < 10 else 2)
    row = {"timestamp": now().isoformat(timespec="seconds"), "action": "SET_SL", "symbol": p["symbol"],
           "instrument_id": p["instrumentId"], "position_id": p["positionId"], "stop_loss": rate, "reason": a.reason}
    if a.dry_run:
        row["status"] = "DRY-RUN"; log_trade(row)
        print(f"[DRY-RUN] SET-SL {p['symbol']} -> {rate} (-{a.pct:.0%} da {p['price']})"); return
    try:
        c.set_stop_loss(p["positionId"], rate)
        row["status"] = "Accepted"
    except EtoroError as e:
        row["status"] = "ERROR"; log_trade(row)
        sys.exit(f"ERRORE: {e}")
    log_trade(row)
    print(f"SET-SL {p['symbol']} pos {p['positionId']} -> {rate} (-{a.pct:.0%})")


def cmd_review(c, a):
    """Confronta ogni decisione passata con l'andamento successivo del prezzo."""
    if not TRADES_CSV.exists():
        print("nessuna operazione registrata"); return
    rows = [r for r in csv.DictReader(open(TRADES_CSV, encoding="utf-8"))
            if r["action"] in ("BUY", "SELL") and r.get("price") and r["status"] not in ("Rejected", "DRY-RUN", "ERROR")]
    if not rows:
        print("nessuna operazione con prezzo registrato"); return
    ids = sorted({int(r["instrument_id"]) for r in rows})
    rt = c.rates(ids)
    print(f"{'data':<11}{'azione':<7}{'simbolo':<9}{'prezzo':>11}{'oggi':>11}{'var':>8}{'giorni':>7}  esito")
    good = bad = 0
    for r in rows:
        now_px = rt.get(int(r["instrument_id"]), {}).get("bid")
        if not now_px:
            continue
        px = float(r["price"]); chg = now_px / px - 1
        days = (now() - dt.datetime.fromisoformat(r["timestamp"])).days
        # BUY: bene se sale; SELL: bene se dopo la vendita scende (perdita evitata)
        score = chg if r["action"] == "BUY" else -chg
        verdict = "neutro" if abs(score) < 0.02 else ("BUONA" if score > 0 else "SBAGLIATA")
        good += verdict == "BUONA"; bad += verdict == "SBAGLIATA"
        print(f"{r['timestamp'][:10]:<11}{r['action']:<7}{r['symbol']:<9}{px:>11.2f}{now_px:>11.2f}{chg:>+8.1%}{days:>7}  {verdict}")
    print(f"\nDecisioni buone: {good}  sbagliate: {bad}  (soglia ±2%; giudica solo dopo almeno 1-2 settimane)")


def cmd_note(c, a):
    fp = append_daily(f"_{now():%H:%M}_ — {a.text}")
    print(f"nota salvata in {fp}")


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="eToro trader CLI (regole di rischio integrate)")
    ap.add_argument("--dry-run", action="store_true", help="simula senza inviare ordini")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("search"); s.add_argument("symbol"); s.add_argument("--limit", type=int, default=10)
    s = sub.add_parser("history"); s.add_argument("symbol"); s.add_argument("--days", type=int, default=260)

    s = sub.add_parser("buy")
    s.add_argument("symbol"); s.add_argument("amount", type=float, help="importo in USD")
    s.add_argument("--sl", type=float, required=True, help="stop-loss come frazione sotto il prezzo, es. 0.12")
    s.add_argument("--tp", type=float, default=None, help="take-profit come frazione sopra il prezzo (opzionale)")
    s.add_argument("--reason", required=True)

    s = sub.add_parser("sell")
    s.add_argument("position_id"); s.add_argument("--units", type=float, default=None)
    s.add_argument("--reason", required=True)

    s = sub.add_parser("set-sl")
    s.add_argument("position_id"); s.add_argument("--pct", type=float, required=True)
    s.add_argument("--reason", required=True)

    s = sub.add_parser("note"); s.add_argument("text")
    sub.add_parser("review", help="valuta le decisioni passate")

    a = ap.parse_args()
    # approvazione esplicita dell'utente (solo da sessione interattiva): esclude l'ordine dai limiti giornalieri/settimanali
    a.approved_by_user = os.environ.get("TRADER_USER_APPROVED") == "1"
    if getattr(a, "dry_run", None) is None:
        a.dry_run = False
    c = EtoroClient()
    {"status": cmd_status, "search": cmd_search, "history": cmd_history, "buy": cmd_buy,
     "sell": cmd_sell, "set-sl": cmd_set_sl, "note": cmd_note, "review": cmd_review}[a.cmd](c, a)


if __name__ == "__main__":
    try:
        main()
    except EtoroError as e:
        sys.exit(f"ERRORE eToro: {e}")
