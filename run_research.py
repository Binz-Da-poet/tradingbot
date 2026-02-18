"""
Điểm vào chế độ nghiên cứu (Backtest & Tối ưu tham số).

Cách sử dụng:
    # Tự động tải dữ liệu + backtest
    python run_research.py --download

    # Tải dữ liệu cụ thể + backtest
    python run_research.py --download --symbol ETHUSDT --days 60

    # Tải + tối ưu tham số
    python run_research.py --download --optimize

    # Dùng file CSV có sẵn
    python run_research.py --csv data/BTCUSDT_1m.csv

    # Liệt kê dữ liệu đã tải
    python run_research.py --list
"""

import os
import sys
import argparse
import time

import config
from core.data_handler import load_csv, compute_indicators
from core.data_downloader import download_ohlcv, print_available_data
from core.strategy import generate_signals
from core.backtester import Backtester, BacktestParams
from core.metrics import (
    calculate_metrics,
    print_summary,
    plot_equity_curve,
    export_trade_log,
)
from optimizer.grid_search import run_grid_search


def run_backtest(
    csv_path: str,
    ema_fast: int = None,
    ema_slow: int = None,
    tp_pct: float = None,
    sl_pct: float = None,
):
    """Chạy backtest với tham số cho trước hoặc mặc định."""
    ema_fast = ema_fast or config.EMA_FAST
    ema_slow = ema_slow or config.EMA_SLOW
    tp_pct = tp_pct or config.TP_PCT
    sl_pct = sl_pct or config.SL_PCT

    print("╔" + "═" * 48 + "╗")
    print("║    HỆ THỐNG GIAO DỊCH CRYPTO - CHẾ ĐỘ NGHIÊN CỨU   ║")
    print("╚" + "═" * 48 + "╝")
    print()

    # Bước 1: Nạp dữ liệu
    print("▶ Bước 1: Nạp dữ liệu")
    df = load_csv(csv_path)

    # Bước 2: Tính chỉ báo kỹ thuật
    print("\n▶ Bước 2: Tính chỉ báo kỹ thuật")
    print(f"  EMA nhanh = {ema_fast}, EMA chậm = {ema_slow}")
    df = compute_indicators(df, ema_fast=ema_fast, ema_slow=ema_slow, rsi_period=config.RSI_PERIOD)

    # Bước 3: Tạo tín hiệu giao dịch
    print("\n▶ Bước 3: Tạo tín hiệu giao dịch")
    df = generate_signals(df, rsi_threshold=config.RSI_THRESHOLD, use_rsi_filter=config.USE_RSI_FILTER)

    # Bước 4: Chạy mô phỏng
    print("\n▶ Bước 4: Chạy mô phỏng")
    params = BacktestParams(
        initial_capital=config.INITIAL_CAPITAL,
        trading_fee=config.TRADING_FEE,
        slippage=config.SLIPPAGE,
        risk_per_trade=config.RISK_PER_TRADE,
        max_daily_loss=config.MAX_DAILY_LOSS,
        max_open_trades=config.MAX_OPEN_TRADES,
        circuit_breaker_dd=config.CIRCUIT_BREAKER_DD,
        tp_pct=tp_pct,
        sl_pct=sl_pct,
    )

    bt = Backtester(params)
    start_time = time.time()
    trade_log, equity_curve = bt.run(df)
    elapsed = time.time() - start_time
    print(f"  [Backtest] Thời gian chạy: {elapsed:.2f} giây")

    # Bước 5: Phân tích hiệu suất
    print("\n▶ Bước 5: Phân tích hiệu suất")
    metrics = calculate_metrics(trade_log, equity_curve, config.INITIAL_CAPITAL)
    print_summary(metrics)

    # Bước 6: Lưu kết quả
    print("▶ Bước 6: Lưu kết quả")
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    trade_log_path = os.path.join(config.OUTPUT_DIR, config.TRADE_LOG_FILE)
    export_trade_log(trade_log, trade_log_path)

    equity_path = os.path.join(config.OUTPUT_DIR, config.EQUITY_CURVE_FILE)
    plot_equity_curve(equity_curve, equity_path)

    print("\n✓ Hoàn thành nghiên cứu!")
    return metrics


def run_optimize_and_backtest(csv_path: str):
    """Chạy tối ưu tham số rồi backtest với tham số tốt nhất."""
    print("╔" + "═" * 48 + "╗")
    print("║  HỆ THỐNG GIAO DỊCH - TỐI ƯU + NGHIÊN CỨU  ║")
    print("╚" + "═" * 48 + "╝")
    print()

    # Bước 1: Nạp dữ liệu gốc
    print("▶ Bước 1: Nạp dữ liệu gốc")
    base_df = load_csv(csv_path)

    # Bước 2: Chạy Grid Search
    print("\n▶ Bước 2: Tối ưu tham số")
    start_time = time.time()
    best_params, results_df = run_grid_search(
        base_df=base_df,
        initial_capital=config.INITIAL_CAPITAL,
    )
    elapsed = time.time() - start_time
    print(f"  Thời gian tối ưu: {elapsed:.1f} giây")

    if not best_params:
        print("  [Lỗi] Không tìm được tham số tốt nhất. Kết thúc.")
        return

    # Lưu bảng kết quả tối ưu
    if not results_df.empty:
        opt_path = os.path.join(config.OUTPUT_DIR, "ket_qua_toi_uu.csv")
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        results_df.to_csv(opt_path, index=False, encoding="utf-8-sig")
        print(f"  [Tối ưu] Đã lưu bảng kết quả tại: {opt_path}")

    # Bước 3: Backtest với tham số tốt nhất
    print(f"\n▶ Bước 3: Backtest với tham số tốt nhất")
    metrics = run_backtest(
        csv_path=csv_path,
        ema_fast=best_params["ema_fast"],
        ema_slow=best_params["ema_slow"],
        tp_pct=best_params["tp_pct"],
        sl_pct=best_params["sl_pct"],
    )

    return metrics


def main():
    parser = argparse.ArgumentParser(
        description="Hệ thống giao dịch Crypto - Chế độ nghiên cứu",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ:
  # Tự động tải BTCUSDT 30 ngày + backtest
  python run_research.py --download

  # Tải ETHUSDT 60 ngày + tối ưu tham số
  python run_research.py --download --symbol ETHUSDT --days 60 --optimize

  # Tải dữ liệu theo khoảng thời gian cụ thể
  python run_research.py --download --symbol BTCUSDT --start 2024-01-01 --end 2024-06-30

  # Dùng file CSV có sẵn
  python run_research.py --csv data/BTCUSDT_1m.csv

  # Liệt kê dữ liệu đã tải
  python run_research.py --list
        """,
    )

    # Nguồn dữ liệu
    data_group = parser.add_argument_group("Nguồn dữ liệu")
    data_group.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Đường dẫn file OHLCV CSV có sẵn",
    )
    data_group.add_argument(
        "--download",
        action="store_true",
        default=False,
        help="Tự động tải dữ liệu từ Binance",
    )
    data_group.add_argument(
        "--list",
        action="store_true",
        default=False,
        help="Liệt kê các file dữ liệu đã tải",
    )

    # Tham số tải dữ liệu
    dl_group = parser.add_argument_group("Tham số tải dữ liệu (dùng với --download)")
    dl_group.add_argument(
        "--symbol",
        type=str,
        default=config.DEFAULT_SYMBOL,
        help=f"Cặp giao dịch (mặc định: {config.DEFAULT_SYMBOL})",
    )
    dl_group.add_argument(
        "--interval",
        type=str,
        default=config.DEFAULT_INTERVAL,
        choices=["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"],
        help=f"Khung thời gian (mặc định: {config.DEFAULT_INTERVAL})",
    )
    dl_group.add_argument(
        "--days",
        type=int,
        default=config.DEFAULT_DAYS_BACK,
        help=f"Số ngày dữ liệu (mặc định: {config.DEFAULT_DAYS_BACK})",
    )
    dl_group.add_argument(
        "--start",
        type=str,
        default=None,
        help="Ngày bắt đầu YYYY-MM-DD (thay thế --days)",
    )
    dl_group.add_argument(
        "--end",
        type=str,
        default=None,
        help="Ngày kết thúc YYYY-MM-DD (mặc định: hôm nay)",
    )
    dl_group.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Tải lại dù file đã tồn tại",
    )

    # Chế độ chạy
    run_group = parser.add_argument_group("Chế độ chạy")
    run_group.add_argument(
        "--optimize",
        action="store_true",
        default=False,
        help="Tối ưu tham số bằng Grid Search trước khi backtest",
    )

    args = parser.parse_args()

    # Liệt kê dữ liệu
    if args.list:
        print_available_data(config.DATA_DIR)
        return

    # Xác định file CSV
    csv_path = args.csv

    if args.download:
        # Tải dữ liệu tự động
        print("╔" + "═" * 48 + "╗")
        print("║        TẢI DỮ LIỆU TỪ BINANCE               ║")
        print("╚" + "═" * 48 + "╝")
        print()

        csv_path = download_ohlcv(
            symbol=args.symbol.upper(),
            interval=args.interval,
            start_date=args.start,
            end_date=args.end,
            days_back=args.days,
            save_dir=config.DATA_DIR,
            force=args.force,
        )

        if not csv_path:
            print("[Lỗi] Không tải được dữ liệu. Kết thúc.")
            sys.exit(1)

        print()

    # Kiểm tra file CSV
    if csv_path is None:
        # Nếu không chỉ định gì → tự động tải mặc định
        print("Không chỉ định nguồn dữ liệu. Tự động tải BTCUSDT 30 ngày...\n")
        csv_path = download_ohlcv(
            symbol=config.DEFAULT_SYMBOL,
            interval=config.DEFAULT_INTERVAL,
            days_back=config.DEFAULT_DAYS_BACK,
            save_dir=config.DATA_DIR,
        )
        if not csv_path:
            print("[Lỗi] Không tải được dữ liệu. Kết thúc.")
            sys.exit(1)
        print()

    if not os.path.isfile(csv_path):
        print(f"[Lỗi] Không tìm thấy file: {csv_path}")
        sys.exit(1)

    # Chạy backtest hoặc tối ưu
    if args.optimize:
        run_optimize_and_backtest(csv_path)
    else:
        run_backtest(csv_path)


if __name__ == "__main__":
    main()
