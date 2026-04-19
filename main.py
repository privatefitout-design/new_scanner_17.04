import asyncio
import os
import httpx
from datetime import datetime
from dotenv import load_dotenv
from collections import deque

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT']

history = {symbol: deque(maxlen=25) for symbol in SYMBOLS}
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

async def main():
    print(f"[{datetime.now()}] Scanner запущен")

    async with httpx.AsyncClient(timeout=15.0) as client:
        while True:
            for symbol in SYMBOLS:
                try:
                    # Open Interest
                    oi_resp = await client.get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}")
                    oi = float(oi_resp.json().get("openInterest", 0))

                    # Ticker
                    ticker_resp = await client.get(f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}")
                    t = ticker_resp.json()

                    price = float(t.get("lastPrice", 0))
                    price_change = float(t.get("priceChangePercent", 0))

                    data = {
                        "symbol": symbol,
                        "price": price,
                        "open_interest": oi,
                        "price_change": price_change
                    }

                    history[symbol].append(data)

                    # Простая проверка flat базы
                    if len(history[symbol]) >= 8:
                        prices = [d['price'] for d in history[symbol]]
                        price_range = (max(prices) - min(prices)) / min(prices) * 100
                        oi_growth = (oi - history[symbol][0]['open_interest']) / history[symbol][0]['open_interest'] * 100 if history[symbol][0]['open_interest'] > 0 else 0

                        if price_range < 2.8 and 5 < oi_growth < 25 and abs(price_change) < 1.8:
                            now = datetime.now().timestamp()
                            if symbol not in last_alert or (now - last_alert.get(symbol, 0)) > 300:
                                last_alert[symbol] = now
                                alert = f"🔥 Зарождение!\n{symbol}\nЦена: {price:.2f}\nOI рост: {oi_growth:.1f}%\nДиапазон: {price_range:.2f}%"
                                await send_telegram(alert)
                                print(f"АЛЕРТ → {symbol}")

                    print(f"{symbol:>8} | OI: {oi:>12,.0f} | Price: {price:>8.2f} | Chg: {price_change:>6.2f}%")

                except Exception as e:
                    print(f"Ошибка {symbol}: {e}")

            print("-" * 80)
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
