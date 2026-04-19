import asyncio
import os
import httpx
from datetime import datetime
from dotenv import load_dotenv
from collections import deque

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT']

# История данных для анализа
history = {symbol: deque(maxlen=30) for symbol in SYMBOLS}
last_alert = {}

async def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram не настроен")
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
            )
    except Exception as e:
        print(f"Ошибка Telegram: {e}")

class BinanceClient:
    BASE_URL = "https://fapi.binance.com"

    async def get_data(self, symbol: str):
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                oi_resp = await client.get(f"{self.BASE_URL}/fapi/v1/openInterest?symbol={symbol}")
                oi = float(oi_resp.json().get("openInterest", 0))

                ticker_resp = await client.get(f"{self.BASE_URL}/fapi/v1/ticker/24hr?symbol={symbol}")
                t = ticker_resp.json()

                return {
                    "symbol": symbol,
                    "price": float(t.get("lastPrice", 0)),
                    "open_interest": oi,
                    "volume": float(t.get("volume", 0)),
                    "price_change": float(t.get("priceChangePercent", 0)),
                    "high": float(t.get("highPrice", 0)),
                    "low": float(t.get("lowPrice", 0)),
                    "timestamp": datetime.now()
                }
            except Exception as e:
                print(f"Ошибка {symbol}: {e}")
                return None

def is_good_setup(symbol_data):
    """Улучшенное условие: flat база + тихий рост OI"""
    if len(symbol_data) < 10:
        return False

    prices = [d['price'] for d in symbol_data]
    oi_list = [d['open_interest'] for d in symbol_data]

    price_range_pct = (max(prices) - min(prices)) / min(prices) * 100
    oi_growth_pct = (oi_list[-1] - oi_list[0]) / oi_list[0] * 100 if oi_list[0] > 0 else 0

    conditions = [
        price_range_pct < 2.5,           # узкий диапазон (flat)
        4 < oi_growth_pct < 22,          # умеренный рост OI
        abs(symbol_data[-1]['price_change']) < 1.5,   # цена почти не двигается
    ]

    return all(conditions)

async def main():
    print(f"[{datetime.now()}] ScreenerLabs Scanner запущен (всё в main.py)")
    
    client = BinanceClient()

    print("Мониторим:", SYMBOLS)
    print("Ищем flat базу + тихий рост OI...\n")

    try:
        while True:
            for symbol in SYMBOLS:
                data = await client.get_data(symbol)
                if not data:
                    continue

                history[symbol].append(data)

                if is_good_setup(history[symbol]):
                    now = datetime.now().timestamp()
                    if symbol not in last_alert or (now - last_alert.get(symbol, 0)) > 300:  # 5 минут
                        last_alert[symbol] = now

                        alert = f"""
🔥 <b>Зарождение движения!</b>

📍 <b>{symbol}</b>
💰 Цена: <code>{data['price']:.2f}</code>
📊 OI: <code>{data['open_interest']:,.0f}</code>
📉 Диапазон цены: <code>{(max(p['price'] for p in history[symbol]) - min(p['price'] for p in history[symbol])) / min(p['price'] for p in history[symbol]) * 100:.2f}%</code>
⏰ {datetime.now().strftime('%H:%M:%S')}
                        """.strip()

                        await send_telegram(alert)
                        print(f"✅ АЛЕРТ → {symbol}")

                print(f"{symbol:>8} | OI: {data['open_interest']:>12,.0f} | Price: {data['price']:>8.2f} | Chg: {data['price_change']:>6.2f}%")

            print("-" * 100)
            await asyncio.sleep(25)

    except KeyboardInterrupt:
        print("\nСканер остановлен.")

if __name__ == "__main__":
    asyncio.run(main())