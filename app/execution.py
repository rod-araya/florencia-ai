# app/execution.py
# Exchange execution engine for Binance (spot or USDT-M futures via CCXT).
# - Places a LIMIT entry order at the specified price.
# - When filled, manages TP/SL by polling candles and sending a single
#   MARKET reduce order to close when TP or SL is touched.
#   (This avoids exchange-specific OCO/stop types and works reliably.)
#
# Notes:
# - SHORT requires derivatives (e.g., EXCHANGE=binanceusdm). On spot (EXCHANGE=binance)
#   SHORT is not supported unless you use margin; here we raise a clear error.
# - Size is in base asset units (e.g., BTC). Precision is adjusted using market metadata.
# - You should call engine.poll(candle_dict) once per CLOSED 5m candle to:
#     * transition entry orders to OPEN when filled,
#     * close OPEN positions by TP/SL with a MARKET reduce order.
#
# Env best practices (outside this file):
#   - For Binance Testnet (spot): client.set_sandbox_mode(True)
#   - For Binance USDT-M futures testnet: use ccxt.binanceusdm() and set_sandbox_mode(True)
#   - Provide API keys via env to the ccxt client in your factory.

from dataclasses import dataclass, field
from typing import List, Optional
from loguru import logger
import math


@dataclass
class Position:
    """Representa una posición abierta o cerrada"""
    side: str                 # "LONG" o "SHORT"
    entry: float
    stop: float
    tp: float
    size: float               # unidades base (e.g., BTC)
    opened_ts: str
    status: str = "PENDING_ENTRY"  # PENDING_ENTRY -> OPEN -> CLOSED_TP|CLOSED_SL
    entry_order_id: Optional[str] = None
    tp_hit: bool = False
    sl_hit: bool = False
    closed_ts: Optional[str] = None
    close_price: Optional[float] = None
    pnl: float = 0.0


@dataclass
class ExchangeEngine:
    """Motor de ejecución para Binance (spot o USDT-M futures)"""
    exchange: any            # cliente ccxt (binance o binanceusdm)
    symbol: str              # e.g., "BTC/USDT"
    is_derivatives: bool     # True para binanceusdm; False para spot binance
    max_open_positions: int = 1
    min_confidence: float = 0.60
    positions: List[Position] = field(default_factory=list)

    # ---------- Helpers ----------
    def _market_info(self):
        """Obtiene información de precisión del mercado"""
        m = self.exchange.market(self.symbol)
        return {
            "price_prec": m.get("precision", {}).get("price", None),
            "amount_prec": m.get("precision", {}).get("amount", None),
            "contract": m.get("contract", False),
        }

    def _p(self, price: float) -> float:
        """Redondea precio a la precisión del exchange"""
        try:
            return float(self.exchange.price_to_precision(self.symbol, price))
        except Exception:
            info = self._market_info()
            prec = info["price_prec"] or 2
            q = 10 ** prec
            return math.floor(price * q) / q

    def _a(self, amount: float) -> float:
        """Redondea cantidad a la precisión del exchange"""
        try:
            return float(self.exchange.amount_to_precision(self.symbol, amount))
        except Exception:
            info = self._market_info()
            prec = info["amount_prec"] or 6
            q = 10 ** prec
            return math.floor(amount * q) / q

    def _opposite(self, side: str) -> str:
        """Retorna el lado opuesto (sell para LONG, buy para SHORT)"""
        return "sell" if side.upper() == "LONG" else "buy"

    def _entry_side(self, side: str) -> str:
        """Traduce a lado CCXT (buy/sell)"""
        if side.upper() == "LONG":
            return "buy"
        # SHORT solo permitido en derivados
        if not self.is_derivatives:
            raise RuntimeError("SHORT no soportado en spot. Usa binanceusdm (derivados).")
        return "sell"

    def _reduce_params(self):
        """Parámetros para reducir posición (derivados)"""
        return {"reduceOnly": True} if self.is_derivatives else {}

    # ---------- Public API ----------
    def can_open(self) -> bool:
        """Verifica si hay espacio para nueva posición"""
        return sum(1 for p in self.positions if p.status in ("PENDING_ENTRY", "OPEN")) < self.max_open_positions

    def open(self, side: str, entry: float, stop: float, tp: float, size: float, ts: str, confidence: float = 1.0) -> Optional[Position]:
        """
        Abre una nueva posición con orden LIMIT en entry.
        Retorna Position con status PENDING_ENTRY, o None si falla validación.
        """
        # Validar confianza
        if confidence < self.min_confidence:
            logger.warning("EX REJECTED | confidence={:.2f} < min={:.2f}", confidence, self.min_confidence)
            return None

        # Validar side
        side_u = side.upper()
        if side_u not in ("LONG", "SHORT"):
            raise ValueError("side debe ser 'LONG' o 'SHORT'")

        # Validar max posiciones
        if not self.can_open():
            logger.warning("EX REJECTED | max {} posiciones abiertas", self.max_open_positions)
            return None

        # Preparar órdenes
        entry_p = self._p(entry)
        size_a = self._a(size)
        order_side = self._entry_side(side_u)

        try:
            logger.info("EX OPEN {} | entry={} sl={} tp={} size={} conf={:.2f}",
                       side_u, entry_p, self._p(stop), self._p(tp), size_a, confidence)

            order = self.exchange.create_order(
                symbol=self.symbol,
                type="limit",
                side=order_side,
                amount=size_a,
                price=entry_p,
                params={"timeInForce": "GTC"},
            )

            pos = Position(
                side=side_u,
                entry=entry_p,
                stop=self._p(stop),
                tp=self._p(tp),
                size=size_a,
                opened_ts=ts,
                status="PENDING_ENTRY",
                entry_order_id=order.get("id"),
            )
            self.positions.append(pos)
            logger.info("EX ORDER PLACED | id={} side={} entry={:.2f} sl={:.2f} tp={:.2f}",
                       pos.entry_order_id, side_u, pos.entry, pos.stop, pos.tp)
            return pos

        except Exception as e:
            logger.error("EX OPEN ERROR: {}", str(e)[:200])
            return None

    def poll(self, last_candle: dict):
        """
        Sincroniza posiciones con el exchange y cierra por TP/SL.
        last_candle: {'ts', 'open', 'high', 'low', 'close'}
        Llamar una vez por vela cerrada.
        """
        ts = last_candle["ts"]
        high = float(last_candle["high"])
        low  = float(last_candle["low"])

        # 1) Transicionar PENDING_ENTRY -> OPEN cuando se llena
        for p in self.positions:
            if p.status != "PENDING_ENTRY":
                continue
            if not p.entry_order_id:
                continue
            try:
                od = self.exchange.fetch_order(p.entry_order_id, self.symbol)
                st = (od.get("status") or "").lower()
                if st in ("closed", "filled"):
                    p.status = "OPEN"
                    filled_price = od.get("average") or od.get("price") or p.entry
                    logger.info("EX ENTRY FILLED | {} id={} price={:.2f}",
                               p.side, p.entry_order_id, float(filled_price))
                elif st in ("canceled", "rejected"):
                    p.status = "CLOSED_SL"
                    p.closed_ts = ts
                    p.close_price = None
                    p.pnl = 0.0
                    logger.warning("EX ENTRY CANCELED | id={} status={}", p.entry_order_id, st)
            except Exception as e:
                logger.warning("EX fetch_order error id={}: {}", p.entry_order_id, str(e)[:160])

        # 2) Para posiciones OPEN, cierra por TP/SL con MARKET reduce
        for p in self.positions:
            if p.status != "OPEN":
                continue

            # Detectar hits
            if p.side == "LONG":
                hit_tp = high >= p.tp
                hit_sl = low  <= p.stop
            else:  # SHORT
                hit_tp = low  <= p.tp
                hit_sl = high >= p.stop

            # SL tiene prioridad si ambos se tocan en la misma vela
            reason = None
            close_px = None
            if hit_sl:
                reason = "SL"
                close_px = p.stop
            elif hit_tp:
                reason = "TP"
                close_px = p.tp

            if reason:
                try:
                    opp = self._opposite(p.side)
                    params = self._reduce_params()
                    qty = self._a(p.size)

                    logger.info("EX CLOSING {} | reason={} price={:.2f}",
                               p.side, reason, close_px)

                    # Cierre MARKET
                    od = self.exchange.create_order(
                        symbol=self.symbol,
                        type="market",
                        side=opp,
                        amount=qty,
                        params=params,
                    )

                    # Usar precio de llenado si el exchange lo retorna
                    filled = None
                    if od and isinstance(od, dict):
                        filled = od.get("average") or od.get("price")
                    p.close_price = float(filled) if filled else float(close_px)
                    p.closed_ts = ts
                    p.status = f"CLOSED_{reason}"

                    # PnL en moneda quote (aprox): (close - entry) * size (sign por side)
                    sign = 1 if p.side == "LONG" else -1
                    p.pnl = (p.close_price - p.entry) * sign * p.size

                    logger.info("EX {} CLOSED {} | close={:.2f} pnl={:.2f}",
                               p.side, reason, p.close_price, p.pnl)

                except Exception as e:
                    logger.error("EX close market error ({}): {}", reason, str(e)[:200])

    def total_realized_pnl(self) -> float:
        """Retorna PnL realizado total de posiciones cerradas"""
        return sum(p.pnl for p in self.positions if p.status in ("CLOSED_TP", "CLOSED_SL"))

    def get_stats(self) -> dict:
        """Retorna estadísticas de posiciones"""
        pending = sum(1 for p in self.positions if p.status == "PENDING_ENTRY")
        open_pos = sum(1 for p in self.positions if p.status == "OPEN")
        closed_tp = sum(1 for p in self.positions if p.status == "CLOSED_TP")
        closed_sl = sum(1 for p in self.positions if p.status == "CLOSED_SL")
        total_pnl = self.total_realized_pnl()

        return {
            "pending_entry": pending,
            "open": open_pos,
            "closed_tp": closed_tp,
            "closed_sl": closed_sl,
            "total_realized_pnl": total_pnl,
        }
