"""Client minimale per la Public API di eToro (conto reale).

Documentazione: https://api-portal.etoro.com
Le chiavi vengono lette da .env (ETORO_API_KEY, ETORO_USER_KEY) e non vengono mai stampate.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import requests

BASE_URL = "https://public-api.etoro.com"
ROOT = Path(__file__).resolve().parent.parent
INSTRUMENT_CACHE = ROOT / "data" / "instruments.json"

# status.id degli ordini (GET /api/v2/trading/info/orders:lookup)
ORDER_STATUS = {
    1: "Received", 2: "Placed", 3: "Filled", 4: "Rejected", 5: "PartiallyFilled",
    6: "PendingCancel", 7: "Canceled", 8: "Expired", 9: "CanceledPartiallyFilled",
    10: "RejectedPartiallyFilled", 11: "WaitingForMarket", 12: "PendingTriggeredRate",
}
FINAL_OK = {3, 5}
FINAL_KO = {4, 7, 8, 9, 10}


class EtoroError(RuntimeError):
    pass


def _load_env(path: Path = ROOT / ".env") -> dict:
    env = {}
    if not path.exists():
        raise EtoroError(f"File {path} non trovato")
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("ETORO_API_KEY", "ETORO_USER_KEY"):
        if not env.get(k):
            raise EtoroError(f"{k} mancante in .env")
    return env


class EtoroClient:
    def __init__(self):
        env = _load_env()
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "etoro-companion/0.2",
            "Accept": "application/json",
            "x-api-key": env["ETORO_API_KEY"],
            "x-user-key": env["ETORO_USER_KEY"],
        })
        self._cache = None

    # ---------------- HTTP ----------------
    def _req(self, method: str, path: str, *, params=None, body=None, request_id: str | None = None):
        headers = {"x-request-id": request_id or str(uuid.uuid4())}
        if body is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(4):
            r = self.s.request(method, BASE_URL + path, params=params,
                               data=json.dumps(body) if body is not None else None,
                               headers=headers, timeout=30)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 5)))
                continue
            if r.status_code >= 400:
                raise EtoroError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:500]}")
            return r.json() if r.content else {}
        raise EtoroError(f"{method} {path} -> troppe richieste (429)")

    # ---------------- Market data ----------------
    def search_symbol(self, symbol: str) -> list[dict]:
        d = self._req("GET", "/api/v1/market-data/search", params={"internalSymbolFull": symbol})
        return d.get("items", [])

    def instrument(self, symbol: str) -> dict:
        """Ritorna i dati dello strumento con simbolo esatto (case-insensitive)."""
        items = [i for i in self.search_symbol(symbol)
                 if (i.get("internalSymbolFull") or "").upper() == symbol.upper()]
        if not items:
            raise EtoroError(f"Simbolo {symbol} non trovato su eToro")
        it = items[0]
        self._remember(it)
        return it

    def instrument_by_id(self, instrument_id: int) -> dict:
        cache = self._load_cache()
        if str(instrument_id) in cache:
            return cache[str(instrument_id)]
        d = self._req("GET", "/api/v1/market-data/search", params={"internalInstrumentId": instrument_id})
        for it in d.get("items", []):
            if it.get("internalInstrumentId") == instrument_id:
                self._remember(it)
                return self._load_cache()[str(instrument_id)]
        return {"symbol": f"ID{instrument_id}", "name": "?", "exchange": "?", "assetClass": "?"}

    def rates(self, instrument_ids: list[int]) -> dict[int, dict]:
        if not instrument_ids:
            return {}
        d = self._req("GET", "/api/v1/market-data/instruments/rates",
                      params={"instrumentIds": ",".join(str(i) for i in instrument_ids)})
        return {r["instrumentID"]: r for r in d.get("rates", [])}

    def candles(self, instrument_id: int, count: int = 260, interval: str = "OneDay") -> list[dict]:
        d = self._req("GET", f"/api/v1/market-data/instruments/{instrument_id}/history/candles/asc/{interval}/{count}")
        out = []
        for block in d.get("candles", []):
            out.extend(block.get("candles", []))
        return out

    # ---------------- Portfolio ----------------
    def portfolio(self) -> dict:
        return self._req("GET", "/api/v1/trading/info/real/pnl")["clientPortfolio"]

    # ---------------- Trading ----------------
    def open_buy(self, instrument_id: int, amount_usd: float, stop_loss_rate: float,
                 take_profit_rate: float | None = None) -> dict:
        ref = str(uuid.uuid4())
        body = {
            "action": "open",
            "transaction": "buy",
            "instrumentId": instrument_id,
            "orderType": "mkt",
            "leverage": 1,
            "settlementType": "real",
            "amount": round(amount_usd, 2),
            "orderCurrency": "usd",
            "stopLossRate": stop_loss_rate,
            "stopLossType": "fixed",
        }
        if take_profit_rate:
            body["takeProfitRate"] = take_profit_rate
        resp = self._req("POST", "/api/v2/trading/execution/orders", body=body, request_id=ref)
        resp["referenceId"] = resp.get("referenceId") or ref
        return resp

    def close_position(self, position_id: int, instrument_id: int, units: float | None = None) -> dict:
        body = {"InstrumentId": instrument_id, "UnitsToDeduct": units}
        return self._req("POST", f"/api/v1/trading/execution/market-close-orders/positions/{position_id}", body=body)

    def close_order_status(self, order_id: int, timeout_s: int = 20) -> dict:
        """Stato di un ordine di chiusura (statusID 3 = eseguito; 'proceeds' = incasso netto)."""
        deadline = time.time() + timeout_s
        last = {}
        while time.time() < deadline:
            try:
                last = self._req("GET", f"/api/v1/trading/info/real/close-orders/{order_id}")
                if last.get("statusID") in FINAL_OK | FINAL_KO or last.get("statusID") == 11:
                    return last
            except EtoroError:
                pass
            time.sleep(2)
        return last

    def set_stop_loss(self, position_id: int, stop_loss_rate: float) -> dict:
        return self._req("PATCH", f"/api/v2/trading/positions/{position_id}",
                         body={"stopLossRate": stop_loss_rate, "stopLossType": "fixed"})

    def order_lookup(self, *, order_id: int | None = None, reference_id: str | None = None) -> dict:
        params = {"orderId": order_id} if order_id else {"referenceId": reference_id}
        return self._req("GET", "/api/v2/trading/info/orders:lookup", params=params)

    def wait_order(self, *, order_id=None, reference_id=None, timeout_s: int = 30) -> dict:
        """Attende che l'ordine arrivi in uno stato finale (o in attesa del mercato)."""
        deadline = time.time() + timeout_s
        last = {}
        while time.time() < deadline:
            try:
                last = self.order_lookup(order_id=order_id, reference_id=reference_id)
            except EtoroError:
                time.sleep(2)
                continue
            sid = (last.get("status") or {}).get("id")
            if sid in FINAL_OK or sid in FINAL_KO or sid == 11:
                return last
            time.sleep(2)
        return last

    # ---------------- Cache strumenti ----------------
    def _load_cache(self) -> dict:
        if self._cache is None:
            self._cache = json.loads(INSTRUMENT_CACHE.read_text("utf-8")) if INSTRUMENT_CACHE.exists() else {}
        return self._cache

    def _remember(self, it: dict) -> None:
        cache = self._load_cache()
        cache[str(it["internalInstrumentId"])] = {
            "symbol": it.get("internalSymbolFull"),
            "name": it.get("internalInstrumentDisplayName"),
            "exchange": it.get("internalExchangeName"),
            "assetClass": it.get("internalAssetClassName"),
        }
        INSTRUMENT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        INSTRUMENT_CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False), "utf-8")
