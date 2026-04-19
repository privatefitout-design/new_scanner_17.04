import httpx
from typing import Dict, Optional

class BinanceFuturesClient:
    BASE_URL = "https://fapi.binance.com"

    async def get_ticker_data(self, symbol: str) -> Optional[Dict]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                # Open Interest
                oi_resp = await client.get(f"{self.BASE_URL}/fapi/v1/openInterest?symbol={symbol}")
                oi_data = oi_resp.json()

                # 24hr Ticker
                ticker_resp = await client.get(f"{self.BASE_URL}/fapi/v1/ticker/24hr?symbol={symbol}")
                ticker = ticker_resp.json()

                return {
                    "symbol": symbol,
                    "open_interest": float(oi_data.get("openInterest", 0)),
                    "price": float(ticker.get("lastPrice", 0)),
                    "volume": float(ticker.get("volume", 0)),
                    "price_change_percent": float(ticker.get("priceChangePercent", 0)),
                    "high_price": float(ticker.get("highPrice", 0)),
                    "low_price": float(ticker.get("lowPrice", 0))
                }
            except Exception as e:
                print(f"Ошибка получения данных {symbol}: {e}")
                return None