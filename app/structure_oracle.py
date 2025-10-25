import os
import json
import requests
import re
from typing import List, Dict
from loguru import logger
from structure_schema import StructureReport
from pydantic import ValidationError

LLM_URL = os.getenv("LLM_URL", "http://ollama:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.2:3b-instruct-q4_0")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))

SYSTEM_PROMPT = r"""Analyze 5m BTC. Return ONLY valid JSON. MANDATORY: trend must be UP or DOWN (NO SIDEWAYS ALLOWED).

TREND (FORCED DECISION):
- Compare last 2-3 pivots: if most recent high > previous high → UP
- If most recent low < previous low → DOWN
- NEVER return SIDEWAYS: always choose UP or DOWN based on dominant direction

CHOCH (Change of Character):
- BULLISH: close ABOVE last LH (breaks downtrend) → need HL after
- BEARISH: close BELOW last HL (breaks uptrend) → need LH after
- Requires: broken_level_price, break_close_ts, leg{high_ts,high_price,low_ts,low_price}

Confidence 0.0-1.0: high=clear structure, low=choppy but STILL pick UP/DOWN."""

# Strict template to force exact structure on retry
STRICT_TEMPLATE = r"""{
  "trend":"UP",
  "last_swings":[],
  "choch":{"detected":false,"direction":null,"broken_level_type":null,"broken_level_price":null,"break_close_ts":null,"leg":null},
  "post_choch_swing":{"exists":false,"type":null,"ts":null,"price":null},
  "validity_checks":{"broke_on_close":false,"notes":""},
  "confidence":0.0
}"""

def _extract_json(text: str) -> str:
    """
    Try to extract the first well-formed JSON object from model output.
    Handles stray prose or markdown fences.
    """
    if not text:
        return "{}"
    # remove markdown fences if present
    cleaned = text.replace("```json", "").replace("```", "").strip()
    # fast path: first { ... } to last }
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start:end+1]
    return "{}"

def detect_structure_with_llm(candles: List[List], pivot_candidates: List[Dict], K: int = 2) -> StructureReport:
    user_payload = {
        "tf": "5m",
        "params": {"K": K},
        "candles": candles,              # [["ISO", o,h,l,c], ...]
        "pivot_candidates": pivot_candidates
    }

    def _call(prompt_text: str) -> str:
        req = {
            "model": LLM_MODEL,
            "prompt": prompt_text,
            "options": {
                "temperature": LLM_TEMPERATURE,
                "num_ctx": 3072,       # 40 velas + 18 pivots + prompt = ~2500 tokens
                "num_predict": 300,    # JSON completo con leg + swings
                "top_p": 0.9,
                "repeat_penalty": 1.05,
                "num_thread": 4        # mejor rendimiento para llama3.2
            },
            "stream": False,
            "format": "json"
        }
        r = requests.post(f"{LLM_URL}/api/generate", json=req, timeout=90)  # llama3.2 es rápido
        r.raise_for_status()
        return r.json().get("response", "{}")

    # ---------- Attempt 1: normal strict prompt ----------
    prompt1 = (
        SYSTEM_PROMPT
        + "\n\nReturn ONLY JSON. MUST choose UP or DOWN (never SIDEWAYS).\n"
        + STRICT_TEMPLATE
        + "\n\nData:\n"
        + json.dumps(user_payload)
    )
    raw1 = _call(prompt1)
    txt1 = _extract_json(raw1)
    try:
        data = json.loads(txt1)
        return StructureReport.model_validate(data)
    except (ValueError, ValidationError) as e1:
        # Fallback: calcular tendencia comparando últimos pivots
        logger.warning(f"JSON parse error: {str(e1)[:100]} - usando fallback Python")
        
        # Determinar tendencia comparando pivots
        trend = "UP"  # default
        if len(pivot_candidates) >= 2:
            highs = [p for p in pivot_candidates if p.get("type") == "H"]
            lows = [p for p in pivot_candidates if p.get("type") == "L"]
            
            if len(highs) >= 2 and len(lows) >= 2:
                # Si últimos lows están bajando → DOWN
                if lows[-1]["price"] < lows[-2]["price"]:
                    trend = "DOWN"
                # Si últimos highs están subiendo → UP
                elif highs[-1]["price"] > highs[-2]["price"]:
                    trend = "UP"
                # Si mixto, comparar último candle con hace 10 velas
                elif len(candles) >= 10:
                    trend = "UP" if candles[-1][4] > candles[-10][4] else "DOWN"
        
        return StructureReport(
            trend=trend,
            last_swings=[],
            choch={
                "detected": False,
                "direction": None,
                "broken_level_type": None,
                "broken_level_price": None,
                "break_close_ts": None,
                "leg": None
            },
            post_choch_swing={
                "exists": False,
                "type": None,
                "ts": None,
                "price": None
            },
            validity_checks={
                "broke_on_close": False,
                "notes": f"python_fallback: {str(e1)[:100]}"
            },
            confidence=0.2
        )
