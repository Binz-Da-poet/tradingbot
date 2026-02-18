"""
Bộ mô phỏng giao dịch (Backtester).

Duyệt từng nến một để mô phỏng thực tế:
- Kiểm tra TP/SL dựa trên high/low của nến
- Áp dụng phí giao dịch và trượt giá
- Tuân thủ quản lý rủi ro (giới hạn lệnh, lỗ hàng ngày, ngắt mạch)
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple


@dataclass
class Position:
    """Đại diện cho một vị thế đang mở."""
    entry_time: pd.Timestamp
    entry_price: float      # Giá vào lệnh (đã tính trượt giá)
    quantity: float          # Số lượng coin
    tp_price: float          # Mức chốt lời
    sl_price: float          # Mức cắt lỗ
    entry_fee: float         # Phí vào lệnh


@dataclass
class Trade:
    """Kết quả một lệnh giao dịch đã hoàn thành."""
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    quantity: float
    side: str                # "TP" hoặc "SL"
    pnl: float               # Lãi/lỗ sau phí
    pnl_pct: float            # Lãi/lỗ phần trăm
    total_fee: float          # Tổng phí (vào + ra)


@dataclass
class BacktestParams:
    """Tham số cho bộ mô phỏng."""
    initial_capital: float = 10_000.0
    trading_fee: float = 0.001
    slippage: float = 0.0005
    risk_per_trade: float = 0.01
    max_daily_loss: float = 0.03
    max_open_trades: int = 3
    circuit_breaker_dd: float = 0.10
    tp_pct: float = 0.003
    sl_pct: float = 0.003


class Backtester:
    """
    Bộ mô phỏng giao dịch theo từng nến.
    Ưu tiên mô phỏng thực tế hơn tốc độ.
    """

    def __init__(self, params: BacktestParams = None):
        self.params = params or BacktestParams()
        self._reset()

    def _reset(self):
        """Khởi tạo lại trạng thái mô phỏng."""
        self.cash = self.params.initial_capital
        self.equity = self.params.initial_capital
        self.peak_equity = self.params.initial_capital
        self.positions: List[Position] = []
        self.trades: List[Trade] = []
        self.equity_curve: List[Dict] = []
        self.circuit_breaker_active = False

        # Theo dõi lãi/lỗ hàng ngày
        self._current_date: Optional[pd.Timestamp] = None
        self._daily_pnl: float = 0.0

    def run(self, df: pd.DataFrame, silent: bool = False) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Chạy mô phỏng trên toàn bộ dữ liệu.

        Tham số:
            df: DataFrame có cột signal, open, high, low, close, timestamp
            silent: nếu True thì không in thông báo

        Trả về:
            (nhật_ký_giao_dịch: DataFrame, đường_vốn: DataFrame)
        """
        self._reset()

        if not silent:
            print(f"  [Backtest] Bắt đầu mô phỏng với vốn {self.params.initial_capital:,.0f} USD")
            print(f"  [Backtest] Phí: {self.params.trading_fee*100}% | "
                  f"Trượt giá: {self.params.slippage*100}% | "
                  f"TP: {self.params.tp_pct*100}% | SL: {self.params.sl_pct*100}%")

        for i in range(len(df)):
            row = df.iloc[i]
            current_time = row["timestamp"]

            # Cập nhật theo dõi lãi/lỗ hàng ngày
            self._update_daily_tracking(current_time)

            # Bước 1: Kiểm tra các vị thế đang mở xem có chạm TP/SL không
            self._check_exits(row)

            # Bước 2: Kiểm tra ngắt mạch
            self._check_circuit_breaker()

            # Bước 3: Nếu có tín hiệu MUA → mở vị thế mới
            if row.get("signal", 0) == 1:
                self._try_open_position(row)

            # Bước 4: Tính equity hiện tại và ghi lại
            self._update_equity(row)
            self.equity_curve.append({
                "timestamp": current_time,
                "equity": self.equity,
            })

        # Đóng tất cả vị thế còn lại ở nến cuối cùng
        if len(df) > 0:
            self._close_all_positions(df.iloc[-1])

        if not silent:
            print(f"  [Backtest] Hoàn thành: {len(self.trades)} lệnh, "
                  f"vốn cuối {self.equity:,.2f} USD")

        trade_log = self._build_trade_log()
        equity_df = pd.DataFrame(self.equity_curve)

        return trade_log, equity_df

    def _update_daily_tracking(self, current_time: pd.Timestamp):
        """Reset theo dõi lãi/lỗ khi sang ngày mới."""
        current_date = current_time.date()
        if self._current_date is None or current_date != self._current_date:
            self._current_date = current_date
            self._daily_pnl = 0.0

    def _check_exits(self, row: pd.Series):
        """Kiểm tra các vị thế đang mở xem đã chạm TP hoặc SL chưa."""
        closed_indices = []

        for idx, pos in enumerate(self.positions):
            exit_price = None
            exit_side = None

            # Kiểm tra SL trước (giả định SL xảy ra trước TP trong cùng nến)
            if row["low"] <= pos.sl_price:
                exit_price = pos.sl_price
                exit_side = "SL"
            elif row["high"] >= pos.tp_price:
                exit_price = pos.tp_price
                exit_side = "TP"

            if exit_price is not None:
                # Áp dụng trượt giá khi thoát (bất lợi cho trader)
                if exit_side == "TP":
                    exit_price *= (1 - self.params.slippage)
                else:
                    exit_price *= (1 - self.params.slippage)

                exit_fee = exit_price * pos.quantity * self.params.trading_fee
                gross_pnl = (exit_price - pos.entry_price) * pos.quantity
                net_pnl = gross_pnl - pos.entry_fee - exit_fee

                trade = Trade(
                    entry_time=pos.entry_time,
                    exit_time=row["timestamp"],
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    quantity=pos.quantity,
                    side=exit_side,
                    pnl=net_pnl,
                    pnl_pct=(net_pnl / (pos.entry_price * pos.quantity)) * 100,
                    total_fee=pos.entry_fee + exit_fee,
                )
                self.trades.append(trade)
                self.cash += exit_price * pos.quantity - exit_fee
                self._daily_pnl += net_pnl
                closed_indices.append(idx)

        # Xóa các vị thế đã đóng (từ cuối lên để không lệch index)
        for idx in sorted(closed_indices, reverse=True):
            self.positions.pop(idx)

    def _check_circuit_breaker(self):
        """Kích hoạt ngắt mạch nếu drawdown vượt ngưỡng."""
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - self.equity) / self.peak_equity
            if drawdown >= self.params.circuit_breaker_dd:
                if not self.circuit_breaker_active:
                    self.circuit_breaker_active = True

    def _can_open_trade(self) -> bool:
        """Kiểm tra xem có được phép mở lệnh mới không."""
        if self.circuit_breaker_active:
            return False

        if len(self.positions) >= self.params.max_open_trades:
            return False

        # Kiểm tra lỗ hàng ngày
        if self.equity > 0:
            daily_loss_pct = abs(min(0, self._daily_pnl)) / self.equity
            if daily_loss_pct >= self.params.max_daily_loss:
                return False

        return True

    def _try_open_position(self, row: pd.Series):
        """Thử mở vị thế mới nếu đủ điều kiện."""
        if not self._can_open_trade():
            return

        # Giá vào lệnh = giá đóng cửa + trượt giá (bất lợi: mua cao hơn)
        entry_price = row["close"] * (1 + self.params.slippage)

        # Tính mức TP và SL
        tp_price = entry_price * (1 + self.params.tp_pct)
        sl_price = entry_price * (1 - self.params.sl_pct)

        # Tính kích thước lệnh dựa trên rủi ro
        # risk_amount = vốn hiện tại * % rủi ro mỗi lệnh
        risk_amount = self.equity * self.params.risk_per_trade
        sl_distance = entry_price - sl_price

        if sl_distance <= 0:
            return

        quantity = risk_amount / sl_distance

        # Kiểm tra đủ tiền không
        cost = entry_price * quantity
        entry_fee = cost * self.params.trading_fee
        total_cost = cost + entry_fee

        if total_cost > self.cash:
            # Giảm kích thước lệnh cho vừa số tiền còn lại
            quantity = self.cash / (entry_price * (1 + self.params.trading_fee))
            if quantity <= 0:
                return
            cost = entry_price * quantity
            entry_fee = cost * self.params.trading_fee
            total_cost = cost + entry_fee

        self.cash -= total_cost

        pos = Position(
            entry_time=row["timestamp"],
            entry_price=entry_price,
            quantity=quantity,
            tp_price=tp_price,
            sl_price=sl_price,
            entry_fee=entry_fee,
        )
        self.positions.append(pos)

    def _update_equity(self, row: pd.Series):
        """Cập nhật vốn hiện tại (tiền mặt + giá trị vị thế)."""
        position_value = sum(
            pos.quantity * row["close"] for pos in self.positions
        )
        self.equity = self.cash + position_value
        self.peak_equity = max(self.peak_equity, self.equity)

    def _close_all_positions(self, row: pd.Series):
        """Đóng tất cả vị thế còn lại ở nến cuối cùng."""
        for pos in self.positions[:]:
            exit_price = row["close"] * (1 - self.params.slippage)
            exit_fee = exit_price * pos.quantity * self.params.trading_fee
            gross_pnl = (exit_price - pos.entry_price) * pos.quantity
            net_pnl = gross_pnl - pos.entry_fee - exit_fee

            trade = Trade(
                entry_time=pos.entry_time,
                exit_time=row["timestamp"],
                entry_price=pos.entry_price,
                exit_price=exit_price,
                quantity=pos.quantity,
                side="ĐÓNG",
                pnl=net_pnl,
                pnl_pct=(net_pnl / (pos.entry_price * pos.quantity)) * 100,
                total_fee=pos.entry_fee + exit_fee,
            )
            self.trades.append(trade)
            self.cash += exit_price * pos.quantity - exit_fee

        self.positions.clear()
        self.equity = self.cash

    def _build_trade_log(self) -> pd.DataFrame:
        """Tạo DataFrame nhật ký giao dịch."""
        if not self.trades:
            return pd.DataFrame(columns=[
                "thoi_gian_vao", "thoi_gian_ra", "gia_vao", "gia_ra",
                "so_luong", "loai_thoat", "lai_lo", "lai_lo_pct", "phi"
            ])

        records = []
        for t in self.trades:
            records.append({
                "thoi_gian_vao": t.entry_time,
                "thoi_gian_ra": t.exit_time,
                "gia_vao": round(t.entry_price, 4),
                "gia_ra": round(t.exit_price, 4),
                "so_luong": round(t.quantity, 8),
                "loai_thoat": t.side,
                "lai_lo": round(t.pnl, 4),
                "lai_lo_pct": round(t.pnl_pct, 4),
                "phi": round(t.total_fee, 4),
            })

        return pd.DataFrame(records)
