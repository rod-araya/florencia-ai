import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
from loguru import logger

@dataclass
class TradeSignal:
    """Representa una señal de trading detectada"""
    timestamp: datetime
    direction: str  # "BULLISH" o "BEARISH"
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float
    status: str = "DETECTED"  # DETECTED, FILLED, INVALIDATED, CLOSED_TP, CLOSED_SL

@dataclass
class TradeStats:
    """Estadísticas de sesión de trading"""
    signals_detected: int = 0
    signals_bullish: int = 0
    signals_bearish: int = 0
    signals_filled: int = 0
    signals_invalidated: int = 0
    positions_open: int = 0
    positions_closed_tp: int = 0
    positions_closed_sl: int = 0
    realized_pnl: float = 0.0
    pending_orders: int = 0

class TradeTracker:
    """Sistema de seguimiento de trades y estadísticas"""
    
    def __init__(self):
        self.session_start = datetime.now()
        self.signals: List[TradeSignal] = []
        self.last_stats_log = datetime.now()
        self.stats_interval = timedelta(minutes=5)  # Log cada 5 minutos
        
    def add_signal(self, direction: str, entry: float, stop: float, tp: float, confidence: float) -> TradeSignal:
        """Agrega una nueva señal de trading"""
        signal = TradeSignal(
            timestamp=datetime.now(),
            direction=direction,
            entry_price=entry,
            stop_loss=stop,
            take_profit=tp,
            confidence=confidence,
            status="DETECTED"
        )
        self.signals.append(signal)
        return signal
    
    def update_signal_status(self, signal: TradeSignal, new_status: str):
        """Actualiza el estado de una señal"""
        signal.status = new_status
    
    def get_session_stats(self) -> TradeStats:
        """Calcula las estadísticas de la sesión actual"""
        stats = TradeStats()
        
        for signal in self.signals:
            if signal.status == "DETECTED":
                stats.signals_detected += 1
                if signal.direction == "BULLISH":
                    stats.signals_bullish += 1
                else:
                    stats.signals_bearish += 1
            elif signal.status == "FILLED":
                stats.signals_filled += 1
            elif signal.status == "INVALIDATED":
                stats.signals_invalidated += 1
            elif signal.status == "CLOSED_TP":
                stats.positions_closed_tp += 1
            elif signal.status == "CLOSED_SL":
                stats.positions_closed_sl += 1
        
        # Calcular PnL (simulado - en implementación real vendría del exchange)
        stats.realized_pnl = self._calculate_realized_pnl()
        
        return stats
    
    def _calculate_realized_pnl(self) -> float:
        """Calcula el PnL realizado (simulado)"""
        # En una implementación real, esto vendría del exchange
        # Por ahora, simulamos basado en señales cerradas
        closed_tp = sum(1 for s in self.signals if s.status == "CLOSED_TP")
        closed_sl = sum(1 for s in self.signals if s.status == "CLOSED_SL")
        
        # Simulación simple: TP = +100, SL = -50
        return (closed_tp * 100.0) - (closed_sl * 50.0)
    
    def should_log_stats(self) -> bool:
        """Determina si es tiempo de hacer log de estadísticas"""
        return datetime.now() - self.last_stats_log >= self.stats_interval
    
    def log_session_stats(self, current_price: float, price_change: float = 0.0):
        """Hace log de las estadísticas de sesión"""
        stats = self.get_session_stats()
        
        logger.info("=== Estadísticas de sesión ===")
        logger.info(f"• Señales detectadas: (BUY: {stats.signals_bullish}, SELL: {stats.signals_bearish})")
        logger.info(f"• Señales llenadas: (BUY: {stats.signals_filled}, SELL: {stats.signals_filled})")
        logger.info(f"• Señales invalidadas: {stats.signals_invalidated}")
        logger.info(f"• Posiciones abiertas: {stats.positions_open}")
        logger.info(f"• Posiciones cerradas: TP {stats.positions_closed_tp}, SL {stats.positions_closed_sl}")
        logger.info(f"• PnL realizado: {stats.realized_pnl:.2f} USDT")
        logger.info(f"• Estado actual: {stats.pending_orders} pendientes, {stats.positions_open} abiertas")
        logger.info(f"• Precio actual: {current_price:.2f} | Cambio: {price_change:.2f}%")
        logger.info("Esperando 60 segundos...")
        
        self.last_stats_log = datetime.now()
    
    def get_price_info(self, df) -> tuple:
        """Extrae información de precio del DataFrame"""
        if df.empty:
            return 0.0, 0.0, "N/A"
        
        current_price = float(df["close"].iloc[-1])
        prev_price = float(df["close"].iloc[-2]) if len(df) > 1 else current_price
        change = ((current_price - prev_price) / prev_price * 100) if prev_price != 0 else 0.0
        
        last_candle_ts = df["ts"].iloc[-1].strftime("%Y-%m-%dT%H:%M:%S%z")
        
        return current_price, change, last_candle_ts
