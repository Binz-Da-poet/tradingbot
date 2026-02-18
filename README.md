# Hệ Thống Giao Dịch Crypto

Hệ thống giao dịch crypto modular bằng Python, ưu tiên **nghiên cứu (backtest)** và hỗ trợ **giao dịch thực** qua Binance Spot API.

---

## Tính Năng

- **Giao diện Web (UI)**: Dashboard trực quan bằng Streamlit — biểu đồ tương tác, điều chỉnh tham số bằng chuột
- **Tự động tải dữ liệu**: Tải OHLCV từ Binance không cần API key
- **Chế độ nghiên cứu**: Backtest chiến lược EMA crossover trên dữ liệu lịch sử
- **Tối ưu tham số**: Grid search tìm tham số tốt nhất theo tỷ số Sharpe
- **Mô phỏng thực tế**: Phí giao dịch, trượt giá, quản lý rủi ro đầy đủ
- **Giao dịch thực** (tùy chọn): Kết nối Binance Spot, WebSocket, lệnh thị trường
- **Quản lý rủi ro**: Giới hạn lệnh, lỗ hàng ngày, ngắt mạch drawdown

---

## Cấu Trúc Dự Án

```
TRADING BOT/
├── core/                     # Module nghiên cứu
│   ├── data_handler.py       # Nạp CSV + tính chỉ báo kỹ thuật
│   ├── strategy.py           # Chiến lược EMA crossover + RSI
│   ├── backtester.py         # Mô phỏng giao dịch theo từng nến
│   └── metrics.py            # Phân tích hiệu suất + biểu đồ
├── live/                     # Module giao dịch thực
│   ├── execution.py          # Kết nối Binance API + WebSocket
│   ├── risk_manager.py       # Quản lý rủi ro thời gian thực
│   ├── order_manager.py      # Quản lý vòng đời lệnh
│   └── main.py               # Điều phối giao dịch thực (async)
├── optimizer/                # Tối ưu tham số
│   └── grid_search.py        # Grid search song song
├── config.py                 # Cấu hình trung tâm
├── app.py                    # Giao diện Web (Streamlit)
├── run_research.py           # Điểm vào CLI: nghiên cứu
├── run_live.py               # Điểm vào CLI: giao dịch thực
└── requirements.txt          # Thư viện phụ thuộc
```

---

## Cài Đặt

```bash
# 1. Tạo môi trường ảo (khuyến nghị)
python -m venv venv
venv\Scripts\activate     # Windows
# source venv/bin/activate  # Linux/Mac

# 2. Cài đặt thư viện
pip install -r requirements.txt
```

---

## Sử Dụng

### Cách 1: Giao Diện Web (Khuyến Nghị)

```bash
streamlit run app.py
```

Trình duyệt sẽ tự mở tại `http://localhost:8501` với giao diện gồm:

- **Trang chủ**: Tổng quan cấu hình, dữ liệu đã tải
- **Tải dữ liệu**: Tải OHLCV từ Binance, xem biểu đồ nến
- **Backtest**: Tùy chỉnh tham số bằng slider, chạy mô phỏng, xem biểu đồ
- **Tối ưu tham số**: Grid search tìm tham số tốt nhất
- **Kết quả**: Xem lại kết quả, tải CSV

### Cách 2: Dòng Lệnh (CLI)

```bash
# Tự động tải BTCUSDT 30 ngày + backtest
python run_research.py

# Tải coin/thời gian cụ thể
python run_research.py --download --symbol ETHUSDT --days 60

# Tải + tối ưu tham số
python run_research.py --download --optimize

# Dùng file CSV có sẵn
python run_research.py --csv data/BTCUSDT_1m.csv
```

**Kết quả:**
- Báo cáo hiệu suất in ra console
- `output/nhat_ky_giao_dich.csv` — Nhật ký từng lệnh
- `output/bieu_do_duong_von.png` — Biểu đồ đường vốn + drawdown
- `output/ket_qua_toi_uu.csv` — Bảng kết quả tối ưu (nếu dùng `--optimize`)

### Cách 3: Giao Dịch Thực

```bash
# Thiết lập API key (PowerShell)
$env:BINANCE_API_KEY = "your_api_key"
$env:BINANCE_API_SECRET = "your_api_secret"

# Chạy giao dịch thực
python run_live.py --symbol BTCUSDT --confirm
```

---

## Chiến Lược

**EMA Crossover + Bộ lọc RSI**

| Tham số        | Mặc định | Mô tả                          |
|----------------|----------|----------------------------------|
| EMA nhanh      | 9        | Chu kỳ EMA nhanh                 |
| EMA chậm       | 21       | Chu kỳ EMA chậm                  |
| RSI            | 14       | Chu kỳ RSI                       |
| Ngưỡng RSI     | 60       | Chỉ mua khi RSI < ngưỡng        |
| Chốt lời (TP)  | 0.3%     | Mức chốt lời                     |
| Cắt lỗ (SL)    | 0.3%     | Mức cắt lỗ                       |

**Quy tắc:**
1. **Vào lệnh**: EMA nhanh cắt lên EMA chậm + RSI < 60
2. **Thoát lệnh**: Chạm TP (chốt lời) hoặc SL (cắt lỗ)
3. **Chỉ LONG** (mua), không short

---

## Quản Lý Rủi Ro

| Quy tắc               | Giá trị   |
|------------------------|-----------|
| Rủi ro mỗi lệnh       | 1% vốn   |
| Lỗ tối đa trong ngày  | 3% vốn   |
| Lệnh mở tối đa        | 3         |
| Ngắt mạch (drawdown)  | 10%       |

---

## Tối Ưu Tham Số

Grid search tìm kiếm trong không gian:

| Tham số    | Dải giá trị        |
|------------|---------------------|
| EMA nhanh  | 5, 6, ..., 15       |
| EMA chậm   | 20, 21, ..., 50     |
| TP         | 0.2%, 0.3%, ..., 0.6% |
| SL         | 0.2%, 0.3%, ..., 0.6% |

Tổng: ~8,525 tổ hợp. Xếp hạng theo **tỷ số Sharpe**.

---

## Mô Phỏng Thực Tế

Hệ thống áp dụng các yếu tố thực tế:

- **Phí giao dịch**: 0.1% mỗi lần mua/bán
- **Trượt giá**: 0.05%
- **Duyệt từng nến**: Kiểm tra TP/SL bằng high/low (không vector hóa)
- **SL kiểm tra trước TP**: Trường hợp xấu ưu tiên
- **Không đòn bẩy**: Chỉ giao dịch spot

---

## Định Dạng File CSV Đầu Vào

File CSV cần có các cột (không phân biệt hoa/thường):

```
timestamp,open,high,low,close,volume
2024-01-01 00:00:00,42000.5,42050.0,41980.0,42030.0,125.3
2024-01-01 00:01:00,42030.0,42060.0,42010.0,42045.0,98.7
...
```

---

## Lưu Ý Quan Trọng

- Hệ thống được thiết kế cho **nghiên cứu**, không đảm bảo lợi nhuận
- Kết quả backtest **không đại diện** cho hiệu suất tương lai
- Giao dịch thực có rủi ro mất vốn — hãy bắt đầu với số tiền nhỏ
- Luôn kiểm tra kỹ chiến lược bằng backtest trước khi giao dịch thực
