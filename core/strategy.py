"""
Chiến lược giao dịch: EMA Crossover với bộ lọc RSI tùy chọn.

Quy tắc:
- Tín hiệu MUA: EMA nhanh cắt lên EMA chậm
- Bộ lọc RSI (tùy chọn): chỉ mua khi RSI < ngưỡng
- Chỉ giao dịch LONG (mua), không short
- Thoát lệnh do backtester quản lý (TP/SL)
"""

import pandas as pd
import numpy as np


def generate_signals(
    df: pd.DataFrame,
    rsi_threshold: float = 60,
    use_rsi_filter: bool = True,
) -> pd.DataFrame:
    """
    Tạo tín hiệu giao dịch dựa trên EMA crossover.

    Tham số:
        df: DataFrame chứa cột ema_fast, ema_slow, rsi
        rsi_threshold: ngưỡng RSI tối đa để cho phép vào lệnh
        use_rsi_filter: bật/tắt bộ lọc RSI

    Trả về:
        DataFrame với cột 'signal' (1 = MUA, 0 = không có tín hiệu)
    """
    df = df.copy()

    # Phát hiện giao cắt: EMA nhanh cắt lên EMA chậm
    # Nến trước: EMA nhanh <= EMA chậm
    # Nến hiện tại: EMA nhanh > EMA chậm
    ema_fast_prev = df["ema_fast"].shift(1)
    ema_slow_prev = df["ema_slow"].shift(1)

    crossover = (ema_fast_prev <= ema_slow_prev) & (df["ema_fast"] > df["ema_slow"])

    if use_rsi_filter:
        # Chỉ mua khi RSI chưa quá mua (< ngưỡng)
        rsi_ok = df["rsi"] < rsi_threshold
        df["signal"] = np.where(crossover & rsi_ok, 1, 0)
    else:
        df["signal"] = np.where(crossover, 1, 0)

    # Dòng đầu tiên không có dữ liệu shift → bỏ tín hiệu
    df.loc[0, "signal"] = 0

    total_signals = df["signal"].sum()
    print(f"  [Chiến lược] Tìm thấy {total_signals} tín hiệu MUA"
          f" (bộ lọc RSI: {'BẬT' if use_rsi_filter else 'TẮT'})")

    return df
