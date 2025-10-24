# 📋 GUÍA DE INTEGRACIÓN - MOTOR DE EJECUCIÓN (execution.py)

**Fecha:** 24 de octubre, 2025  
**Archivo:** `/opt/projects/florencia-ai/app/execution.py`  
**Estado:** ✅ Implementado

---

## 🎯 ¿QUÉ ES execution.py?

Motor de ejecución que maneja **órdenes en tiempo real** con el exchange Binance:

- ✅ Órdenes LIMIT de entrada
- ✅ Órdenes MARKET de cierre con TP/SL
- ✅ Soporte LONG (spot/derivados) y SHORT (derivados)
- ✅ Seguimiento automático de PnL real
- ✅ Estados de posición: PENDING_ENTRY → OPEN → CLOSED_TP/CLOSED_SL

---

## 🔧 COMPONENTES PRINCIPALES

### **1. Clase `Position`**

Representa una posición abierta o cerrada:

```python
@dataclass
class Position:
    side: str                           # "LONG" o "SHORT"
    entry: float                        # Precio de entrada
    stop: float                         # Precio de stop loss
    tp: float                           # Precio de take profit
    size: float                         # Tamaño en unidades base (BTC, ETH, etc)
    opened_ts: str                      # Timestamp de apertura
    status: str                         # PENDING_ENTRY|OPEN|CLOSED_TP|CLOSED_SL
    entry_order_id: Optional[str]       # ID de orden en el exchange
    closed_ts: Optional[str]            # Timestamp de cierre
    close_price: Optional[float]        # Precio de cierre real
    pnl: float                          # PnL realizado
```

**Estados de transición:**
```
PENDING_ENTRY  →  OPEN  →  CLOSED_TP
                  ↓
              CLOSED_SL
```

---

### **2. Clase `ExchangeEngine`**

Motor principal de ejecución:

```python
@dataclass
class ExchangeEngine:
    exchange: any               # Cliente CCXT (binance o binanceusdm)
    symbol: str                 # Par a tradear: "BTC/USDT"
    is_derivatives: bool        # True=binanceusdm, False=binance spot
    max_open_positions: int     # Máximo de posiciones simultáneas
    min_confidence: float       # Confianza mínima para abrir (default 0.60)
    positions: List[Position]   # Lista de posiciones
```

**Métodos principales:**
- `can_open()` - Verifica si hay espacio para nueva posición
- `open(side, entry, stop, tp, size, ts, confidence)` - Abre nueva posición
- `poll(last_candle)` - Sincroniza con exchange, maneja TP/SL
- `total_realized_pnl()` - PnL realizado total
- `get_stats()` - Estadísticas de posiciones

---

## 📝 CÓMO INTEGRAR EN main.py

### **PASO 1: Importar el motor**

```python
from execution import ExchangeEngine, Position
import ccxt
```

---

### **PASO 2: Inicializar en main()**

```python
def main():
    logger.info("florencia-ai iniciado | {} {} | PAPER={}", SYMBOL, TIMEFRAME, PAPER)
    
    # ... código existente ...
    
    # NUEVO: Inicializar motor de ejecución
    is_derivatives = EXCHANGE == "binanceusdm"
    
    ex_client = getattr(ccxt, EXCHANGE)({
        "apiKey": os.getenv("BINANCE_API_KEY"),
        "secret": os.getenv("BINANCE_SECRET"),
        "enableRateLimit": True,
    })
    
    # Paper trading: usar testnet
    if PAPER:
        ex_client.set_sandbox_mode(True)
    
    engine = ExchangeEngine(
        exchange=ex_client,
        symbol=SYMBOL,
        is_derivatives=is_derivatives,
        max_open_positions=1,
        min_confidence=0.60,  # Solo abre si confianza >= 60%
    )
    
    last_signal_ts = None
    last_closed_ts = None
    trade_tracker = TradeTracker()
    iteration_count = 0
```

---

### **PASO 3: Usar engine.open() cuando detectes señal**

En la sección donde actualmente hace `telegram(message)`:

```python
if report.confidence >= engine.min_confidence:
    # Tenemos señal válida y confianza mínima
    
    # ABRIR POSICIÓN
    position = engine.open(
        side=direction,              # "BULLISH" → "LONG", "BEARISH" → "SHORT"
        entry=entry,
        stop=stop,
        tp=tp,
        size=0.001,                  # Tamaño (0.001 BTC = ~$30 a precio 30k)
        ts=last_candle_ts,
        confidence=report.confidence
    )
    
    if position:
        # Exitosa apertura
        trade_tracker.add_signal(direction, entry, stop, tp, report.confidence)
        logger.info("Trade abierto: {} | entry={:.2f} sl={:.2f} tp={:.2f}",
                   direction, entry, stop, tp)
        telegram(message)
    else:
        # Falló validación (confianza baja, max posiciones, etc)
        logger.warning("Trade rechazado: confianza insuficiente")
```

---

### **PASO 4: Llamar poll() cada vela cerrada**

En el loop principal, después de analizar LLM:

```python
# NUEVO: Sincronizar con exchange y cerrar por TP/SL
candle_dict = {
    "ts": last_candle_ts,
    "open": float(tail["open"].iloc[-1]),
    "high": float(tail["high"].iloc[-1]),
    "low": float(tail["low"].iloc[-1]),
    "close": float(tail["close"].iloc[-1]),
}
engine.poll(candle_dict)

# Log de estadísticas
stats = engine.get_stats()
logger.info("EX STATS | pending={} open={} closed_tp={} closed_sl={} pnl={:.2f}",
           stats["pending_entry"],
           stats["open"],
           stats["closed_tp"],
           stats["closed_sl"],
           stats["total_realized_pnl"])
```

---

## 🔄 FLUJO COMPLETO DE UNA OPERACIÓN

```
1. DETECT SIGNAL
   └─ LLM detecta ChoCH + post-swing
   └─ Confianza >= 60%

2. OPEN POSITION
   └─ engine.open(BULLISH, entry=100, stop=95, tp=110, size=0.001)
   └─ Crea orden LIMIT en exchange
   └─ Status: PENDING_ENTRY

3. NEXT CANDLE - poll()
   └─ Sincroniza con exchange
   └─ ¿Orden llenada? → Status: OPEN
   └─ ¿TP/SL tocado? → Cierra con MARKET
   └─ Calcula PnL real

4. CLOSE POSITION (TP hit)
   └─ Status: CLOSED_TP
   └─ PnL = (110 - 100) * 0.001 = 0.01 BTC ≈ $300

5. LOG STATS
   └─ Actualiza estadísticas
   └─ Suma a total_realized_pnl
```

---

## 📊 PRECISIÓN EN BINANCE

El motor maneja automáticamente:

```python
# PRECIO: redondea a precisión del exchange
entry_p = self._p(100.12345)  # → 100.12 (2 decimales típico)

# CANTIDAD: redondea a unidades mínimas
size_a = self._a(0.00123)      # → 0.001 (8 decimales típico)
```

**Esto previene errores de:**
- Cantidad muy pequeña
- Precio con demasiados decimales
- Órdenes rechazadas por el exchange

---

## 🚀 EJEMPLO COMPLETO DE INTEGRACIÓN

```python
# En main.py, después de imports

from execution import ExchangeEngine
import ccxt
import os

def main():
    # ... código existente de setup ...
    
    # NUEVO: Setup exchange engine
    exchange_type = os.getenv("EXCHANGE", "binance")
    is_derivatives = exchange_type == "binanceusdm"
    
    ccxt_client = getattr(ccxt, exchange_type)({
        "apiKey": os.getenv("BINANCE_API_KEY"),
        "secret": os.getenv("BINANCE_SECRET"),
        "enableRateLimit": True,
    })
    
    if PAPER:  # Paper trading en testnet
        ccxt_client.set_sandbox_mode(True)
    
    engine = ExchangeEngine(
        exchange=ccxt_client,
        symbol=SYMBOL,
        is_derivatives=is_derivatives,
        max_open_positions=1,
        min_confidence=0.60,
    )
    
    # Loop principal
    while True:
        try:
            # ... fetch data, analyze with LLM ...
            
            if report.choch.detected and report.validity_checks.broke_on_close:
                # NUEVA: Intentar abrir trade
                position = engine.open(
                    side="LONG" if report.choch.direction == "BULLISH" else "SHORT",
                    entry=entry,
                    stop=stop,
                    tp=tp,
                    size=0.001,
                    ts=last_candle_ts,
                    confidence=report.confidence
                )
            
            # NUEVA: Sincronizar posiciones abiertas
            candle = {
                "ts": last_candle_ts,
                "open": float(tail["open"].iloc[-1]),
                "high": float(tail["high"].iloc[-1]),
                "low": float(tail["low"].iloc[-1]),
                "close": float(tail["close"].iloc[-1]),
            }
            engine.poll(candle)
            
            # Log estadísticas
            stats = engine.get_stats()
            logger.info("Positions: pending={} open={} tp={} sl={} pnl={:.2f}",
                       stats["pending_entry"],
                       stats["open"],
                       stats["closed_tp"],
                       stats["closed_sl"],
                       stats["total_realized_pnl"])
            
        except Exception as e:
            logger.exception(f"Error: {e}")
        finally:
            time.sleep(LOOP_SECONDS)

if __name__ == "__main__":
    main()
```

---

## ⚙️ CONFIGURACIÓN EN .env

```bash
# Binance API (paper trading)
BINANCE_API_KEY=your_test_api_key
BINANCE_SECRET=your_test_secret

# Elige exchange
EXCHANGE=binance          # Spot, LONG solo
# EXCHANGE=binanceusdm    # USDT-M futures, LONG y SHORT

# Paper vs Live
PAPER=true               # Usa testnet
# PAPER=false            # Trading real (⚠️ CUIDADO)
```

---

## 🔒 SEGURIDAD

**IMPORTANTE - Paper Trading:**
```python
# Siempre usa testnet para paper trading
if PAPER:
    ccxt_client.set_sandbox_mode(True)
```

**NO hardcodear credenciales:**
```python
# ❌ MAL:
ccxt_client = ccxt.binance({
    "apiKey": "abc123...",  # NUNCA aquí
    "secret": "xyz789...",
})

# ✅ BIEN:
ccxt_client = ccxt.binance({
    "apiKey": os.getenv("BINANCE_API_KEY"),
    "secret": os.getenv("BINANCE_SECRET"),
})
```

---

## 📈 MONITOREO EN LOGS

```
# Orden abierta
EX ORDER PLACED | id=abc123 side=LONG entry=100.00 sl=95.00 tp=110.00

# Llenada
EX ENTRY FILLED | LONG id=abc123 price=100.02

# Cierre por TP
EX LONG CLOSED TP | close=110.05 pnl=0.01

# Estadísticas
EX STATS | pending=0 open=0 closed_tp=1 closed_sl=0 pnl=0.01
```

---

## ✅ CHECKLIST DE INTEGRACIÓN

- [ ] Crear cuenta de prueba en Binance Testnet
- [ ] Generar API keys (Testnet)
- [ ] Configurar variables de entorno (.env)
- [ ] Importar ExchangeEngine en main.py
- [ ] Inicializar engine en main()
- [ ] Integrar engine.open() cuando detecte señal
- [ ] Integrar engine.poll() en cada vela
- [ ] Probar con paper trading (1-2 horas)
- [ ] Verificar logs de EX (ORDER PLACED, FILLED, CLOSED)
- [ ] Comparar PnL en logs vs estadísticas del exchange
- [ ] Cuando esté validado, cambiar a trading real

---

**Próximo paso:** Integrar execution.py en main.py
