"""
Xử lý dữ liệu: nạp file OHLCV CSV và tính toán chỉ báo kỹ thuật.
"""

import pandas as pd
import numpy as np
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator


def load_csv(file_path: str) -> pd.DataFrame:
    """
    Đọc file OHLCV CSV, parse timestamp, sắp xếp theo thời gian.

    Yêu cầu cột: timestamp (hoặc date/datetime), open, high, low, close, volume
    Trả về DataFrame đã được chuẩn hóa.
    """
    df = pd.read_csv(file_path)

    # Chuẩn hóa tên cột thành chữ thường
    df.columns = [c.strip().lower() for c in df.columns]

    # Tìm cột thời gian
    time_col = None
    for candidate in ["timestamp", "datetime", "date", "time"]:
        if candidate in df.columns:
            time_col = candidate
            break

    if time_col is None:
        raise ValueError(
            "Không tìm thấy cột thời gian. "
            "File CSV cần có cột: timestamp, datetime, hoặc date."
        )

    df[time_col] = pd.to_datetime(df[time_col])
    df = df.rename(columns={time_col: "timestamp"})
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Kiểm tra các cột OHLCV bắt buộc
    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Thiếu các cột bắt buộc: {missing}")

    # Chuyển kiểu dữ liệu sang float
    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Xử lý giá trị thiếu
    rows_before = len(df)
    df = df.dropna(subset=required)
    rows_dropped = rows_before - len(df)
    if rows_dropped > 0:
        print(f"  [Dữ liệu] Đã loại bỏ {rows_dropped} dòng có giá trị thiếu.")

    df = df.reset_index(drop=True)
    print(f"  [Dữ liệu] Đã nạp {len(df)} nến từ {df['timestamp'].iloc[0]} "
          f"đến {df['timestamp'].iloc[-1]}")

    return df


def compute_indicators(
    df: pd.DataFrame,
    ema_fast: int = 9,
    ema_slow: int = 21,
    rsi_period: int = 14,
) -> pd.DataFrame:
    """
    Tính chỉ báo kỹ thuật EMA nhanh, EMA chậm, RSI và thêm vào DataFrame.

    Các dòng đầu chưa đủ dữ liệu tính chỉ báo sẽ bị loại bỏ (NaN).
    """
    df = df.copy()

    # Tính EMA nhanh
    ema_fast_indicator = EMAIndicator(close=df["close"], window=ema_fast)
    df["ema_fast"] = ema_fast_indicator.ema_indicator()

    # Tính EMA chậm
    ema_slow_indicator = EMAIndicator(close=df["close"], window=ema_slow)
    df["ema_slow"] = ema_slow_indicator.ema_indicator()

    # Tính RSI
    rsi_indicator = RSIIndicator(close=df["close"], window=rsi_period)
    df["rsi"] = rsi_indicator.rsi()

    # Loại bỏ các dòng NaN do chỉ báo chưa đủ dữ liệu
    rows_before = len(df)
    df = df.dropna(subset=["ema_fast", "ema_slow", "rsi"]).reset_index(drop=True)
    rows_dropped = rows_before - len(df)
    if rows_dropped > 0:
        print(f"  [Chỉ báo] Đã loại bỏ {rows_dropped} dòng đầu (khởi tạo chỉ báo).")

    return df
