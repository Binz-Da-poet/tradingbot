"""
Quản lý vòng đời lệnh cho giao dịch thực.

Chức năng:
- Theo dõi lệnh đang chờ, đã khớp, đã hủy
- Quản lý TP/SL cục bộ (theo dõi giá và đặt lệnh thị trường khi đạt mục tiêu)
- Tương tác với risk_manager khi lệnh khớp/đóng
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, timezone

import config
from live.execution import BinanceConnector
from live.risk_manager import RiskManager

logger = logging.getLogger("QuanLyLenh")


@dataclass
class LivePosition:
    """Vị thế đang mở trong giao dịch thực."""
    position_id: str
    symbol: str
    entry_price: float
    quantity: float
    tp_price: float
    sl_price: float
    entry_time: datetime
    entry_order_id: str
    status: str = "OPEN"  # OPEN, CLOSED


class OrderManager:
    """
    Quản lý toàn bộ vòng đời lệnh.
    Theo dõi giá để kích hoạt TP/SL cục bộ.
    """

    def __init__(
        self,
        connector: BinanceConnector,
        risk_manager: RiskManager,
        tp_pct: float = None,
        sl_pct: float = None,
    ):
        self.connector = connector
        self.risk_manager = risk_manager
        self.tp_pct = tp_pct or config.TP_PCT
        self.sl_pct = sl_pct or config.SL_PCT

        self.positions: Dict[str, LivePosition] = {}
        self._position_counter = 0

    @property
    def open_positions(self) -> List[LivePosition]:
        """Danh sách vị thế đang mở."""
        return [p for p in self.positions.values() if p.status == "OPEN"]

    async def open_position(
        self,
        symbol: str,
        current_price: float,
    ) -> Optional[LivePosition]:
        """
        Mở vị thế mới: tính kích thước, đặt lệnh MUA, tạo TP/SL cục bộ.

        Trả về LivePosition nếu thành công, None nếu thất bại.
        """
        # Kiểm tra rủi ro
        if not self.risk_manager.can_trade():
            return None

        # Tính mức TP/SL
        slippage_price = current_price * (1 + config.SLIPPAGE)
        tp_price = slippage_price * (1 + self.tp_pct)
        sl_price = slippage_price * (1 - self.sl_pct)

        # Tính kích thước lệnh
        quantity = self.risk_manager.calculate_position_size(
            entry_price=slippage_price,
            sl_price=sl_price,
        )

        if quantity <= 0:
            logger.warning("Kích thước lệnh = 0, bỏ qua tín hiệu")
            return None

        try:
            # Đặt lệnh MUA thị trường
            result = await self.connector.place_market_order(
                symbol=symbol,
                side="BUY",
                quantity=quantity,
            )

            # Lấy giá khớp thực tế
            fills = result.get("fills", [])
            if fills:
                total_qty = sum(float(f["qty"]) for f in fills)
                total_cost = sum(float(f["qty"]) * float(f["price"]) for f in fills)
                actual_price = total_cost / total_qty if total_qty > 0 else slippage_price
                actual_qty = total_qty
            else:
                actual_price = slippage_price
                actual_qty = float(result.get("executedQty", quantity))

            # Cập nhật TP/SL theo giá khớp thực tế
            tp_price = actual_price * (1 + self.tp_pct)
            sl_price = actual_price * (1 - self.sl_pct)

            # Tạo vị thế
            self._position_counter += 1
            pos_id = f"POS_{self._position_counter:04d}"

            position = LivePosition(
                position_id=pos_id,
                symbol=symbol,
                entry_price=actual_price,
                quantity=actual_qty,
                tp_price=tp_price,
                sl_price=sl_price,
                entry_time=datetime.now(timezone.utc),
                entry_order_id=str(result.get("orderId", "")),
            )

            self.positions[pos_id] = position
            self.risk_manager.trade_opened()

            logger.info(
                f"MỞ LỆNH {pos_id}: MUA {actual_qty:.8f} {symbol} "
                f"@ {actual_price:.4f} | TP={tp_price:.4f} | SL={sl_price:.4f}"
            )

            return position

        except Exception as e:
            logger.error(f"Lỗi mở lệnh: {e}")
            return None

    async def check_tp_sl(self, symbol: str, current_price: float):
        """
        Kiểm tra tất cả vị thế đang mở xem đã chạm TP hoặc SL chưa.
        Nếu chạm → đặt lệnh BÁN thị trường để đóng vị thế.
        """
        for position in self.open_positions:
            if position.symbol != symbol:
                continue

            should_close = False
            close_reason = ""

            if current_price >= position.tp_price:
                should_close = True
                close_reason = "TP"
            elif current_price <= position.sl_price:
                should_close = True
                close_reason = "SL"

            if should_close:
                await self._close_position(position, close_reason, current_price)

    async def _close_position(
        self,
        position: LivePosition,
        reason: str,
        current_price: float,
    ):
        """Đóng một vị thế bằng lệnh BÁN thị trường."""
        try:
            result = await self.connector.place_market_order(
                symbol=position.symbol,
                side="SELL",
                quantity=position.quantity,
            )

            # Tính lãi/lỗ
            fills = result.get("fills", [])
            if fills:
                total_qty = sum(float(f["qty"]) for f in fills)
                total_revenue = sum(
                    float(f["qty"]) * float(f["price"]) for f in fills
                )
                exit_price = total_revenue / total_qty if total_qty > 0 else current_price
            else:
                exit_price = current_price

            gross_pnl = (exit_price - position.entry_price) * position.quantity

            # Trừ phí ước tính
            entry_fee = position.entry_price * position.quantity * config.TRADING_FEE
            exit_fee = exit_price * position.quantity * config.TRADING_FEE
            net_pnl = gross_pnl - entry_fee - exit_fee

            position.status = "CLOSED"
            self.risk_manager.trade_closed()
            self.risk_manager.record_trade_pnl(net_pnl)

            # Cập nhật vốn
            new_equity = self.risk_manager.current_equity + net_pnl
            self.risk_manager.update_equity(new_equity)

            pnl_str = f"+{net_pnl:.2f}" if net_pnl >= 0 else f"{net_pnl:.2f}"
            logger.info(
                f"ĐÓNG LỆNH {position.position_id} ({reason}): "
                f"BÁN {position.quantity:.8f} {position.symbol} "
                f"@ {exit_price:.4f} | PnL: {pnl_str} USD"
            )

        except Exception as e:
            logger.error(
                f"Lỗi đóng lệnh {position.position_id}: {e}. "
                f"Vị thế vẫn mở — cần kiểm tra thủ công!"
            )

    async def close_all_positions(self, symbol: str, current_price: float):
        """Đóng tất cả vị thế đang mở (dùng khi tắt hệ thống)."""
        open_pos = [p for p in self.open_positions if p.symbol == symbol]
        if not open_pos:
            return

        logger.info(f"Đang đóng {len(open_pos)} vị thế trước khi tắt...")
        for position in open_pos:
            await self._close_position(position, "ĐÓNG_HỆ_THỐNG", current_price)

    def get_status(self) -> dict:
        """Trả về trạng thái tổng quan."""
        return {
            "tong_vi_the": len(self.positions),
            "vi_the_mo": len(self.open_positions),
            "vi_the_dong": len(self.positions) - len(self.open_positions),
        }
