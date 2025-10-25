import os
import time
import pandas as pd
import ccxt
from loguru import logger
from dotenv import load_dotenv
from structure_oracle import detect_structure_with_llm
from utils import fractal_pivot_candidates, telegram
from execution import ExchangeEngine

load_dotenv()
TZ = os.getenv("TZ", "America/Santiago")
EXCHANGE = os.getenv("EXCHANGE", "binance")  # "binance" o "binanceusdm"
SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
TIMEFRAME = os.getenv("TIMEFRAME", "5m")
LOOP_SECONDS = int(os.getenv("LOOP_SECONDS", "60"))
PAPER = os.getenv("PAPER", "true").lower() == "true"

MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.60"))
DEFAULT_SIZE = float(os.getenv("DEFAULT_SIZE", "0.001"))  # ej: 0.001 BTC
MAX_OPEN_POS = int(os.getenv("MAX_OPEN_POS", "1"))

os.makedirs("./logs", exist_ok=True)
logger.add("./logs/run.log", rotation="10 MB", retention=5)

def ex():
    klass = getattr(ccxt, EXCHANGE)
    client = klass({
        "enableRateLimit": True,
        "apiKey": os.getenv("BINANCE_API_KEY", ""),
        "secret": os.getenv("BINANCE_API_SECRET", ""),
    })
    # Testnet opcional
    if EXCHANGE.lower() in ("binance", "binanceusdm") and os.getenv("BINANCE_TESTNET", "false").lower() == "true":
        client.set_sandbox_mode(True)
    return client

def fetch_ohlcv(limit=300):
    client = ex()
    data = client.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=limit)
    df = pd.DataFrame(data, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_convert(TZ)
    return df

def main():
    logger.info("florencia-ai iniciado | {} {} | PAPER={}", SYMBOL, TIMEFRAME, PAPER)
    last_signal_ts = None
    last_closed_ts = None

    client = ex()
    is_deriv = EXCHANGE.lower() in ("binanceusdm", "binancecoinm")
    engine = ExchangeEngine(
        exchange=client,
        symbol=SYMBOL,
        is_derivatives=is_deriv,
        max_open_positions=MAX_OPEN_POS,
        min_confidence=MIN_CONFIDENCE
    )

    while True:
        try:
            df = fetch_ohlcv(300)
            if len(df) < 60:
                time.sleep(LOOP_SECONDS)
                continue

            work_df = df.iloc[:-1]
            if work_df.empty:
                time.sleep(LOOP_SECONDS)
                continue

            curr_closed_ts = work_df["ts"].iloc[-1]
            if last_closed_ts is not None and curr_closed_ts == last_closed_ts:
                time.sleep(LOOP_SECONDS)
                continue
            last_closed_ts = curr_closed_ts

            # ====== CONTEXTO COMPACTO: FORZAR DECISIONES RÁPIDAS ======
            tail = work_df.tail(30)  # 30 velas = 2.5 horas (suficiente para detectar estructura)
            first_ts = tail["ts"].iloc[0].isoformat()

            all_pivots = fractal_pivot_candidates(work_df, K=2)
            pivots = []
            for p in all_pivots:
                ts = p.get("ts")
                if ts and ts >= first_ts:
                    pivots.append({
                        "type": p.get("type"),
                        "ts": ts[:16],
                        "price": round(float(p.get("price", 0.0)), 2)
                    })
            pivots = pivots[-14:]  # máx 14 pivots (suficiente para detectar tendencia)

            def _r(x): return round(float(x), 2)
            candles = [
                [r.ts.isoformat(timespec="minutes"), _r(r.open), _r(r.high), _r(r.low), _r(r.close)]
                for _, r in tail.iterrows()
            ]
            # ================================

            report = detect_structure_with_llm(candles, pivots, K=2)

            # Actualiza posiciones con la ÚLTIMA vela cerrada (usa poll, no mark_to_market)
            last_row = tail.iloc[-1]
            engine.poll({
                "ts": last_row.ts.isoformat(),
                "open": float(last_row.open),
                "high": float(last_row.high),
                "low": float(last_row.low),
                "close": float(last_row.close)
            })

            if report.choch.detected and report.validity_checks.broke_on_close and report.choch.leg:
                if report.confidence < MIN_CONFIDENCE:
                    logger.info("Señal descartada por baja confianza: {:.2f} < {:.2f}",
                                report.confidence, MIN_CONFIDENCE)
                else:
                    leg = report.choch.leg
                    direction = report.choch.direction

                    if direction == "BULLISH":
                        entry = leg.low_price + 0.618 * (leg.high_price - leg.low_price)
                        stop = leg.low_price
                        tp = leg.high_price
                        swing_ok = (report.post_choch_swing.exists and report.post_choch_swing.type == "HL")
                        side = "LONG"
                    elif direction == "BEARISH":
                        entry = leg.high_price - 0.618 * (leg.high_price - leg.low_price)
                        stop = leg.high_price
                        tp = leg.low_price
                        swing_ok = (report.post_choch_swing.exists and report.post_choch_swing.type == "LH")
                        side = "SHORT"
                    else:
                        swing_ok = False

                    if not swing_ok:
                        logger.info("ChoCH {} detectado, post-ChoCH swing NO confirmado.", direction)
                    else:
                        if last_signal_ts == report.choch.break_close_ts:
                            logger.info("Throttle: ya actuamos para esta señal ({})", last_signal_ts)
                        else:
                            if engine.can_open():
                                last_signal_ts = report.choch.break_close_ts
                                pos = engine.open(side, entry, stop, tp, DEFAULT_SIZE, last_signal_ts)
                                msg = (
                                    f"🚀 florencia-ai {side} | {SYMBOL} {TIMEFRAME}\n"
                                    f"ENTRY:{entry:.2f}  SL:{stop:.2f}  TP:{tp:.2f}\n"
                                    f"size:{DEFAULT_SIZE}  conf:{report.confidence:.2f}"
                                )
                                telegram(msg)
                            else:
                                logger.info("Cap de posiciones alcanzado ({}). No se abre nueva.",
                                            MAX_OPEN_POS)
            else:
                logger.info("Sin ChoCH válido | trend={} | conf={:.2f}",
                            report.trend, report.confidence)

            logger.info("PnL realizado (exchange-managed aprox): {:.2f}", engine.total_realized_pnl())

        except Exception as e:
            logger.exception(f"Loop error: {e}")
        finally:
            time.sleep(LOOP_SECONDS)

if __name__ == "__main__":
    main()
