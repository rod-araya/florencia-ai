import os, requests
import pandas as pd

BOT = os.getenv("TELEGRAM_BOT_TOKEN", "7494717589:AAFyvGDvoU1ae3KUljQp6UhB1L3d9LJ_SOc")
CHAT = os.getenv("TELEGRAM_CHAT_ID", "2128579285")

def telegram(text: str):
    if not BOT or not CHAT: return
    try:
        requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage",
                      json={"chat_id": CHAT, "text": text}, timeout=10)
    except Exception:
        pass

def fractal_pivot_candidates(df: pd.DataFrame, K:int=2):
    cands = []
    for i in range(K, len(df)-K):
        high = df["high"].iloc[i]; low = df["low"].iloc[i]
        if (df["high"].iloc[i-K:i] < high).all() and (df["high"].iloc[i+1:i+1+K] < high).all():
            cands.append({"type":"H","ts": df["ts"].iloc[i].isoformat(), "price": float(high)})
        if (df["low"].iloc[i-K:i] > low).all() and (df["low"].iloc[i+1:i+1+K] > low).all():
            cands.append({"type":"L","ts": df["ts"].iloc[i].isoformat(), "price": float(low)})
    return cands
