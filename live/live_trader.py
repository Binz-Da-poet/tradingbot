"""
Bộ giao dịch thực thời gian thực — phiên bản đồng bộ cho Streamlit.

Hoạt động:
1. Kết nối Binance REST API (đồng bộ)
2. Lấy nến gần nhất → tính chỉ báo → kiểm tra tín hiệu
3. Quản lý vị thế mở (TP/SL cục bộ)
4. Lưu trạng thái vào file JSON để duy trì qua các lần refresh
"""

import os
import json
import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from decimal import Decimal, ROUND_DOWN

import pandas as pd
import numpy as np
from binance.client import Client
from binance.exceptions import BinanceAPIException

import config
from core.data_handler import compute_indicators
from core.strategy import generate_signals

logger = logging.getLogger("GiaoDichThuc")

STATE_FILE = os.path.join(config.OUTPUT_DIR, "live_state.json")
TRADE_HISTORY_FILE = os.path.join(config.OUTPUT_DIR, "lich_su_giao_dich_thuc.csv")


class LiveTrader:
    """
    Bộ giao dịch thực đồng bộ.
    Mỗi lần gọi tick() → kiểm tra tín hiệu, quản lý vị thế.
    """

    MAX_RETRIES = 3

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        symbol: str = "BTCUSDT",
        ema_fast: int = None,
        ema_slow: int = None,
        tp_pct: float = None,
        sl_pct: float = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbol = symbol.upper()
        self.ema_fast = ema_fast or config.EMA_FAST
        self.ema_slow = ema_slow or config.EMA_SLOW
        self.tp_pct = tp_pct or config.TP_PCT
        self.sl_pct = sl_pct or config.SL_PCT

        self.client: Optional[Client] = None
        self.connected = False
        self.symbol_info: Dict = {}

        # Trạng thái giao dịch
        self.positions: List[Dict] = []
        self.trade_history: List[Dict] = []
        self.initial_equity = 0.0
        self.current_equity = 0.0
        self.peak_equity = 0.0
        self.daily_pnl = 0.0
        self.daily_date = None
        self.circuit_breaker = False
        self.last_signal = 0
        self.last_price = 0.0
        self.last_update = None
        self.logs: List[str] = []

        # Nạp trạng thái cũ nếu có
        self._load_state()

    def connect(self) -> bool:
        """Kết nối đến Binance."""
        try:
            self.client = Client(self.api_key, self.api_secret)
            self.client.ping()
            self._log("Đã kết nối thành công đến Binance.")

            # Lấy thông tin cặp giao dịch
            info = self.client.get_symbol_info(self.symbol)
            if info is None:
                self._log(f"LỖI: Không tìm thấy cặp giao dịch {self.symbol}")
                return False

            filters = {f["filterType"]: f for f in info["filters"]}
            self.symbol_info = {
                "base_asset": info["baseAsset"],
                "quote_asset": info["quoteAsset"],
                "step_size": filters.get("LOT_SIZE", {}).get("stepSize", "0.00000001"),
                "min_qty": float(filters.get("LOT_SIZE", {}).get("minQty", "0.00001")),
                "tick_size": filters.get("PRICE_FILTER", {}).get("tickSize", "0.01"),
                "min_notional": float(filters.get("NOTIONAL", {}).get("minNotional", "10")),
            }

            # Lấy số dư
            balance = self._get_balance("USDT")
            self._log(f"Số dư USDT: {balance:,.2f}")

            if self.initial_equity == 0:
                self.initial_equity = balance
            self.current_equity = balance
            self.peak_equity = max(self.peak_equity, balance)
            self.connected = True

            return True
        except Exception as e:
            self._log(f"LỖI kết nối: {e}")
            self.connected = False
            return False

    def tick(self) -> Dict:
        """
        Thực hiện một chu kỳ kiểm tra:
        1. Lấy giá hiện tại
        2. Kiểm tra TP/SL cho vị thế đang mở
        3. Lấy nến gần nhất → tính chỉ báo → kiểm tra tín hiệu
        4. Nếu có tín hiệu MUA → mở vị thế

        Trả về dict trạng thái hiện tại.
        """
        if not self.connected:
            return self._get_status("Chưa kết nối")

        try:
            # Cập nhật theo dõi hàng ngày
            self._update_daily_tracking()

            # Lấy giá hiện tại
            ticker = self.client.get_symbol_ticker(symbol=self.symbol)
            self.last_price = float(ticker["price"])
            self.last_update = datetime.now(timezone.utc)

            # Cập nhật equity
            self.current_equity = self._calculate_equity()
            self.peak_equity = max(self.peak_equity, self.current_equity)

            # Kiểm tra ngắt mạch
            self._check_circuit_breaker()

            # Kiểm tra TP/SL
            self._check_tp_sl()

            # Lấy nến và tính tín hiệu
            signal_info = self._check_signal()

            # Nếu có tín hiệu MUA → mở vị thế
            if signal_info.get("signal") == 1 and self._can_trade():
                self._open_position()

            self._save_state()
            return self._get_status("Đang hoạt động")

        except Exception as e:
            self._log(f"LỖI trong tick: {e}")
            return self._get_status(f"Lỗi: {e}")

    def _get_balance(self, asset: str = "USDT") -> float:
        """Lấy số dư khả dụng."""
        account = self.client.get_account()
        for b in account["balances"]:
            if b["asset"] == asset:
                return float(b["free"])
        return 0.0

    def _get_asset_balance(self, asset: str) -> float:
        """Lấy số dư một tài sản (cả free + locked)."""
        account = self.client.get_account()
        for b in account["balances"]:
            if b["asset"] == asset:
                return float(b["free"]) + float(b["locked"])
        return 0.0

    def _calculate_equity(self) -> float:
        """Tính tổng vốn = USDT + giá trị vị thế."""
        usdt = self._get_balance("USDT")
        position_value = sum(
            p["quantity"] * self.last_price for p in self.positions
        )
        return usdt + position_value

    def _check_signal(self) -> Dict:
        """Lấy nến gần nhất, tính chỉ báo, kiểm tra tín hiệu."""
        try:
            # Lấy 100 nến gần nhất
            klines = self.client.get_klines(
                symbol=self.symbol,
                interval=config.KLINE_INTERVAL,
                limit=100,
            )

            df = pd.DataFrame(klines, columns=[
                "timestamp", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades",
                "taker_buy_base", "taker_buy_quote", "ignore",
            ])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float)
            df = df[["timestamp", "open", "high", "low", "close", "volume"]]

            # Tính chỉ báo
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

            if len(df) == 0:
                return {"signal": 0}

            last = df.iloc[-1]
            self.last_signal = int(last.get("signal", 0))

            return {
                "signal": self.last_signal,
                "ema_fast": last.get("ema_fast", 0),
                "ema_slow": last.get("ema_slow", 0),
                "rsi": last.get("rsi", 0),
                "close": last.get("close", 0),
            }

        except Exception as e:
            self._log(f"Lỗi kiểm tra tín hiệu: {e}")
            return {"signal": 0}

    def _can_trade(self) -> bool:
        """Kiểm tra có được phép mở lệnh mới không."""
        if self.circuit_breaker:
            self._log("CHẶN: Ngắt mạch đang kích hoạt")
            return False

        if len(self.positions) >= config.MAX_OPEN_TRADES:
            return False

        # Kiểm tra lỗ hàng ngày
        if self.current_equity > 0:
            daily_loss_pct = abs(min(0, self.daily_pnl)) / self.current_equity
            if daily_loss_pct >= config.MAX_DAILY_LOSS:
                self._log("CHẶN: Vượt giới hạn lỗ hàng ngày")
                return False

        return True

    def _open_position(self):
        """Mở vị thế MUA thực tế trên Binance."""
        try:
            entry_price = self.last_price * (1 + config.SLIPPAGE)
            tp_price = entry_price * (1 + self.tp_pct)
            sl_price = entry_price * (1 - self.sl_pct)

            # Tính kích thước lệnh
            risk_amount = self.current_equity * config.RISK_PER_TRADE
            sl_distance = entry_price - sl_price
            if sl_distance <= 0:
                return

            quantity = risk_amount / sl_distance

            # Kiểm tra giá trị tối thiểu
            notional = quantity * self.last_price
            if notional < self.symbol_info.get("min_notional", 10):
                self._log(f"Giá trị lệnh quá nhỏ: {notional:.2f} < {self.symbol_info.get('min_notional', 10)}")
                return

            # Làm tròn số lượng
            quantity = self._adjust_quantity(quantity)
            if quantity <= 0:
                return

            # Đặt lệnh MUA thị trường
            self._log(f"ĐẶT LỆNH MUA: {quantity} {self.symbol} @ ~{self.last_price:.2f}")

            result = None
            for attempt in range(1, self.MAX_RETRIES + 1):
                try:
                    result = self.client.create_order(
                        symbol=self.symbol,
                        side="BUY",
                        type="MARKET",
                        quantity=quantity,
                    )
                    break
                except BinanceAPIException as e:
                    if e.code in (-2010, -1013, -1111):
                        self._log(f"Lỗi lệnh: {e.message}")
                        return
                    if attempt < self.MAX_RETRIES:
                        self._log(f"Thử lại lần {attempt + 1}...")
                        time.sleep(2 ** attempt)
                    else:
                        raise

            if not result:
                return

            # Lấy giá khớp thực tế
            fills = result.get("fills", [])
            if fills:
                total_qty = sum(float(f["qty"]) for f in fills)
                total_cost = sum(float(f["qty"]) * float(f["price"]) for f in fills)
                actual_price = total_cost / total_qty if total_qty > 0 else self.last_price
                actual_qty = total_qty
            else:
                actual_price = self.last_price
                actual_qty = float(result.get("executedQty", quantity))

            # Cập nhật TP/SL theo giá khớp thực
            tp_price = actual_price * (1 + self.tp_pct)
            sl_price = actual_price * (1 - self.sl_pct)

            position = {
                "id": f"POS_{len(self.trade_history) + len(self.positions) + 1:04d}",
                "symbol": self.symbol,
                "entry_price": actual_price,
                "quantity": actual_qty,
                "tp_price": tp_price,
                "sl_price": sl_price,
                "entry_time": datetime.now(timezone.utc).isoformat(),
                "order_id": str(result.get("orderId", "")),
            }
            self.positions.append(position)

            self._log(
                f"LỆNH ĐÃ KHỚP: MUA {actual_qty:.6f} {self.symbol} "
                f"@ {actual_price:.2f} | TP={tp_price:.2f} | SL={sl_price:.2f}"
            )

        except Exception as e:
            self._log(f"LỖI mở lệnh: {e}")

    def _check_tp_sl(self):
        """Kiểm tra các vị thế đang mở xem đã chạm TP/SL chưa."""
        closed = []
        for pos in self.positions:
            reason = None
            if self.last_price >= pos["tp_price"]:
                reason = "TP"
            elif self.last_price <= pos["sl_price"]:
                reason = "SL"

            if reason:
                self._close_position(pos, reason)
                closed.append(pos)

        for pos in closed:
            self.positions.remove(pos)

    def _close_position(self, pos: Dict, reason: str):
        """Đóng vị thế bằng lệnh BÁN thị trường."""
        try:
            quantity = self._adjust_quantity(pos["quantity"])
            if quantity <= 0:
                return

            self._log(f"ĐÓNG LỆNH ({reason}): BÁN {quantity} {self.symbol}")

            result = None
            for attempt in range(1, self.MAX_RETRIES + 1):
                try:
                    result = self.client.create_order(
                        symbol=self.symbol,
                        side="SELL",
                        type="MARKET",
                        quantity=quantity,
                    )
                    break
                except BinanceAPIException as e:
                    if attempt < self.MAX_RETRIES:
                        time.sleep(2 ** attempt)
                    else:
                        self._log(f"LỖI đóng lệnh: {e.message} — CẦN ĐÓNG THỦ CÔNG!")
                        return

            if not result:
                return

            # Tính lãi/lỗ
            fills = result.get("fills", [])
            if fills:
                total_qty = sum(float(f["qty"]) for f in fills)
                total_revenue = sum(float(f["qty"]) * float(f["price"]) for f in fills)
                exit_price = total_revenue / total_qty if total_qty > 0 else self.last_price
            else:
                exit_price = self.last_price

            gross_pnl = (exit_price - pos["entry_price"]) * pos["quantity"]
            entry_fee = pos["entry_price"] * pos["quantity"] * config.TRADING_FEE
            exit_fee = exit_price * pos["quantity"] * config.TRADING_FEE
            net_pnl = gross_pnl - entry_fee - exit_fee

            self.daily_pnl += net_pnl

            trade = {
                "id": pos["id"],
                "symbol": self.symbol,
                "entry_time": pos["entry_time"],
                "exit_time": datetime.now(timezone.utc).isoformat(),
                "entry_price": round(pos["entry_price"], 4),
                "exit_price": round(exit_price, 4),
                "quantity": round(pos["quantity"], 8),
                "reason": reason,
                "pnl": round(net_pnl, 4),
                "pnl_pct": round((net_pnl / (pos["entry_price"] * pos["quantity"])) * 100, 2),
                "fee": round(entry_fee + exit_fee, 4),
            }
            self.trade_history.append(trade)
            self._save_trade_history()

            sign = "+" if net_pnl >= 0 else ""
            self._log(
                f"ĐÓNG {pos['id']} ({reason}): {exit_price:.2f} | "
                f"PnL: {sign}{net_pnl:.2f} USD ({sign}{trade['pnl_pct']:.2f}%)"
            )

        except Exception as e:
            self._log(f"LỖI đóng lệnh {pos['id']}: {e}")

    def close_all(self):
        """Đóng tất cả vị thế đang mở."""
        if not self.positions:
            self._log("Không có vị thế nào để đóng.")
            return

        self._log(f"Đang đóng {len(self.positions)} vị thế...")
        for pos in self.positions[:]:
            self._close_position(pos, "ĐÓNG_THỦ_CÔNG")
        self.positions.clear()
        self._save_state()

    def _check_circuit_breaker(self):
        """Kiểm tra ngắt mạch."""
        if self.peak_equity <= 0:
            return
        dd = (self.peak_equity - self.current_equity) / self.peak_equity
        if dd >= config.CIRCUIT_BREAKER_DD and not self.circuit_breaker:
            self.circuit_breaker = True
            self._log(f"NGẮT MẠCH! Drawdown = {dd*100:.1f}% >= {config.CIRCUIT_BREAKER_DD*100}%")

    def _update_daily_tracking(self):
        """Reset lãi/lỗ khi sang ngày mới."""
        today = datetime.now(timezone.utc).date().isoformat()
        if self.daily_date != today:
            if self.daily_date:
                self._log(f"Sang ngày mới. PnL hôm qua: {self.daily_pnl:+.2f} USD")
            self.daily_date = today
            self.daily_pnl = 0.0

    def _adjust_quantity(self, quantity: float) -> float:
        """Làm tròn số lượng theo bước cho phép của Binance."""
        step = self.symbol_info.get("step_size", "0.00000001")
        qty = Decimal(str(quantity)).quantize(Decimal(step), rounding=ROUND_DOWN)
        return float(qty)

    def _get_status(self, status_text: str) -> Dict:
        """Trả về trạng thái hiện tại."""
        dd = 0.0
        if self.peak_equity > 0:
            dd = (self.peak_equity - self.current_equity) / self.peak_equity

        total_pnl = 0.0
        if self.initial_equity > 0:
            total_pnl = ((self.current_equity - self.initial_equity) / self.initial_equity) * 100

        return {
            "status": status_text,
            "connected": self.connected,
            "symbol": self.symbol,
            "last_price": self.last_price,
            "last_signal": self.last_signal,
            "last_update": self.last_update.strftime("%H:%M:%S") if self.last_update else "—",
            "initial_equity": round(self.initial_equity, 2),
            "current_equity": round(self.current_equity, 2),
            "peak_equity": round(self.peak_equity, 2),
            "total_pnl_pct": round(total_pnl, 2),
            "drawdown_pct": round(dd * 100, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "open_positions": len(self.positions),
            "total_trades": len(self.trade_history),
            "circuit_breaker": self.circuit_breaker,
            "positions": self.positions.copy(),
            "logs": self.logs[-30:],
        }

    def _log(self, message: str):
        """Thêm log với thời gian."""
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {message}"
        self.logs.append(entry)
        if len(self.logs) > 200:
            self.logs = self.logs[-100:]
        logger.info(message)

    def _save_state(self):
        """Lưu trạng thái ra file JSON."""
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        state = {
            "positions": self.positions,
            "initial_equity": self.initial_equity,
            "peak_equity": self.peak_equity,
            "daily_pnl": self.daily_pnl,
            "daily_date": self.daily_date,
            "circuit_breaker": self.circuit_breaker,
            "trade_count": len(self.trade_history),
        }
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_state(self):
        """Nạp trạng thái từ file JSON."""
        if not os.path.isfile(STATE_FILE):
            return
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            self.positions = state.get("positions", [])
            self.initial_equity = state.get("initial_equity", 0)
            self.peak_equity = state.get("peak_equity", 0)
            self.daily_pnl = state.get("daily_pnl", 0)
            self.daily_date = state.get("daily_date")
            self.circuit_breaker = state.get("circuit_breaker", False)
            if self.positions:
                self._log(f"Đã nạp {len(self.positions)} vị thế từ phiên trước.")
        except Exception:
            pass

    def _save_trade_history(self):
        """Lưu lịch sử giao dịch ra CSV."""
        if not self.trade_history:
            return
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        df = pd.DataFrame(self.trade_history)
        df.to_csv(TRADE_HISTORY_FILE, index=False, encoding="utf-8-sig")

    def reset_state(self):
        """Reset toàn bộ trạng thái (xóa vị thế, lịch sử phiên)."""
        self.positions = []
        self.daily_pnl = 0.0
        self.circuit_breaker = False
        self.initial_equity = 0.0
        self.peak_equity = 0.0
        self.logs = []
        if os.path.isfile(STATE_FILE):
            os.remove(STATE_FILE)
        self._log("Đã reset trạng thái.")
