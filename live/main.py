"""
Điều phối chính cho chế độ giao dịch thực.

Luồng hoạt động:
1. Kết nối Binance API
2. Khởi tạo Risk Manager + Order Manager
3. Đăng ký WebSocket nhận nến
4. Tích lũy dữ liệu nến → tính chỉ báo → tạo tín hiệu
5. Nếu có tín hiệu MUA → mở vị thế qua Order Manager
6. Liên tục kiểm tra TP/SL cho các vị thế đang mở
7. Tắt an toàn khi nhận tín hiệu dừng
"""

import asyncio
import signal
import logging
import sys
from collections import deque
from datetime import datetime, timezone

import pandas as pd

import config
from core.data_handler import compute_indicators
from core.strategy import generate_signals
from live.execution import BinanceConnector
from live.risk_manager import RiskManager
from live.order_manager import OrderManager

logger = logging.getLogger("GiaoDichThuc")

# Số nến tối thiểu cần tích lũy trước khi bắt đầu phân tích
MIN_CANDLES = 60


class LiveTradingEngine:
    """
    Bộ máy giao dịch thực.
    Nhận dữ liệu nến từ WebSocket và thực thi chiến lược.
    """

    def __init__(
        self,
        symbol: str = None,
        ema_fast: int = None,
        ema_slow: int = None,
    ):
        self.symbol = symbol or config.BINANCE_SYMBOL
        self.ema_fast = ema_fast or config.EMA_FAST
        self.ema_slow = ema_slow or config.EMA_SLOW

        self.connector = BinanceConnector()
        self.risk_manager = RiskManager()
        self.order_manager = OrderManager(
            connector=self.connector,
            risk_manager=self.risk_manager,
        )

        # Bộ đệm nến (giữ tối đa 500 nến gần nhất)
        self._candle_buffer: deque = deque(maxlen=500)
        self._current_candle: dict = {}
        self._running = False

    async def start(self):
        """Khởi động hệ thống giao dịch thực."""
        logger.info("=" * 50)
        logger.info("  HỆ THỐNG GIAO DỊCH THỰC - KHỞI ĐỘNG")
        logger.info("=" * 50)
        logger.info(f"Cặp giao dịch: {self.symbol}")
        logger.info(f"EMA: {self.ema_fast}/{self.ema_slow}")
        logger.info(f"TP: {config.TP_PCT*100}% | SL: {config.SL_PCT*100}%")

        # Kết nối Binance
        await self.connector.connect()

        # Kiểm tra số dư
        balance = await self.connector.get_account_balance("USDT")
        logger.info(f"Số dư USDT: {balance:,.2f}")
        self.risk_manager.update_equity(balance)

        # Lấy thông tin cặp giao dịch
        await self.connector.get_symbol_info(self.symbol)

        self._running = True

        # Đăng ký WebSocket kline
        logger.info(f"Đăng ký WebSocket {self.symbol} khung {config.KLINE_INTERVAL}...")

        try:
            await self.connector.subscribe_kline(
                symbol=self.symbol,
                interval=config.KLINE_INTERVAL,
                callback=self._on_kline,
            )
        except asyncio.CancelledError:
            logger.info("Nhận tín hiệu dừng, đang tắt hệ thống...")
        finally:
            await self._shutdown()

    async def _on_kline(self, kline_data: dict):
        """
        Xử lý mỗi khi nhận được cập nhật nến từ WebSocket.
        Chỉ hành động khi nến đã đóng (is_closed = True).
        """
        current_price = kline_data["close"]

        # Luôn kiểm tra TP/SL với giá hiện tại
        await self.order_manager.check_tp_sl(self.symbol, current_price)

        # Chỉ phân tích khi nến đã đóng
        if not kline_data.get("is_closed", False):
            return

        # Thêm nến đã đóng vào bộ đệm
        self._candle_buffer.append({
            "timestamp": pd.Timestamp(kline_data["timestamp"], unit="ms", tz="UTC"),
            "open": kline_data["open"],
            "high": kline_data["high"],
            "low": kline_data["low"],
            "close": kline_data["close"],
            "volume": kline_data["volume"],
        })

        # Chờ đủ nến tối thiểu
        if len(self._candle_buffer) < MIN_CANDLES:
            logger.debug(
                f"Tích lũy nến: {len(self._candle_buffer)}/{MIN_CANDLES}"
            )
            return

        # Tạo DataFrame từ bộ đệm
        df = pd.DataFrame(list(self._candle_buffer))

        # Tính chỉ báo
        try:
            df = compute_indicators(
                df,
                ema_fast=self.ema_fast,
                ema_slow=self.ema_slow,
                rsi_period=config.RSI_PERIOD,
            )

            # Tạo tín hiệu
            df = generate_signals(
                df,
                rsi_threshold=config.RSI_THRESHOLD,
                use_rsi_filter=config.USE_RSI_FILTER,
            )
        except Exception as e:
            logger.error(f"Lỗi tính chỉ báo/tín hiệu: {e}")
            return

        # Kiểm tra tín hiệu ở nến cuối cùng
        if len(df) == 0:
            return

        last_row = df.iloc[-1]
        last_signal = last_row.get("signal", 0)

        if last_signal == 1:
            logger.info(
                f"TÍN HIỆU MUA! Giá: {current_price:.4f} | "
                f"EMA_F: {last_row['ema_fast']:.4f} | "
                f"EMA_S: {last_row['ema_slow']:.4f} | "
                f"RSI: {last_row['rsi']:.1f}"
            )

            position = await self.order_manager.open_position(
                symbol=self.symbol,
                current_price=current_price,
            )

            if position:
                logger.info(f"Đã mở vị thế: {position.position_id}")
            else:
                logger.info("Không mở được vị thế (bị chặn bởi quản lý rủi ro)")

        # Log trạng thái định kỳ
        risk_status = self.risk_manager.get_status()
        order_status = self.order_manager.get_status()
        logger.debug(
            f"Giá: {current_price:.2f} | "
            f"Vốn: {risk_status['von_hien_tai']:,.2f} | "
            f"DD: {risk_status['drawdown_pct']:.2f}% | "
            f"Lệnh mở: {order_status['vi_the_mo']}"
        )

    async def _shutdown(self):
        """Tắt hệ thống an toàn."""
        logger.info("Đang tắt hệ thống giao dịch...")
        self._running = False

        # Đóng tất cả vị thế đang mở
        try:
            current_price = await self.connector.get_current_price(self.symbol)
            await self.order_manager.close_all_positions(self.symbol, current_price)
        except Exception as e:
            logger.error(f"Lỗi khi đóng vị thế: {e}")

        # Ngắt kết nối
        await self.connector.disconnect()

        # In trạng thái cuối
        risk_status = self.risk_manager.get_status()
        logger.info("=" * 50)
        logger.info("  TRẠNG THÁI KẾT THÚC")
        logger.info("=" * 50)
        logger.info(f"  Vốn cuối: {risk_status['von_hien_tai']:,.2f} USD")
        logger.info(f"  Drawdown: {risk_status['drawdown_pct']:.2f}%")
        logger.info(f"  PnL hôm nay: {risk_status['pnl_hang_ngay']:+.2f} USD")
        logger.info(f"  Ngắt mạch: {'CÓ' if risk_status['ngat_mach'] else 'KHÔNG'}")
        logger.info("=" * 50)


def setup_logging():
    """Cấu hình logging cho giao dịch thực."""
    log_format = "%(asctime)s | %(name)-15s | %(levelname)-8s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Log ra console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format, date_format))

    # Log ra file
    file_handler = logging.FileHandler(
        "output/giao_dich_thuc.log", encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format, date_format))

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


async def run_live_trading(symbol: str = None):
    """Hàm chính để chạy giao dịch thực."""
    import os
    os.makedirs("output", exist_ok=True)

    setup_logging()

    engine = LiveTradingEngine(symbol=symbol)

    # Xử lý tín hiệu dừng
    loop = asyncio.get_running_loop()

    def handle_shutdown():
        logger.info("Nhận tín hiệu DỪNG (Ctrl+C)")
        engine._running = False
        for task in asyncio.all_tasks(loop):
            task.cancel()

    # Trên Windows, signal.SIGINT không hoạt động với asyncio event loop
    # nên sử dụng try/except KeyboardInterrupt bên ngoài
    try:
        if sys.platform != "win32":
            loop.add_signal_handler(signal.SIGINT, handle_shutdown)
            loop.add_signal_handler(signal.SIGTERM, handle_shutdown)
    except NotImplementedError:
        pass

    try:
        await engine.start()
    except KeyboardInterrupt:
        logger.info("Nhận Ctrl+C, đang tắt...")
        await engine._shutdown()
