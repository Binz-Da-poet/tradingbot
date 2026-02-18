"""
Quản lý rủi ro thời gian thực cho giao dịch thực.

Quy tắc:
- Rủi ro tối đa 1% vốn mỗi lệnh
- Lỗ tối đa trong ngày 3%
- Tối đa 3 lệnh mở cùng lúc
- Ngắt mạch khi drawdown > 10%
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import config

logger = logging.getLogger("QuanLyRuiRo")


class RiskManager:
    """
    Bộ quản lý rủi ro thời gian thực.
    Kiểm soát tất cả điều kiện trước khi cho phép mở lệnh.
    """

    def __init__(
        self,
        initial_capital: float = None,
        risk_per_trade: float = None,
        max_daily_loss: float = None,
        max_open_trades: int = None,
        circuit_breaker_dd: float = None,
    ):
        self.initial_capital = initial_capital or config.INITIAL_CAPITAL
        self.risk_per_trade = risk_per_trade or config.RISK_PER_TRADE
        self.max_daily_loss = max_daily_loss or config.MAX_DAILY_LOSS
        self.max_open_trades = max_open_trades or config.MAX_OPEN_TRADES
        self.circuit_breaker_dd = circuit_breaker_dd or config.CIRCUIT_BREAKER_DD

        # Trạng thái
        self.current_equity = self.initial_capital
        self.peak_equity = self.initial_capital
        self.open_trade_count = 0
        self.circuit_breaker_active = False

        # Theo dõi lãi/lỗ hàng ngày
        self._daily_pnl = 0.0
        self._current_date: Optional[datetime] = None
        self._daily_start_equity = self.initial_capital

        logger.info(
            f"Khởi tạo quản lý rủi ro: "
            f"vốn={self.initial_capital:,.0f}, "
            f"rủi_ro/lệnh={self.risk_per_trade*100}%, "
            f"lỗ_ngày_max={self.max_daily_loss*100}%, "
            f"lệnh_mở_max={self.max_open_trades}, "
            f"ngắt_mạch={self.circuit_breaker_dd*100}%"
        )

    def update_equity(self, new_equity: float):
        """Cập nhật vốn hiện tại và kiểm tra ngắt mạch."""
        self.current_equity = new_equity
        self.peak_equity = max(self.peak_equity, new_equity)
        self._check_circuit_breaker()

    def record_trade_pnl(self, pnl: float):
        """Ghi nhận lãi/lỗ của một lệnh đã đóng."""
        self._daily_pnl += pnl
        logger.info(f"Ghi nhận PnL: {pnl:+.2f} USD | PnL hàng ngày: {self._daily_pnl:+.2f} USD")

    def trade_opened(self):
        """Ghi nhận đã mở thêm một lệnh."""
        self.open_trade_count += 1
        logger.info(f"Lệnh mở: {self.open_trade_count}/{self.max_open_trades}")

    def trade_closed(self):
        """Ghi nhận đã đóng một lệnh."""
        self.open_trade_count = max(0, self.open_trade_count - 1)
        logger.info(f"Lệnh mở còn: {self.open_trade_count}/{self.max_open_trades}")

    def can_trade(self) -> bool:
        """
        Kiểm tra tổng hợp: có được phép mở lệnh mới không?
        Trả về True nếu tất cả điều kiện đều thỏa mãn.
        """
        self._update_daily_tracking()

        # Kiểm tra 1: Ngắt mạch
        if self.circuit_breaker_active:
            logger.warning("CHẶN: Ngắt mạch đang kích hoạt (drawdown vượt ngưỡng)")
            return False

        # Kiểm tra 2: Số lệnh mở
        if self.open_trade_count >= self.max_open_trades:
            logger.warning(
                f"CHẶN: Đã đạt giới hạn lệnh mở "
                f"({self.open_trade_count}/{self.max_open_trades})"
            )
            return False

        # Kiểm tra 3: Lỗ hàng ngày
        if self._daily_start_equity > 0:
            daily_loss_pct = abs(min(0, self._daily_pnl)) / self._daily_start_equity
            if daily_loss_pct >= self.max_daily_loss:
                logger.warning(
                    f"CHẶN: Lỗ hàng ngày vượt ngưỡng "
                    f"({daily_loss_pct*100:.2f}% >= {self.max_daily_loss*100}%)"
                )
                return False

        logger.debug("Cho phép giao dịch: tất cả điều kiện rủi ro đều OK")
        return True

    def calculate_position_size(
        self,
        entry_price: float,
        sl_price: float,
    ) -> float:
        """
        Tính kích thước lệnh dựa trên rủi ro.

        Tham số:
            entry_price: giá vào lệnh dự kiến
            sl_price: mức cắt lỗ

        Trả về:
            Số lượng coin nên mua
        """
        risk_amount = self.current_equity * self.risk_per_trade
        sl_distance = abs(entry_price - sl_price)

        if sl_distance <= 0:
            logger.warning("Khoảng cắt lỗ = 0, không thể tính kích thước lệnh")
            return 0.0

        quantity = risk_amount / sl_distance
        cost = quantity * entry_price

        # Đảm bảo không vượt quá vốn khả dụng
        if cost > self.current_equity * 0.95:
            quantity = (self.current_equity * 0.95) / entry_price
            logger.warning(
                f"Giảm kích thước lệnh để không vượt 95% vốn: {quantity:.8f}"
            )

        return quantity

    def _check_circuit_breaker(self):
        """Kích hoạt ngắt mạch nếu drawdown vượt ngưỡng."""
        if self.peak_equity <= 0:
            return

        drawdown = (self.peak_equity - self.current_equity) / self.peak_equity

        if drawdown >= self.circuit_breaker_dd and not self.circuit_breaker_active:
            self.circuit_breaker_active = True
            logger.critical(
                f"NGẮT MẠCH KÍCH HOẠT! Drawdown = {drawdown*100:.2f}% "
                f"(ngưỡng = {self.circuit_breaker_dd*100}%). "
                f"Dừng tất cả giao dịch."
            )

    def _update_daily_tracking(self):
        """Reset lãi/lỗ hàng ngày khi sang ngày mới (UTC)."""
        now = datetime.now(timezone.utc).date()
        if self._current_date is None or now != self._current_date:
            if self._current_date is not None:
                logger.info(
                    f"Sang ngày mới ({now}). "
                    f"PnL hôm qua: {self._daily_pnl:+.2f} USD. Reset."
                )
            self._current_date = now
            self._daily_pnl = 0.0
            self._daily_start_equity = self.current_equity

    def get_status(self) -> dict:
        """Trả về trạng thái hiện tại của bộ quản lý rủi ro."""
        drawdown = 0.0
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - self.current_equity) / self.peak_equity

        return {
            "von_hien_tai": round(self.current_equity, 2),
            "dinh_von": round(self.peak_equity, 2),
            "drawdown_pct": round(drawdown * 100, 2),
            "lenh_mo": self.open_trade_count,
            "lenh_mo_toi_da": self.max_open_trades,
            "pnl_hang_ngay": round(self._daily_pnl, 2),
            "ngat_mach": self.circuit_breaker_active,
        }
