import asyncio
import os
import httpx
from datetime import datetime, timedelta
from dotenv import load_dotenv
from collections import deque

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ================== НАСТРОЙКИ ==================
MAX_WORKERS = 16                    # количество параллельных worker'ов
SCAN_INTERVAL = 20                  # секунд между полными сканами
ALERT_COOLDOWN = 60 * 60            # 1 час между алертами по одному символу

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

async def fetch_symbol_data(client, symbol):
    try:
        # Open Interest
        oi_resp = await client.get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}")
        oi = float(oi_resp.json().get("openInterest", 0))

        # Ticker
        ticker_resp = await client.get(f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}")
        t = ticker_resp.json()

        return {
            "symbol": symbol,
            "price": float(t.get("lastPrice", 0)),
            "open_interest": oi,
            "volume": float(t.get("volume", 0)),
            "price_change": float(t.get("priceChangePercent", 0)),
            "timestamp": datetime.now()
        }
    except:
        return None

def is_flat_base_pattern(data_history):
    if len(data_history) < 15:
        return False

    prices = [d['price'] for d in data_history]
    oi_list = [d['open_interest'] for d in data_history]

    price_range_pct = (max(prices) - min(prices)) / min(prices) * 100
    oi_growth_pct = (oi_list[-1] - oi_list[0]) / oi_list[0] * 100 if oi_list[0] > 0 else 0

    return (
        price_range_pct < 2.6 and      # плоская база
        6 < oi_growth_pct < 25 and     # умеренный рост OI
        abs(data_history[-1]['price_change']) < 1.7
    )

async def worker(client, symbol, semaphore):
    async with semaphore:
        data = await fetch_symbol_data(client, symbol)
        if not data:
            return

        if symbol not in history:
            history[symbol] = deque(maxlen=30)
        history[symbol].append(data)

        if is_flat_base_pattern(history[symbol]):
            now = datetime.now().timestamp()
            if symbol not in last_alert or (now - last_alert.get(symbol, 0)) > ALERT_COOLDOWN:
                last_alert[symbol] = now

                alert = f"""
🔥 <b>Зарождение движения!</b>

📍 <b>{symbol}</b>
💰 Цена: <code>{data['price']:.2f}</code>
📊 OI: <code>{data['open_interest']:,.0f}</code>
📉 Диапазон: <code>{(max(p['price'] for p in history[symbol]) - min(p['price'] for p in history[symbol])) / min(p['price'] for p in history[symbol]) * 100:.2f}%</code>
⏰ {datetime.now().strftime('%H:%M:%S')}
                """.strip()

                await send_telegram(alert)
                print(f"✅ АЛЕРТ → {symbol}")

        print(f"{symbol:>10} | OI: {data['open_interest']:>12,.0f} | Price: {data['price']:>8.2f} | Chg: {data['price_change']:>6.2f}%")

async def main():
    print(f"[{datetime.now()}] Scanner запущен | Workers: {MAX_WORKERS} | Интервал: {SCAN_INTERVAL} сек")

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Получаем список всех USDT-M фьючерсов
        resp = await client.get("https://fapi.binance.com/fapi/v1/exchangeInfo")
        all_symbols = [s['symbol'] for s in resp.json()['symbols'] if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING']

        print(f"Найдено {len(all_symbols)} торговых пар. Начинаем мониторинг...\n")

        semaphore = asyncio.Semaphore(MAX_WORKERS)

        while True:
            tasks = [worker(client, symbol, semaphore) for symbol in all_symbols]
            await asyncio.gather(*tasks, return_exceptions=True)
            print(f"\n[{datetime.now()}] Полный цикл завершён. Следующий через {SCAN_INTERVAL} сек...\n")
            await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
