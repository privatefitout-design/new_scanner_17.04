import asyncio
import os
import httpx
from datetime import datetime
from dotenv import load_dotenv
from collections import deque

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ================== НАСТРОЙКИ ==================
MAX_WORKERS = 16
SCAN_INTERVAL = 20
ALERT_COOLDOWN_MINUTES = 60

MIN_OI_THRESHOLD = 50_000_000   # минимальный OI, чтобы рассматривать пару (50 миллионов)

SYMBOLS = None  # будет заполнено автоматически

history = {}
last_alert = {}

async def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
            )
    except:
        pass

async def get_all_symbols(client):
    try:
        resp = await client.get("https://fapi.binance.com/fapi/v1/exchangeInfo")
        symbols = [s['symbol'] for s in resp.json()['symbols'] 
                  if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING']
        return symbols
    except:
        return ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']

async def main():
    global SYMBOLS
    print(f"[{datetime.now()}] Scanner запущен | Workers: {MAX_WORKERS}")

    async with httpx.AsyncClient(timeout=15.0) as client:
        SYMBOLS = await get_all_symbols(client)
        print(f"Найдено {len(SYMBOLS)} торговых пар. Фильтр OI > {MIN_OI_THRESHOLD:,}\n")

        semaphore = asyncio.Semaphore(MAX_WORKERS)

        while True:
            tasks = []
            for symbol in SYMBOLS:
                tasks.append(process_symbol(client, symbol, semaphore))

            await asyncio.gather(*tasks, return_exceptions=True)

            print(f"\n[{datetime.now()}] Полный цикл завершён. Следующий через {SCAN_INTERVAL} сек...\n")
            await asyncio.sleep(SCAN_INTERVAL)

async def process_symbol(client, symbol, semaphore):
    async with semaphore:
        try:
            oi_resp = await client.get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}")
            oi = float(oi_resp.json().get("openInterest", 0))

            if oi < MIN_OI_THRESHOLD:
                return

            ticker_resp = await client.get(f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}")
            t = ticker_resp.json()

            data = {
                "symbol": symbol,
                "price": float(t.get("lastPrice", 0)),
                "open_interest": oi,
                "price_change": float(t.get("priceChangePercent", 0)),
            }

            if symbol not in history:
                history[symbol] = deque(maxlen=30)
            history[symbol].append(data)

            # Проверка условия
            if is_flat_base_pattern(history[symbol]):
                now = datetime.now().timestamp()
                if symbol not in last_alert or (now - last_alert.get(symbol, 0)) > ALERT_COOLDOWN_MINUTES * 60:
                    last_alert[symbol] = now
                    alert = f"🔥 Зарождение!\n{symbol}\nЦена: {data['price']:.2f}\nOI: {oi:,.0f}\nДиапазон: {calculate_range(history[symbol]):.2f}%"
                    await send_telegram(alert)
                    print(f"✅ АЛЕРТ → {symbol}")

            print(f"{symbol:>10} | OI: {oi:>12,.0f} | Price: {data['price']:>9.2f} | Chg: {data['price_change']:>6.2f}%")

        except:
            pass

def is_flat_base_pattern(data_history):
    if len(data_history) < 12:
        return False
    prices = [d['price'] for d in data_history]
    oi_list = [d['open_interest'] for d in data_history]

    price_range = (max(prices) - min(prices)) / min(prices) * 100
    oi_growth = (oi_list[-1] - oi_list[0]) / oi_list[0] * 100 if oi_list[0] > 0 else 0

    return price_range < 2.8 and 5 < oi_growth < 25 and abs(data_history[-1]['price_change']) < 1.8

def calculate_range(data_history):
    prices = [d['price'] for d in data_history]
    return (max(prices) - min(prices)) / min(prices) * 100

if __name__ == "__main__":
    asyncio.run(main())
