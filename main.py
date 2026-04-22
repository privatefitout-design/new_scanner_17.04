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

MIN_OI_THRESHOLD = 8_000_000        # минимум OI
MIN_BASE_DAYS = 45                  # минимальная длина базы в днях
SCAN_INTERVAL_MINUTES = 20          # скан раз в 20 минут
ALERT_COOLDOWN_HOURS = 3            # cooldown алертов

history = {}       # symbol -> deque
last_alert = {}    # symbol -> время последнего алерта

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

    # Расчёт длины базы
    base_days = (data_history[-1]['timestamp'] - data_history[0]['timestamp']).days

    prices = [d['price'] for d in data_history]
    oi_list = [d['open_interest'] for d in data_history]

    price_range_pct = (max(prices) - min(prices)) / min(prices) * 100 if min(prices) > 0 else 999
    oi_growth_pct = (oi_list[-1] - oi_list[0]) / oi_list[0] * 100 if oi_list[0] > 0 else 0
    current_oi = oi_list[-1]
    recent_change = abs(data_history[-1]['price_change'])

    score = 0

    # Фильтр по длине базы
    if base_days < MIN_BASE_DAYS:
        return 0, base_days

    # Scoring
    if price_range_pct < 1.1:   score += 5
    elif price_range_pct < 2.0: score += 3

    if 5 <= oi_growth_pct <= 17:   score += 6
    elif 4 <= oi_growth_pct <= 23: score += 3

    if current_oi > 120_000_000: score += 4
    elif current_oi > 60_000_000:  score += 2

    if recent_change < 0.9:   score += 3

    return min(score, 10), base_days


async def get_active_symbols(client):
    """Предфильтр — только ликвидные пары"""
    try:
        resp = await client.get("https://fapi.binance.com/fapi/v1/ticker/24hr")
        symbols = []
        for item in resp.json():
            if (item['symbol'].endswith('USDT') and
                float(item.get('quoteVolume', 0)) > 80_000_000 and
                abs(float(item.get('priceChangePercent', 0))) < 10):
                symbols.append(item['symbol'])
        return symbols[:220]
    except:
        return []


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
            history[symbol] = deque(maxlen=100)

        history[symbol].append(data)

        score, base_days = calculate_score(history[symbol])

        if score >= 7.5:
            now = datetime.now()
            if (symbol not in last_alert or 
                (now - last_alert.get(symbol, datetime.min)) > timedelta(hours=ALERT_COOLDOWN_HOURS)):

                last_alert[symbol] = now

                alert = f"""
🔥 <b>ТИХОЕ НАКОПЛЕНИЕ {score:.1f}/10</b>

📍 <b>{symbol}</b>
📅 База: <b>{base_days} дней</b>
💰 Цена: <code>{data['price']:.4f}</code>
📊 OI: <code>{oi:,.0f}</code>
📈 Рост OI: <code>{oi_growth_pct:.1f}%</code>
📉 Диапазон: <code>{price_range_pct:.2f}%</code>
⏰ {now.strftime('%d.%m %H:%M')}
                """.strip()

                await send_telegram(alert)
                log.info(f"СИГНАЛ [{score:.1f}/10 | {base_days}д] → {symbol}")

        if score >= 5 or oi > 70_000_000:
            log.info(f"{symbol:>12} | OI: {oi:>13,.0f} | Score: {score:.1f}/10 | Days: {base_days}")

    except Exception as e:
        pass


async def main():
    log.info(f"Scanner запущен | База мин. {MIN_BASE_DAYS} дней | Скан каждые {SCAN_INTERVAL_MINUTES} минут")

    async with httpx.AsyncClient(timeout=15.0) as client:
        while True:
            start = datetime.now()
            log.info("Начинаем полный скан рынка...")

            symbols = await get_active_symbols(client)
            log.info(f"Анализируем {len(symbols)} пар...")

            tasks = [process_symbol(client, sym) for sym in symbols]
            await asyncio.gather(*tasks, return_exceptions=True)

            duration = (datetime.now() - start).seconds
            log.info(f"Скан завершён за {duration} сек. Следующий через {SCAN_INTERVAL_MINUTES} минут.\n")

            await asyncio.sleep(SCAN_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    asyncio.run(main())
