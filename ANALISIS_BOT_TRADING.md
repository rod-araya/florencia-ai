# 📊 ANÁLISIS EXHAUSTIVO DEL BOT DE TRADING - FLORENCIA-AI

**Fecha del análisis:** 24 de octubre, 2025  
**Versión del sistema:** v1.0  
**Proyecto:** florencia-ai (BTC/USDT 5m)

---

## 🎯 LÓGICA DE TRADING - RESUMEN EJECUTIVO

El bot implementa una estrategia de **trading algorítmico basada en análisis de estructura de mercado** usando un modelo de Language Model (Ollama) para detectar patrones técnicos específicos. La estrategia se fundamenta en tres pilares:

1. **Detección de pivotes fractales** - Identifica máximos y mínimos locales
2. **Análisis de cambio de carácter (ChoCH)** - Detecta quiebres de estructura
3. **Niveles de Fibonacci 0.618** - Calcula entrada y objetivos

---

## 🔄 FLUJO DE LÓGICA DE TRADING DETALLADO

### **PASO 1: Adquisición de datos (main.py:53-84)**

```
fetch_ohlcv(300)  →  Obtiene últimas 300 velas OHLCV
   ↓
work_df = df.iloc[:-1]  →  Descarta vela actual (no cerrada)
   ↓
tail = work_df.tail(120)  →  Usa últimas 120 velas para análisis
   ↓
pivots = fractal_pivot_candidates()  →  Identifica H/L locales
```

**Características:**
- Descarga 300 velas (10 horas en timeframe 5m)
- Trabaja solo con velas cerradas (excluye la actual)
- Limita contexto a 120 velas para reducir tokens del LLM
- Filtra pivotes solo dentro de la ventana de 120 velas

### **PASO 2: Gate - Una llamada por vela cerrada nueva (main.py:62-66)**

```
if curr_closed_ts == last_closed_ts:
    continue  →  Evita duplicar análisis
else:
    last_closed_ts = curr_closed_ts  →  Actualiza marca
    → CONTINUAR A ANÁLISIS LLM
```

**Propósito:** Reduce llamadas al LLM a máximo 1 por cada vela cerrada (cada 5 minutos).

### **PASO 3: Análisis LLM - Detección de estructura (structure_oracle.py:108-189)**

El sistema envía al modelo Ollama:
- 120 velas OHLCV (último 10 horas)
- Pivotes fractales detectados
- Prompt con instrucciones muy específicas

**El modelo identifica:**

1. **TREND (tendencia):** UP, DOWN, o SIDEWAYS
   - UP: HH/HL (máximos más altos, mínimos más altos)
   - DOWN: LH/LL (máximos más bajos, mínimos más bajos)
   - SIDEWAYS: sin claridad

2. **ChoCH (Cambio de Carácter):** Quiebre de estructura
   - **Bearish ChoCH:** En contexto UP, el CIERRE baja el último HL (nivel de soporte)
   - **Bullish ChoCH:** En contexto DOWN, el CIERRE sube el último LH (nivel de resistencia)
   - Requiere: cierre completo, NO solo wick

3. **LEG (Impulso):** La onda que genera el quiebre
   - High→Low (bearish) o Low→High (bullish)
   - Debe estar dentro del rango de datos

4. **POST-CHOCH SWING:** Confirmación del movimiento
   - **Bearish ChoCH:** Necesita LH (máximo más bajo) después del quiebre
   - **Bullish ChoCH:** Necesita HL (mínimo más alto) después del quiebre

**Validaciones:**
- `broke_on_close: true` - No puede ser solo wick
- `confidence: [0.0-1.0]` - Grado de certeza del modelo

### **PASO 4: Decisión de trade (main.py:88-125)**

```
IF ChoCH detectado AND broke_on_close=true AND leg existe:
    ├─ IF direction = BULLISH:
    │  ├─ entry = fib_0618_long(leg.low, leg.high)
    │  ├─ stop = leg.low
    │  └─ tp = leg.high
    │
    └─ IF direction = BEARISH:
       ├─ entry = fib_0618_short(leg.high, leg.low)
       ├─ stop = leg.high
       └─ tp = leg.low

AND post_choch_swing.exists = true:
    IF Signal not throttled:
        ├─ Register signal
        ├─ Send Telegram alert
        └─ Log details
```

### **PASO 5: Cálculos de Fibonacci 0.618**

```
LONG (BULLISH):
    entry = low + 0.618 × (high - low)
    stop = low
    tp = high
    RR = (high - entry) / (entry - low)

SHORT (BEARISH):
    entry = high - 0.618 × (high - low)
    stop = high
    tp = low
    RR = (high - entry) / (entry - low)
```

**Ejemplo:**
```
Leg: low=100, high=110
LONG entry = 100 + 0.618×10 = 106.18
stop = 100
tp = 110
Risk/Reward = (110-106.18)/(106.18-100) = 0.64 (pobre)
```

---

## ⚠️ PROBLEMAS IDENTIFICADOS - CRÍTICOS Y MAYORES

### **🔴 CRÍTICOS**

#### **1. NO HAY EJECUCIÓN REAL DE TRADES (Risk: MÁXIMO)**
**Ubicación:** Todo el sistema  
**Problema:**
- El bot DETECTA señales pero NO las ejecuta en el exchange
- Solo registra en TradeTracker (simulado)
- Las estadísticas de PnL son ficticias (TP=+100, SL=-50)
- No hay integración con API de Binance/CCXT para órdenes

**Impacto:**
- El bot es completamente ESPECULATIVO/BACKTESTING
- No puede generar PnL real
- Las señales nunca se ejecutan

**Código afectado:**
```python
# main.py:114 - Solo registra, NO ejecuta
signal = trade_tracker.add_signal(direction, entry, stop, tp, report.confidence)
telegram(message)  # Alerta sí, pero sin orden real
```

---

#### **2. INFORMACIÓN DE PRECIO ESTÁTICA (Risk: CRÍTICO)**
**Ubicación:** main.py:69-71  
**Problema:**
```python
current_price, price_change, last_candle_ts = trade_tracker.get_price_info(work_df)
# Luego:
logger.info(f"Precio (en curso): {current_price:.2f} | Δ vs cerrado: 0.00%")
# ↑ SIEMPRE muestra 0.00% aunque el precio haya cambiado
```

**Impacto:**
- No refleja el precio actual real intra-vela
- Imposible monitorear price slippage en tiempo real
- Las órdenes reales (si existieran) podrían llegar a precios muy diferentes

---

#### **3. VENTANA DE ANÁLISIS INSUFICIENTE (Risk: ALTO)**
**Ubicación:** main.py:74-75  
**Problema:**
```python
tail = work_df.tail(120)  # Solo 120 velas = 10 horas
```

**Por qué es un problema:**
- El prompt del LLM dice "Use only the last ~200 candles" (línea 33 de structure_oracle.py)
- Con 120 candles, falta contexto histórico
- Los pivotes pueden quedar fuera del rango
- Reduce precisión de detección de tendencia

**En 5m, 120 velas = 10 horas:**
- Bueno para volatilidad intraday
- Malo para tendencias de 1-2 días
- Los soportes/resistencias pueden estar fuera

---

#### **4. FALTA MANEJO DE MÚLTIPLES SEÑALES CONCURRENTES (Risk: ALTO)**
**Ubicación:** main.py:108-115  
**Problema:**
```python
if last_signal_ts == report.choch.break_close_ts:
    continue  # Throttle: solo previene DUPLICADOS de la misma vela
```

**Limitación:**
- Solo usa timestamp de vela para throttle
- Si hay 2 ChoCH diferentes = 2 órdenes (sin límite)
- Sin control de:
  - Posiciones máximas abiertas
  - Correlación entre trades
  - Riesgo acumulado

**Ejemplo problemático:**
```
Vela 1: ChoCH BULLISH detectado → Orden abierta
Vela 2: ChoCH BEARISH detectado → Segunda orden abierta
Vela 3: Ambas van en contra → Dos perdidas simultáneas
```

---

### **🟠 MAYORES**

#### **5. DEPENDENCIA CRÍTICA DE OLLAMA (Risk: ALTO)**
**Ubicación:** structure_oracle.py:116-164  
**Problemas:**

a) **Sin fallback real:**
```python
except (ValueError, ValidationError) as e2:
    return StructureReport(trend="SIDEWAYS", ...)  # Fallback genérico
```
- Si Ollama cae → todo es SIDEWAYS
- Sin buffer o caché de decisiones previas
- Sin histórico para validación

b) **Timeout muy largo (180s):**
```python
r = requests.post(f"{LLM_URL}/api/generate", json=req, timeout=180)
```
- En 5m timeframe, esperar 3 minutos es inaceptable
- Pierdes todo el movimiento relevante de la vela
- Mejor: máximo 30s o no esperes

c) **Modelo pequeño (3b):**
```python
LLM_MODEL = "llama3.2:3b-instruct-q4_0"
```
- Muy comprimido (cuantización q4)
- Puede fallar frecuentemente en lógica compleja
- Mejor: `mistral:7b` o modelo más grande

---

#### **6. PIVOT DETECTION INSUFICIENTE (Risk: ALTO)**
**Ubicación:** utils.py:15-23  
**Código:**
```python
def fractal_pivot_candidates(df: pd.DataFrame, K:int=2):
    for i in range(K, len(df)-K):
        # Fractal simple: K velas izquierda y derecha
```

**Limitaciones:**
1. **Solo K=2:** Requiere solo 2 velas a cada lado
   - Demasiado sensible, genera ruido
   - Muchos "falsos pivotes"
   
2. **Sin confirmación:**
   - No valida si el pivote es "real" en el contexto
   - No usa volumen
   - No valida con precio actual

3. **Sin jerarquía:**
   - Todos los pivotes tienen igual peso
   - Debería priorizar pivotes de orden superior
   - Debería ignorar pivotes muy cercanos

**Mejora sugerida:**
```
Usar K=3-5 (más restrictivo)
Validar con volumen
Mantener jerarquía de pivotes (recientes vs históricos)
```

---

#### **7. CONFIANZA (confidence) POCO CONFIABLE (Risk: MEDIO)**
**Ubicación:** structure_oracle.py (salida del LLM)  
**Problema:**
- El campo `confidence` lo devuelve el LLM sin validación
- No hay umbral mínimo de confianza para tradear
- Señal con `confidence=0.01` se ejecuta igual que `confidence=0.95`

**Código:**
```python
# main.py:114
signal = trade_tracker.add_signal(direction, entry, stop, tp, report.confidence)
# Sin validación de threshold
```

**Recomendación:**
```python
MIN_CONFIDENCE = 0.60
if report.confidence < MIN_CONFIDENCE:
    logger.info(f"Señal rechazada: confidence {report.confidence:.2f} < {MIN_CONFIDENCE}")
    continue
```

---

#### **8. ESTADÍSTICAS DE PNÁLOGO SIMULADAS (Risk: MEDIO)**
**Ubicación:** trade_tracker.py:84-92  
**Código:**
```python
def _calculate_realized_pnl(self) -> float:
    closed_tp = sum(1 for s in self.signals if s.status == "CLOSED_TP")
    closed_sl = sum(1 for s in self.signals if s.status == "CLOSED_SL")
    return (closed_tp * 100.0) - (closed_sl * 50.0)  # ← HARDCODEADO
```

**Problemas:**
- PnL fijo: TP siempre +100, SL siempre -50
- Nunca cambia de estado ("DETECTED" → nunca se ejecuta)
- Las estadísticas son COMPLETAMENTE FALSAS
- Los signals nunca se cierran automáticamente

---

#### **9. SIN GESTIÓN DE RIESGO REAL (Risk: CRÍTICO SI SE EJECUTA)**
**Ubicación:** Todo el sistema  
**Falta:**

a) **Sin cálculo de posición:**
- No valida tamaño de contrato
- No usa Kelly Criterion
- No considera saldo actual
- Risk/Reward es fijo

b) **Sin stop-loss dinámico:**
- Stop es siempre el leg.low/high
- Sin trailing stop
- Sin invalidación por tiempo

c) **Sin diversificación:**
- Puede tener posiciones correlacionadas
- Sin límite de símbolos

---

#### **10. GATE/THROTTLE BÁSICO (Risk: MEDIO)**
**Ubicación:** main.py:62-66  
**Problema:**
```python
if last_closed_ts is not None and curr_closed_ts == last_closed_ts:
    continue
last_closed_ts = curr_closed_ts
```

**Limitaciones:**
- Solo previene duplicados en la MISMA vela
- No previene "re-entry" en la misma dirección
- No trackea cuándo se ejecutó la orden (solo cuándo se detectó)

---

#### **11. FALTA INTEGRACIÓN REAL CON EXCHANGE (Risk: CRÍTICO)**
**Ubicación:** main.py (todo)  
**Falta:**

a) **Sin API order:**
```python
# NO EXISTE:
ex().create_limit_buy_order(SYMBOL, amount, price)
ex().create_stop_limit_order(...)
```

b) **Sin position tracking:**
```python
# NO EXISTE:
positions = ex().fetch_positions()
ex().close_position(position_id)
```

c) **Sin manejo de fills:**
```python
# NO EXISTE:
filled_price = order.fill_price
fill_fee = order.fee
```

---

#### **12. LOGGING DE PRECIO INCONSISTENTE (Risk: MEDIO)**
**Ubicación:** main.py:70-71  
**Problema:**
```python
logger.info(f"Precio (cerrado): {current_price:.2f} | Cambio: {price_change:.2f}%...")
logger.info(f"Precio (en curso): {current_price:.2f} | Δ vs cerrado: 0.00%")
```

**Incongruencias:**
- Ambas líneas usan `current_price` (mismo valor)
- La segunda SIEMPRE dice 0.00% (es calculada entre dos velas cerradas)
- No refleja precio intra-vela actual
- Confuso para monitoreo

---

### **🟡 MENORES**

#### **13. IMPORTACIONES NO USADAS**
**Ubicación:** structure_oracle.py:4  
```python
import re  # ← Importado pero NUNCA se usa
```

---

#### **14. VARIABLES DE ENTORNO HARDCODEADAS**
**Ubicación:** utils.py:4-5  
```python
BOT = os.getenv("TELEGRAM_BOT_TOKEN", "7494717589:AAF...")  # ← Token exposé
CHAT = os.getenv("TELEGRAM_CHAT_ID", "2128579285")       # ← ID exposé
```

**Problema:** Credenciales en el código (aunque sean fallback)

---

#### **15. MANEJO DE EXCEPCIONES GENÉRICO**
**Ubicación:** utils.py:12-13  
```python
except Exception:
    pass  # ← Silencia TODOS los errores
```

**Mejor:**
```python
except requests.Timeout:
    logger.warning("Telegram timeout")
except Exception as e:
    logger.warning(f"Telegram error: {e}")
```

---

#### **16. SIN VALIDACIÓN DE DATOS OHLCV**
**Ubicación:** main.py:53-54  
```python
df = fetch_ohlcv(300)
if len(df) < 60:
    continue
```

**Falta:**
- Validar que close >= open (para ciertos análisis)
- Validar gaps enormes (posible error de API)
- Validar timestamps duplicados

---

#### **17. REINTENTO DEL LLM ES COSTOSO (Risk: BAJO)**
**Ubicación:** structure_oracle.py:134-164  
**Problema:**
```python
# Intento 1: prompt normal
# Si falla → Intento 2: prompt ultra-strict
# 2 llamadas al LLM = 2x tiempo + tokens
```

**Con timeout de 180s y 2 intentos:**
- Peor caso: 360 segundos de espera
- En timeframe 5m: esperas TODO el período

---

---

## ✅ MEJORAS RECOMENDADAS - POR PRIORIDAD

### **CRÍTICAS (Implementar primero)**

| # | Mejora | Impacto | Dificultad |
|----|--------|--------|-----------|
| **1** | Implementar ejecución real de órdenes en exchange | MÁXIMO | Muy Alta |
| **2** | Integrar manejo de posiciones activas | MÁXIMO | Muy Alta |
| **3** | Implementar gestión de riesgo real | CRÍTICO | Alta |
| **4** | Añadir umbral de confianza mínima | ALTO | Muy Baja |
| **5** | Implementar caché/buffer de decisiones previas | ALTO | Media |

---

### **ALTAS (Implementar después)**

| # | Mejora | Impacto | Dificultad |
|----|--------|--------|-----------|
| **6** | Aumentar ventana de análisis a 200 candles | ALTO | Muy Baja |
| **7** | Mejorar detección de pivotes (K=3-5, con volumen) | ALTO | Media |
| **8** | Implementar precio real intra-vela | ALTO | Media |
| **9** | Control de posiciones máximas concurrentes | ALTO | Media |
| **10** | Reducir timeout LLM a 30-45 segundos | ALTO | Muy Baja |

---

### **MEDIAS (Optimización)**

| # | Mejora | Impacto | Dificultad |
|----|--------|--------|-----------|
| **11** | Usar modelo LLM más potente (7b-13b) | MEDIO | Baja |
| **12** | Validar datos OHLCV | MEDIO | Baja |
| **13** | Implementar histórico de decisiones | MEDIO | Media |
| **14** | Logging más detallado de invalidaciones | MEDIO | Baja |
| **15** | Revisar fórmula de Fibonacci (¿por qué 0.618?) | MEDIO | Baja |

---

---

## 🎓 ANÁLISIS TÉCNICO - VALIDACIONES

### **¿Qué está bien?**

✅ **Gate de una vela por ejecución** - Previene spam  
✅ **Estructuración de prompt para LLM** - Prompts claros y detallados  
✅ **Fallback a SIDEWAYS** - Mejor que crash  
✅ **Logging detallado** - Fácil debugging  
✅ **Uso de Fibonacci 0.618** - Nivel valido técnicamente  
✅ **Verificación de broke_on_close** - Evita false breakouts por wicks  

### **¿Qué está mal?**

❌ **Sin ejecución real** - Todo es simulación  
❌ **Sin gestión de riesgo** - Posiciones ilimitadas (si se ejecutara)  
❌ **Dependencia crítica de LLM** - Sin alternativas  
❌ **Pivotes demasiado sensibles (K=2)** - Mucho ruido  
❌ **Ventana pequeña (120 candles)** - Poco contexto  
❌ **Confianza sin umbral** - Ejecuta incluso con baja certeza  

---

---

## 🔬 RECOMENDACIÓN FINAL

### **Estado Actual: ALPHA / PROTOTIPO**

El bot es un **proof-of-concept funcional** que demuestra:
- ✅ Integración con LLM para análisis de estructura
- ✅ Sistema de logging y seguimiento
- ✅ Flujo lógico de detección ChoCH

**PERO NO ES LISTO PARA TRADING REAL porque:**

1. **No ejecuta órdenes** (crítico)
2. **Sin gestión de riesgo** (crítico)  
3. **Sin manejo de posiciones** (crítico)
4. **Modelo pequeño del LLM** (confiabilidad baja)
5. **Contexto insuficiente** (precisión baja)

### **Próximos Pasos Recomendados:**

```
Fase 1 (URGENTE - 1-2 semanas):
  ├─ Implementar órdenes reales PAPER trading en Binance
  ├─ Agregar umbral de confianza mínima (60%)
  └─ Implementar control de máximo 1-2 posiciones simultáneas

Fase 2 (1-2 semanas):
  ├─ Mejorar detección de pivotes
  ├─ Aumentar contexto a 200 candles
  └─ Implementar precio real intra-vela

Fase 3 (2-4 semanas):
  ├─ Backtesting exhaustivo
  ├─ Optimización de parámetros
  └─ Testing en paper trading real

Fase 4 (4+ semanas):
  ├─ Trading real con posición pequeña
  ├─ Monitoreo 24/7
  └─ Ajustes dinámicos
```

---

**Fin del análisis**

