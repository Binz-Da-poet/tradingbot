"""
Kết nối Binance API cho giao dịch thực.

Bao gồm:
- Kết nối REST API để đặt lệnh
- WebSocket để nhận dữ liệu giá thời gian thực
- Cơ chế thử lại khi gặp lỗi mạng
"""

import os
import asyncio
import logging
from typing import Optional, Callable, Dict
from decimal import Decimal, ROUND_DOWN

from binance import AsyncClient, BinanceSocketManager
from binance.exceptions import BinanceAPIException, BinanceRequestException

logger = logging.getLogger("GiaoDichThuc")


class BinanceConnector:
    """
    Lớp kết nối Binance Spot API.
    Quản lý REST API và WebSocket.
    """

    MAX_RETRIES = 3
    RETRY_DELAY_BASE = 2  # giây, tăng theo cấp số nhân

    def __init__(self, api_key: str = None, api_secret: str = None):
        self.api_key = api_key or os.environ.get("BINANCE_API_KEY", "")
        self.api_secret = api_secret or os.environ.get("BINANCE_API_SECRET", "")
        self.client: Optional[AsyncClient] = None
        self.bm: Optional[BinanceSocketManager] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._running = False
        self._symbol_info: Dict = {}

    async def connect(self):
        """Khởi tạo kết nối đến Binance."""
        logger.info("Đang kết nối đến Binance...")
        self.client = await AsyncClient.create(
            api_key=self.api_key,
            api_secret=self.api_secret,
        )
        self.bm = BinanceSocketManager(self.client)
        self._running = True
        logger.info("Đã kết nối thành công đến Binance.")

    async def disconnect(self):
        """Ngắt kết nối an toàn."""
        self._running = False
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass

        if self.client:
            await self.client.close_connection()
            logger.info("Đã ngắt kết nối Binance.")

    async def get_account_balance(self, asset: str = "USDT") -> float:
        """Lấy số dư tài khoản cho một loại tài sản."""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                account = await self.client.get_account()
                for balance in account["balances"]:
                    if balance["asset"] == asset:
                        return float(balance["free"])
                return 0.0
            except (BinanceAPIException, BinanceRequestException) as e:
                logger.warning(
                    f"Lỗi lấy số dư (lần {attempt}/{self.MAX_RETRIES}): {e}"
                )
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAY_BASE ** attempt
                    await asyncio.sleep(delay)
                else:
                    raise

    async def get_symbol_info(self, symbol: str) -> Dict:
        """Lấy thông tin cặp giao dịch (bước giá, bước số lượng)."""
        if symbol in self._symbol_info:
            return self._symbol_info[symbol]

        info = await self.client.get_symbol_info(symbol)
        if info is None:
            raise ValueError(f"Không tìm thấy cặp giao dịch: {symbol}")

        filters = {f["filterType"]: f for f in info["filters"]}
        self._symbol_info[symbol] = {
            "raw": info,
            "filters": filters,
            "base_asset": info["baseAsset"],
            "quote_asset": info["quoteAsset"],
        }
        return self._symbol_info[symbol]

    def _adjust_quantity(self, symbol: str, quantity: float) -> float:
        """Làm tròn số lượng theo bước cho phép của Binance."""
        info = self._symbol_info.get(symbol, {})
        filters = info.get("filters", {})
        lot_filter = filters.get("LOT_SIZE", {})

        step_size = lot_filter.get("stepSize", "0.00000001")
        precision = max(0, len(step_size.rstrip("0").split(".")[-1]))

        qty = Decimal(str(quantity)).quantize(
            Decimal(step_size), rounding=ROUND_DOWN
        )
        return float(qty)

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> Dict:
        """
        Đặt lệnh thị trường (Market Order) với cơ chế thử lại.

        Tham số:
            symbol: cặp giao dịch (VD: "BTCUSDT")
            side: "BUY" hoặc "SELL"
            quantity: số lượng coin

        Trả về:
            Kết quả lệnh từ Binance API
        """
        # Lấy thông tin cặp giao dịch nếu chưa có
        if symbol not in self._symbol_info:
            await self.get_symbol_info(symbol)

        adjusted_qty = self._adjust_quantity(symbol, quantity)
        if adjusted_qty <= 0:
            raise ValueError(f"Số lượng sau điều chỉnh = 0: {quantity} → {adjusted_qty}")

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                logger.info(
                    f"Đặt lệnh {side} {adjusted_qty} {symbol} "
                    f"(lần {attempt}/{self.MAX_RETRIES})"
                )

                result = await self.client.create_order(
                    symbol=symbol,
                    side=side,
                    type="MARKET",
                    quantity=adjusted_qty,
                )

                fill_price = float(result.get("fills", [{}])[0].get("price", 0))
                fill_qty = float(result.get("executedQty", 0))

                logger.info(
                    f"Lệnh đã khớp: {side} {fill_qty} {symbol} "
                    f"@ {fill_price:.4f}"
                )
                return result

            except BinanceAPIException as e:
                logger.error(
                    f"Lỗi API Binance khi đặt lệnh (lần {attempt}): "
                    f"Mã {e.code} - {e.message}"
                )
                # Không thử lại nếu lỗi logic (VD: thiếu tiền, lệnh không hợp lệ)
                if e.code in (-2010, -1013, -1111):
                    raise
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAY_BASE ** attempt
                    logger.info(f"Chờ {delay}s trước khi thử lại...")
                    await asyncio.sleep(delay)
                else:
                    raise

            except BinanceRequestException as e:
                logger.error(
                    f"Lỗi kết nối Binance (lần {attempt}): {e}"
                )
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAY_BASE ** attempt
                    await asyncio.sleep(delay)
                else:
                    raise

    async def subscribe_kline(
        self,
        symbol: str,
        interval: str,
        callback: Callable,
    ):
        """
        Đăng ký nhận dữ liệu nến qua WebSocket.

        Gọi callback(kline_data) mỗi khi có nến mới đóng.
        kline_data là dict: {timestamp, open, high, low, close, volume, is_closed}
        """
        logger.info(f"Đăng ký WebSocket kline {symbol} khung {interval}")

        ts = self.bm.kline_socket(symbol, interval=interval)

        async with ts as stream:
            while self._running:
                try:
                    msg = await asyncio.wait_for(stream.recv(), timeout=60)

                    if msg.get("e") == "error":
                        logger.error(f"Lỗi WebSocket: {msg}")
                        continue

                    kline = msg.get("k", {})
                    kline_data = {
                        "timestamp": kline.get("t"),
                        "open": float(kline.get("o", 0)),
                        "high": float(kline.get("h", 0)),
                        "low": float(kline.get("l", 0)),
                        "close": float(kline.get("c", 0)),
                        "volume": float(kline.get("v", 0)),
                        "is_closed": kline.get("x", False),
                    }

                    await callback(kline_data)

                except asyncio.TimeoutError:
                    logger.warning("WebSocket timeout 60s, đang chờ tiếp...")
                    continue
                except asyncio.CancelledError:
                    logger.info("WebSocket bị hủy, thoát vòng lặp.")
                    break
                except Exception as e:
                    logger.error(f"Lỗi xử lý WebSocket: {e}")
                    await asyncio.sleep(1)

    async def get_current_price(self, symbol: str) -> float:
        """Lấy giá hiện tại của một cặp giao dịch."""
        ticker = await self.client.get_symbol_ticker(symbol=symbol)
        return float(ticker["price"])
