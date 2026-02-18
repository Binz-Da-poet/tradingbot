"""
Tự động tải dữ liệu OHLCV từ Binance.

Hỗ trợ:
- Tải dữ liệu lịch sử bất kỳ cặp giao dịch nào
- Nhiều khung thời gian (1m, 5m, 15m, 1h, 4h, 1d)
- Tự động lưu CSV + cache (không tải lại nếu đã có)
- Không cần API key (dữ liệu công khai)
"""

import os
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from binance.client import Client


# Binance giới hạn 1000 nến mỗi request
MAX_CANDLES_PER_REQUEST = 1000

# Số mili-giây mỗi khung thời gian
INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}


def download_ohlcv(
    symbol: str = "BTCUSDT",
    interval: str = "1m",
    start_date: str = None,
    end_date: str = None,
    days_back: int = 30,
    save_dir: str = "data",
    force: bool = False,
) -> str:
    """
    Tải dữ liệu OHLCV từ Binance và lưu thành file CSV.

    Tham số:
        symbol: cặp giao dịch (VD: "BTCUSDT", "ETHUSDT")
        interval: khung thời gian ("1m", "5m", "15m", "1h", "4h", "1d")
        start_date: ngày bắt đầu "YYYY-MM-DD" (nếu None → tính từ days_back)
        end_date: ngày kết thúc "YYYY-MM-DD" (nếu None → hôm nay)
        days_back: số ngày lùi lại nếu không chỉ định start_date
        save_dir: thư mục lưu file CSV
        force: nếu True → tải lại dù file đã tồn tại

    Trả về:
        Đường dẫn file CSV đã lưu
    """
    # Xác định khoảng thời gian
    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    else:
        end_dt = datetime.utcnow()

    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    else:
        start_dt = end_dt - timedelta(days=days_back)

    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    # Tên file output
    filename = f"{symbol}_{interval}_{start_str}_{end_str}.csv"
    filepath = os.path.join(save_dir, filename)

    # Kiểm tra cache
    if os.path.isfile(filepath) and not force:
        df = pd.read_csv(filepath)
        print(f"  [Tải dữ liệu] Đã có sẵn: {filepath} ({len(df)} nến)")
        return filepath

    print(f"  [Tải dữ liệu] Đang tải {symbol} khung {interval}")
    print(f"  [Tải dữ liệu] Từ {start_str} đến {end_str}")

    # Kết nối Binance (không cần API key cho dữ liệu lịch sử)
    client = Client()

    # Tải dữ liệu theo từng batch
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    interval_ms = INTERVAL_MS.get(interval, 60_000)

    all_klines = []
    current_start = start_ms
    batch_count = 0

    while current_start < end_ms:
        try:
            klines = client.get_klines(
                symbol=symbol,
                interval=interval,
                startTime=current_start,
                endTime=end_ms,
                limit=MAX_CANDLES_PER_REQUEST,
            )
        except Exception as e:
            print(f"  [Tải dữ liệu] Lỗi kết nối: {e}")
            print(f"  [Tải dữ liệu] Chờ 5 giây rồi thử lại...")
            time.sleep(5)
            continue

        if not klines:
            break

        all_klines.extend(klines)
        batch_count += 1

        # Cập nhật vị trí bắt đầu cho batch tiếp theo
        last_open_time = klines[-1][0]
        current_start = last_open_time + interval_ms

        # Hiển thị tiến trình
        loaded_dt = datetime.utcfromtimestamp(last_open_time / 1000)
        total_expected = (end_ms - start_ms) / interval_ms
        loaded_count = len(all_klines)

        if batch_count % 5 == 0 or current_start >= end_ms:
            progress = min(100, (loaded_count / max(1, total_expected)) * 100)
            print(f"  [Tải dữ liệu] {loaded_count:,} nến ({progress:.0f}%) "
                  f"— đến {loaded_dt.strftime('%Y-%m-%d %H:%M')}")

        # Tránh vượt rate limit của Binance
        time.sleep(0.2)

    if not all_klines:
        print(f"  [Tải dữ liệu] Không có dữ liệu cho {symbol} trong khoảng thời gian này!")
        return ""

    # Chuyển thành DataFrame
    df = pd.DataFrame(all_klines, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore",
    ])

    # Giữ lại các cột cần thiết
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]

    # Chuyển sang float
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    # Loại bỏ trùng lặp
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    # Lưu file
    os.makedirs(save_dir, exist_ok=True)
    df.to_csv(filepath, index=False)

    print(f"  [Tải dữ liệu] Hoàn thành: {len(df):,} nến")
    print(f"  [Tải dữ liệu] Đã lưu tại: {filepath}")
    print(f"  [Tải dữ liệu] Khoảng giá: {df['low'].min():.2f} — {df['high'].max():.2f}")

    return filepath


def list_available_data(save_dir: str = "data") -> list:
    """Liệt kê các file dữ liệu đã tải."""
    if not os.path.isdir(save_dir):
        return []

    files = []
    for f in sorted(os.listdir(save_dir)):
        if f.endswith(".csv"):
            path = os.path.join(save_dir, f)
            size_mb = os.path.getsize(path) / (1024 * 1024)
            df = pd.read_csv(path, nrows=1)
            total_rows = sum(1 for _ in open(path)) - 1
            files.append({
                "file": f,
                "path": path,
                "size_mb": round(size_mb, 2),
                "rows": total_rows,
            })
    return files


def print_available_data(save_dir: str = "data"):
    """In danh sách dữ liệu đã tải."""
    files = list_available_data(save_dir)
    if not files:
        print("  Chưa có dữ liệu nào. Dùng --download để tải.")
        return

    print(f"\n  {'─' * 60}")
    print(f"  DỮ LIỆU ĐÃ TẢI ({save_dir}/)")
    print(f"  {'─' * 60}")
    print(f"  {'#':>3} {'File':<40} {'Nến':>10} {'MB':>6}")
    print(f"  {'─' * 60}")

    for i, f in enumerate(files, 1):
        print(f"  {i:>3} {f['file']:<40} {f['rows']:>10,} {f['size_mb']:>6.1f}")

    print(f"  {'─' * 60}")
