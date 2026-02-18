"""
Điểm vào chế độ giao dịch thực.

Yêu cầu:
- Biến môi trường: BINANCE_API_KEY, BINANCE_API_SECRET
- Kết nối internet ổn định

Cách sử dụng:
    python run_live.py --symbol BTCUSDT

CẢNH BÁO: Chế độ này giao dịch bằng tiền thật!
Hãy kiểm tra kỹ cấu hình rủi ro trước khi chạy.
"""

import os
import sys
import asyncio
import argparse


def main():
    parser = argparse.ArgumentParser(
        description="Hệ thống giao dịch Crypto - Chế độ THỰC",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
CẢNH BÁO: Chế độ này giao dịch bằng TIỀN THẬT trên Binance Spot!
Đảm bảo đã:
  1. Thiết lập biến môi trường BINANCE_API_KEY và BINANCE_API_SECRET
  2. Kiểm tra cấu hình rủi ro trong config.py
  3. Chạy backtest để xác nhận chiến lược

Ví dụ:
  python run_live.py --symbol BTCUSDT
  python run_live.py --symbol ETHUSDT
        """,
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="BTCUSDT",
        help="Cặp giao dịch (mặc định: BTCUSDT)",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="Xác nhận muốn giao dịch thật (bắt buộc)",
    )

    args = parser.parse_args()

    # Kiểm tra API key
    api_key = os.environ.get("BINANCE_API_KEY", "")
    api_secret = os.environ.get("BINANCE_API_SECRET", "")

    if not api_key or not api_secret:
        print("╔" + "═" * 55 + "╗")
        print("║  LỖI: Thiếu API key Binance!                         ║")
        print("║                                                       ║")
        print("║  Hãy thiết lập biến môi trường:                       ║")
        print("║    set BINANCE_API_KEY=your_api_key                   ║")
        print("║    set BINANCE_API_SECRET=your_api_secret             ║")
        print("╚" + "═" * 55 + "╝")
        sys.exit(1)

    # Yêu cầu xác nhận
    if not args.confirm:
        print()
        print("╔" + "═" * 55 + "╗")
        print("║  CẢNH BÁO: GIAO DỊCH BẰNG TIỀN THẬT!                ║")
        print("║                                                       ║")
        print("║  Hệ thống sẽ đặt lệnh thật trên Binance Spot.       ║")
        print("║  Bạn có thể mất tiền.                                ║")
        print("║                                                       ║")
        print("║  Để xác nhận, thêm cờ --confirm:                     ║")
        print("║    python run_live.py --symbol BTCUSDT --confirm      ║")
        print("╚" + "═" * 55 + "╝")
        print()

        response = input("Nhập 'DONG Y' để tiếp tục: ").strip()
        if response != "DONG Y":
            print("Đã hủy. Không thực hiện giao dịch.")
            sys.exit(0)

    # Khởi động giao dịch thực
    print()
    print(f"Khởi động giao dịch thực: {args.symbol}")
    print(f"Nhấn Ctrl+C để dừng an toàn.")
    print()

    from live.main import run_live_trading

    try:
        asyncio.run(run_live_trading(symbol=args.symbol))
    except KeyboardInterrupt:
        print("\nĐã dừng giao dịch.")


if __name__ == "__main__":
    main()
