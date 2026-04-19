import asyncio
import os
import httpx
from datetime import datetime, timedelta
from dotenv import load_dotenv
from collections import deque

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT']

history = {symbol: deque(maxlen=30) for symbol in SYMBOLS}
last_alert_time = {}        # когда последний раз присылали алерт
active_signals = {}         # запоминаем активные сетапы

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
                }
            except:
                return None

def is_flat_base_with_oi_growth(symbol_data):
    if len(symbol_data) < 12:
        return False

    prices = [d['price'] for d in symbol_data]
    oi_list = [d['open_interest'] for d in symbol_data]

    price_range = (max(prices) - min(prices)) / min(prices) * 100
    oi_growth = (oi_list[-1] - oi_list[0]) / oi_list[0] * 100 if oi_list[0] > 0 else 0

    return (
        price_range < 2.8 and           # плоская база
        5 < oi_growth < 28 and         # умеренный рост OI
        abs(symbol_data[-1]['price_change']) < 1.6
    )

async def main():
    print(f"[{datetime.now()}] Scanner запущен с маркировкой сигналов")

    client = BinanceClient()

    while True:
        for symbol in SYMBOLS:
            data = await client.get_data(symbol)
            if not data:
                continue

            history[symbol].append(data)

            # Проверяем условие
            if is_flat_base_with_oi_growth(history[symbol]):
                now = datetime.now()

                # Проверяем, не отправляли ли мы уже алерт по этому символу недавно
                last = last_alert_time.get(symbol)
                if not last or (now - last) > timedelta(minutes=60):   # 1 раз в час
                    last_alert_time[symbol] = now

                    alert = f"""
🔥 <b>Зарождение движения!</b>

📍 <b>{symbol}</b>
💰 Цена: <code>{data['price']:.2f}</code>
📊 OI: <code>{data['open_interest']:,.0f}</code>
📉 Диапазон цены: <code>{(max(p['price'] for p in history[symbol]) - min(p['price'] for p in history[symbol])) / min(p['price'] for p in history[symbol]) * 100:.2f}%</code>
⏰ {now.strftime('%H:%M:%S')}
                    """.strip()

                    await send_telegram(alert)
                    print(f"✅ АЛЕРТ отправлен → {symbol}")

            print(f"{symbol:>8} | OI: {data['open_interest']:>12,.0f} | Price: {data['price']:>8.2f} | Chg: {data['price_change']:>6.2f}%")

        print("-" * 90)
        await asyncio.sleep(25)

if __name__ == "__main__":
    asyncio.run(main())
