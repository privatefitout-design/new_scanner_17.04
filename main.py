import asyncio
import os
import httpx
import logging
from datetime import datetime, timedelta
from collections import deque
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MIN_OI_THRESHOLD = 8_000_000
MIN_BASE_DAYS = 45          # ← Главный новый фильтр
SCAN_INTERVAL_MINUTES = 25
ALERT_COOLDOWN_HOURS = 3

history = {}
last_alert = {}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger(__name__)


async def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
            )
    except:
        pass


def calculate_score(data_history):
    if len(data_history) < 15:
        return 0, 0

    # Расчёт длины базы в днях
    first_date = data_history[0]['timestamp']
    last_date = data_history[-1]['timestamp']
    base_days = (last_date - first_date).days

    prices = [d['price'] for d in data_history]
    oi_list = [d['open_interest'] for d in data_history]

    price_range_pct = (max(prices) - min(prices)) / min(prices) * 100
    oi_growth_pct = (oi_list[-1] - oi_list[0]) / oi_list[0] * 100 if oi_list[0] > 0 else 0
    current_oi = oi_list[-1]
    recent_change = abs(data_history[-1]['price_change'])

    score = 0

    # Фильтр по длине базы
    if base_days < MIN_BASE_DAYS:
        return 0, base_days

    # Основной scoring
    if price_range_pct < 1.1:   score += 5
    elif price_range_pct < 2.0: score += 3

    if 5 <= oi_growth_pct <= 16:   score += 6
    elif 4 <= oi_growth_pct <= 22: score += 3

    if current_oi > 100_000_000: score += 4
    elif current_oi > 50_000_000:  score += 2

    if recent_change < 0.8:   score += 3

    return min(score, 10), base_days


# ... (остальной код get_active_symbols и process_symbol остаётся похожим)

async def process_symbol(client, symbol):
    try:
        oi_resp = await client.get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}")
        oi = float(oi_resp.json().get("openInterest", 0))
        if oi < MIN_OI_THRESHOLD:
            return

        ticker_resp = await client.get(f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}")
        t = ticker_resp.json()

        data = {
            "price": float(t.get("lastPrice", 0)),
            "open_interest": oi,
            "price_change": float(t.get("priceChangePercent", 0)),
            "timestamp": datetime.now()
        }

        if symbol not in history:
            history[symbol] = deque(maxlen=120)   # длинная история

        history[symbol].append(data)

        score, base_days = calculate_score(history[symbol])

        if score >= 7.5 and base_days >= MIN_BASE_DAYS:
            # отправка алерта...

            alert = f"""
🔥 <b>ТИХОЕ НАКОПЛЕНИЕ {score:.1f}/10</b>

📍 <b>{symbol}</b>
📅 База: <b>{base_days} дней</b>
💰 Цена: <code>{data['price']:.4f}</code>
📊 OI: <code>{oi:,.0f}</code>
📈 Рост OI: <code>{oi_growth_pct:.1f}%</code>
📉 Диапазон: <code>{price_range_pct:.2f}%</code>
            """.strip()

            await send_telegram(alert)
            log.info(f"СИГНАЛ [{score:.1f}/10 | {base_days}д] → {symbol}")

    except:
        pass


# main() функция остаётся почти такой же, только с интервалом 25 минут
