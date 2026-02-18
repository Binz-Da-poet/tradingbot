"""
Cấu hình trung tâm cho hệ thống giao dịch crypto.
Tất cả tham số có thể tùy chỉnh được lưu tại đây.
"""

# ═══════════════════════════════════════════════════════════════
#  PHÍ GIAO DỊCH & TRƯỢT GIÁ
# ═══════════════════════════════════════════════════════════════
TRADING_FEE = 0.001       # Phí giao dịch 0.1% mỗi lần mua/bán
SLIPPAGE = 0.0005         # Trượt giá 0.05%

# ═══════════════════════════════════════════════════════════════
#  QUẢN LÝ RỦI RO
# ═══════════════════════════════════════════════════════════════
RISK_PER_TRADE = 0.01     # Rủi ro tối đa 1% vốn mỗi lệnh
MAX_DAILY_LOSS = 0.03     # Lỗ tối đa trong ngày 3%
MAX_OPEN_TRADES = 3       # Tối đa 3 lệnh mở cùng lúc
CIRCUIT_BREAKER_DD = 0.10 # Ngắt mạch khi drawdown vượt 10%

# ═══════════════════════════════════════════════════════════════
#  CHỐT LỜI & CẮT LỖ
# ═══════════════════════════════════════════════════════════════
TP_PCT = 0.003            # Chốt lời 0.3%
SL_PCT = 0.003            # Cắt lỗ 0.3%

# ═══════════════════════════════════════════════════════════════
#  CHỈ BÁO KỸ THUẬT
# ═══════════════════════════════════════════════════════════════
EMA_FAST = 9              # Chu kỳ EMA nhanh
EMA_SLOW = 21             # Chu kỳ EMA chậm
RSI_PERIOD = 14           # Chu kỳ RSI
RSI_THRESHOLD = 60        # Ngưỡng RSI (chỉ vào lệnh khi RSI < ngưỡng)
USE_RSI_FILTER = True     # Bật/tắt bộ lọc RSI

# ═══════════════════════════════════════════════════════════════
#  VỐN & TÀI KHOẢN
# ═══════════════════════════════════════════════════════════════
INITIAL_CAPITAL = 10_000.0  # Vốn ban đầu (USD)

# ═══════════════════════════════════════════════════════════════
#  TỐI ƯU THAM SỐ (GRID SEARCH)
# ═══════════════════════════════════════════════════════════════
OPTIMIZE_EMA_FAST_RANGE = range(5, 16)        # EMA nhanh: 5 → 15
OPTIMIZE_EMA_SLOW_RANGE = range(20, 51)       # EMA chậm: 20 → 50
OPTIMIZE_TP_VALUES = [0.002, 0.003, 0.004, 0.005, 0.006]  # TP: 0.2% → 0.6%
OPTIMIZE_SL_VALUES = [0.002, 0.003, 0.004, 0.005, 0.006]  # SL: 0.2% → 0.6%

# ═══════════════════════════════════════════════════════════════
#  ĐƯỜNG DẪN OUTPUT
# ═══════════════════════════════════════════════════════════════
OUTPUT_DIR = "output"
TRADE_LOG_FILE = "nhat_ky_giao_dich.csv"
EQUITY_CURVE_FILE = "bieu_do_duong_von.png"

# ═══════════════════════════════════════════════════════════════
#  TẢI DỮ LIỆU TỰ ĐỘNG
# ═══════════════════════════════════════════════════════════════
DATA_DIR = "data"                      # Thư mục lưu dữ liệu
DEFAULT_SYMBOL = "BTCUSDT"             # Cặp giao dịch mặc định
DEFAULT_INTERVAL = "1m"                # Khung thời gian mặc định
DEFAULT_DAYS_BACK = 30                 # Số ngày dữ liệu mặc định

# ═══════════════════════════════════════════════════════════════
#  BINANCE (CHẾ ĐỘ GIAO DỊCH THỰC)
# ═══════════════════════════════════════════════════════════════
BINANCE_SYMBOL = "BTCUSDT"
KLINE_INTERVAL = "1m"     # Khung thời gian 1 phút
