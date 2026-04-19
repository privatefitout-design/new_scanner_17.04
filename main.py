import asyncio
import os
import httpx
from datetime import datetime
from dotenv import load_dotenv
from collections import deque

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MIN_OI_THRESHOLD = 5_000_000      # теперь от 5 миллионов
ALERT_COOLDOWN_MINUTES = 60

SYMBOLS = None
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

def calculate_score(data_history):
    """Считаем scoring от 1 до 10"""
    if len(data_history) < 12:
        return 0

    prices = [d['price'] for d in data_history]
    oi_list = [d['open_interest'] for d in data_history]

    price_range_pct = (max(prices) - min(prices)) / min(prices) * 100
    oi_growth_pct = (oi_list[-1] - oi_list[0]) / oi_list[0] * 100 if oi_list[0] > 0 else 0
    current_oi = oi_list[-1]

    score = 0

    # Flat база (чем уже диапазон — тем выше балл)
    if price_range_pct < 1.5: score += 3
    elif price_range_pct < 2.5: score += 2
    elif price_range_pct < 3.5: score += 1

    # Рост OI
    if 8 < oi_growth_pct < 18: score += 3
    elif 5 < oi_growth_pct < 25: score += 2
    elif oi_growth_pct > 25: score += 1   # слишком резкий рост — меньше баллов

    # Размер OI (чем больше — тем выше приоритет)
    if current_oi > 100_000_000: score += 3
    elif current_oi > 50_000_000: score += 2
    elif current_oi > 20_000_000: score += 1

    # Последнее движение цены не должно быть сильным
    if abs(data_history[-1]['price_change']) < 1.2: score += 1

    return min(score, 10)  # максимум 10 баллов

async def main():
    print(f"[{datetime.now()}] Scanner запущен | Min OI: 5M | Scoring система")

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Получаем все пары
        resp = await client.get("https://fapi.binance.com/fapi/v1/exchangeInfo")
        all_symbols = [s['symbol'] for s in resp.json()['symbols'] 
                      if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING']
        
        print(f"Найдено {len(all_symbols)} пар. Начинаем мониторинг...\n")

        while True:
            tasks = []
            for symbol in all_symbols:
                tasks.append(process_symbol(client, symbol))

            await asyncio.gather(*tasks, return_exceptions=True)

            print(f"\n[{datetime.now()}] Цикл завершён. Следующий через 20 сек...\n")
            await asyncio.sleep(20)

async def process_symbol(client, symbol):
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
            "volume": float(t.get("volume", 0)),
            "price_change": float(t.get("priceChangePercent", 0)),
        }

        if symbol not in history:
            history[symbol] = deque(maxlen=30)
        history[symbol].append(data)

        score = calculate_score(history[symbol])

        if score >= 6:   # порог для алерта
            now = datetime.now().timestamp()
            if symbol not in last_alert or (now - last_alert.get(symbol, 0)) > ALERT_COOLDOWN_MINUTES * 60:
                last_alert[symbol] = now

                alert = f"""
🔥 <b>Сигнал #{score}/10</b>

📍 <b>{symbol}</b>
💰 Цена: <code>{data['price']:.2f}</code>
📊 OI: <code>{oi:,.0f}</code>
📉 Диапазон цены: <code>{(max(p['price'] for p in history[symbol]) - min(p['price'] for p in history[symbol])) / min(p['price'] for p in history[symbol]) * 100:.2f}%</code>
⭐ Score: <b>{score}/10</b>
⏰ {datetime.now().strftime('%H:%M:%S')}
                """.strip()

                await send_telegram(alert)
                print(f"✅ АЛЕРТ [{score}/10] → {symbol}")

        # Вывод в консоль только интересных пар
        if score >= 4 or oi > 30_000_000:
            print(f"{symbol:>10} | OI: {oi:>12,.0f} | Price: {data['price']:>9.2f} | Score: {score}/10")

    except:
        pass

if __name__ == "__main__":
    asyncio.run(main())
