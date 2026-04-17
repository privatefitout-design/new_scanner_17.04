"""
CRYPTO PRE-BREAKOUT SCANNER v5.1
Тихое накопление + рост OI при почти плоской цене
"""

import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from apscheduler.schedulers.blocking import BlockingScheduler

# ====================== НАСТРОЙКИ ======================
TELEGRAM_TOKEN = "8731868942:AAEKTM-hbrskq52V3wFtoKfUEr2Hn5-mrHQ"
CHAT_ID        = "181943757"

MIN_SCORE       = 28
TOP_RESULTS     = 8
SCAN_INTERVAL   = 30        # минут
WORKERS         = 9

OI_MIN_GROWTH   = 2.5
PRICE_CHG_MAX   = 18
BASE_RANGE_MAX  = 65
DOWNTREND_MAX   = -30

# ====================== ЛОГИ ======================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

BASE_URL = "https://fapi.binance.com"

def api_call(endpoint, params=None):
    try:
        r = requests.get(f"{BASE_URL}{endpoint}", params=params, timeout=12)
        return r.json() if r.status_code == 200 else None
    except:
        return None

def get_all_symbols():
    data = api_call("/fapi/v1/exchangeInfo")
    if not data:
        return []
    return [
        s['symbol'] for s in data.get('symbols', [])
        if s.get('quoteAsset') == 'USDT'
        and s.get('status') == 'TRADING'
        and s.get('contractType') == 'PERPETUAL'
    ]

def get_klines(symbol, interval, limit=200):
    data = api_call("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    if not data or len(data) < 20:
        return None
    df = pd.DataFrame(data, columns=['open_time','open','high','low','close','volume','close_time',
                                     'quote_vol','trades','taker_buy_base','taker_buy_quote','ignore'])
    for col in ['open','high','low','close','volume']:
        df[col] = pd.to_numeric(df[col])
    return df

def get_oi_hist(symbol, period, limit=60):
    data = api_call("/futures/data/openInterestHist", {"symbol": symbol, "period": period, "limit": limit})
    if not data:
        return None
    df = pd.DataFrame(data)
    df['oi'] = pd.to_numeric(df['sumOpenInterest'])
    return df

def calc_natr(df, window=14):
    if df is None or len(df) < window:
        return pd.Series()
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return (tr.rolling(window).mean() / c * 100).round(3)

def oi_slope_angle(oi_series):
    try:
        y = np.array(oi_series, dtype=float)
        if len(y) < 5:
            return 0.0
        x = np.arange(len(y))
        y_norm = (y - y.min()) / (y.max() - y.min() + 1e-8)
        slope = np.polyfit(x, y_norm, 1)[0]
        angle = np.degrees(np.arctan(slope * len(y) * 0.75))
        return round(max(0, min(85, angle)), 1)
    except:
        return 0.0

def pattern_d(symbol):
    try:
        k1d = get_klines(symbol, "1d", 200)
        k1h = get_klines(symbol, "1h", 60)
        oi_1h = get_oi_hist(symbol, "1h", 50)

        if k1d is None or k1h is None or oi_1h is None or len(k1h) < 15:
            return 0, None

        score = 0
        data = {"symbol": symbol, "price": round(k1d['close'].iloc[-1], 6)}

        # Защита от даунтренда
        if len(k1d) >= 80:
            trend = (k1d['close'].iloc[-20] - k1d['close'].iloc[-80]) / k1d['close'].iloc[-80] * 100
            if trend < DOWNTREND_MAX:
                return 0, None

        # NATR база
        natr_1d = calc_natr(k1d, 14)
        if len(natr_1d) > 30:
            natr_base = natr_1d.iloc[-40:-5].mean()
            if natr_base > 7.5:
                return 0, None
            if natr_base < 2.0: score += 28
            elif natr_base < 3.5: score += 22
            elif natr_base < 5.0: score += 14
            else: score += 8

        # NATR awakening
        natr_1h = calc_natr(k1h, 7)
        if len(natr_1h) >= 12:
            awaken = natr_1h.iloc[-4:].mean() / natr_1h.iloc[-12:-3].mean()
            data['awakening'] = round(awaken, 2)
            if awaken > 2.8:
                return 0, None
            if awaken > 1.9: score += 26
            elif awaken > 1.35: score += 17
            elif awaken > 1.1: score += 9

        # Диапазон базы
        base_range = (k1d['high'].iloc[-60:-5].max() - k1d['low'].iloc[-60:-5].min()) / \
                     k1d['low'].iloc[-60:-5].min() * 100
        data['base_range'] = round(base_range, 1)
        if base_range > BASE_RANGE_MAX:
            return 0, None

        # OI рост и угол
        oi_now = oi_1h['oi'].iloc[-1]
        oi_12h = round((oi_now - oi_1h['oi'].iloc[-12]) / oi_1h['oi'].iloc[-12] * 100, 1) if len(oi_1h) >= 12 else 0
        data['oi_12h'] = oi_12h

        if oi_12h < OI_MIN_GROWTH:
            return 0, None

        angle = oi_slope_angle(oi_1h['oi'].iloc[-14:])
        data['angle'] = angle

        if angle > 76:
            return 0, None
        if 42 <= angle <= 68:
            score += 32
        elif 35 <= angle <= 74:
            score += 18
        else:
            score += 8

        # Цена почти стоит
        price_chg = abs((data['price'] - k1h['close'].iloc[-6]) / k1h['close'].iloc[-6] * 100) if len(k1h) >= 6 else 99
        data['price_chg_6h'] = round(price_chg, 2)

        if price_chg > PRICE_CHG_MAX:
            return 0, None

        if price_chg < 1.2: score += 28
        elif price_chg < 2.5: score += 20
        elif price_chg < 5: score += 12
        else: score += 5

        data['score'] = score
        return score, data

    except Exception as e:
        log.debug(f"Error in {symbol}: {e}")
        return 0, None

def send_telegram(message):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"},
            timeout=10
        )
    except:
        pass

def run_scan():
    log.info("=" * 70)
    log.info(f"PRE-BREAKOUT SCANNER v5.1  |  {datetime.now().strftime('%d.%m %H:%M')}")
    log.info("=" * 70)

    symbols = get_all_symbols()
    log.info(f"Символов загружено: {len(symbols)}")

    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(pattern_d, sym): sym for sym in symbols}

        for future in as_completed(futures):
            score, data = future.result()
            if score >= MIN_SCORE and data:
                results.append(data)

    results.sort(key=lambda x: x['score'], reverse=True)
    top = results[:TOP_RESULTS]

    if top:
        msg = f"🟢 **PRE-BREAKOUT SIGNALS** — {datetime.now().strftime('%H:%M')}\n\n"
        for r in top:
            msg += f"**{r['symbol']}**  Score: **{r['score']}**  Angle: **{r.get('angle')}°**\n"
            msg += f"OI +{r.get('oi_12h')}% • Цена ±{r.get('price_chg_6h')}% • База {r.get('base_range')}%\n\n"
        send_telegram(msg)
        log.info(f"Отправлено {len(top)} сигналов")
    else:
        log.info("Сигналов не найдено")

    log.info("=" * 70)

if __name__ == "__main__":
    log.info("Сканер запущен | Интервал сканирования: 30 минут")
    run_scan()

    scheduler = BlockingScheduler()
    scheduler.add_job(run_scan, 'interval', minutes=SCAN_INTERVAL)
    scheduler.start()
