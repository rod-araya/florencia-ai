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

SYSTEM_PROMPT = r"""
Market structure analyzer for 5m candles.
Identify: pivots, trend (UP/DOWN/SIDEWAYS), ChoCH, post-ChoCH swing.
Return ONLY valid JSON matching schema. No extra text.
Be concise.
"""

# Strict template to force exact structure on retry
STRICT_TEMPLATE = r"""{
  "trend":"SIDEWAYS",
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
                "num_ctx": 2048,       # neural-chat:7b soporta más contexto
                "num_predict": 256,   # permite más output para JSON detallado
                "top_p": 0.9,
                "repeat_penalty": 1.05,
                "num_thread": 2       # baja CPU (opcional, quita si quieres más velocidad)
            },
            "stream": False,
            "format": "json"
        }
        r = requests.post(f"{LLM_URL}/api/generate", json=req, timeout=120)  # neural-chat:7b es más lento
        r.raise_for_status()
        return r.json().get("response", "{}")

    # ---------- Attempt 1: normal strict prompt ----------
    prompt1 = (
        SYSTEM_PROMPT
        + "\n\nReturn ONLY JSON, no text outside.\nIf uncertain, return choch.detected=false and trend=SIDEWAYS.\n"
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
        # Fallback SIDEWAYS si falla parsing
        logger.warning(f"JSON parse error: {str(e1)[:100]}")
        return StructureReport(
            trend="SIDEWAYS",
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
                "notes": f"parse_error: {str(e1)[:160]}"
            },
            confidence=0.0
        )
