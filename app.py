"""
Giao diện Web cho Hệ Thống Giao Dịch Crypto.
Chạy: streamlit run app.py
"""

import os
import sys
import time
import glob
from datetime import datetime, timedelta
from typing import Dict

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import config
from core.data_handler import load_csv, compute_indicators
from core.data_downloader import download_ohlcv, list_available_data
from core.strategy import generate_signals
from core.backtester import Backtester, BacktestParams
from core.metrics import calculate_metrics, export_trade_log
from live.live_trader import LiveTrader

# ═══════════════════════════════════════════════════════════════
#  CẤU HÌNH TRANG
# ═══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Hệ Thống Giao Dịch Crypto",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def local_css():
    """CSS tùy chỉnh cho giao diện đẹp hơn."""
    st.markdown("""
    <style>
    .metric-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        padding: 1.2rem;
        border-radius: 12px;
        border: 1px solid #0f3460;
        text-align: center;
    }
    .metric-card h3 {
        color: #a8b2d1;
        font-size: 0.85rem;
        margin-bottom: 0.3rem;
        font-weight: 400;
    }
    .metric-card p {
        font-size: 1.6rem;
        font-weight: 700;
        margin: 0;
    }
    .positive { color: #00e676; }
    .negative { color: #ff5252; }
    .neutral { color: #e0e0e0; }
    .section-header {
        border-bottom: 2px solid #0f3460;
        padding-bottom: 0.5rem;
        margin-bottom: 1rem;
    }
    </style>
    """, unsafe_allow_html=True)


def metric_card(title: str, value: str, color_class: str = "neutral"):
    """Hiển thị thẻ chỉ số đẹp."""
    return f"""
    <div class="metric-card">
        <h3>{title}</h3>
        <p class="{color_class}">{value}</p>
    </div>
    """


# ═══════════════════════════════════════════════════════════════
#  SIDEBAR — ĐIỀU KHIỂN
# ═══════════════════════════════════════════════════════════════
def render_sidebar():
    """Thanh điều khiển bên trái."""
    with st.sidebar:
        st.markdown("## 📊 Hệ Thống Giao Dịch")
        st.markdown("---")

        page = st.radio(
            "Chọn chức năng:",
            [
                "🏠 Trang chủ",
                "📥 Tải dữ liệu",
                "🔬 Backtest",
                "⚡ Tối ưu tham số",
                "🔴 Giao dịch thực",
                "📋 Kết quả",
            ],
            index=0,
        )

        st.markdown("---")
        st.caption("Phiên bản 2.0")
        st.caption("Nghiên cứu + Giao dịch thực")

    return page


# ═══════════════════════════════════════════════════════════════
#  TRANG CHỦ
# ═══════════════════════════════════════════════════════════════
def page_home():
    """Trang chủ — tổng quan hệ thống."""
    st.markdown("# 📊 Hệ Thống Giao Dịch Crypto")
    st.markdown("**Nghiên cứu chiến lược & Mô phỏng giao dịch**")
    st.markdown("---")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("### 📥 Bước 1: Tải dữ liệu")
        st.markdown(
            "Tự động tải dữ liệu OHLCV từ Binance. "
            "Chọn cặp giao dịch, khung thời gian, khoảng ngày."
        )
    with col2:
        st.markdown("### 🔬 Bước 2: Backtest")
        st.markdown(
            "Chạy mô phỏng chiến lược EMA Crossover + RSI "
            "với phí, trượt giá, quản lý rủi ro đầy đủ."
        )
    with col3:
        st.markdown("### ⚡ Bước 3: Tối ưu")
        st.markdown(
            "Grid Search tìm bộ tham số tốt nhất "
            "dựa trên tỷ số Sharpe."
        )

    st.markdown("---")

    # Hiển thị cấu hình hiện tại
    st.markdown("### ⚙️ Cấu hình hiện tại")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Vốn ban đầu", f"${config.INITIAL_CAPITAL:,.0f}")
        st.metric("Phí giao dịch", f"{config.TRADING_FEE*100}%")
    with c2:
        st.metric("EMA nhanh/chậm", f"{config.EMA_FAST}/{config.EMA_SLOW}")
        st.metric("Trượt giá", f"{config.SLIPPAGE*100}%")
    with c3:
        st.metric("Chốt lời (TP)", f"{config.TP_PCT*100}%")
        st.metric("Cắt lỗ (SL)", f"{config.SL_PCT*100}%")
    with c4:
        st.metric("Rủi ro/lệnh", f"{config.RISK_PER_TRADE*100}%")
        st.metric("Ngắt mạch DD", f"{config.CIRCUIT_BREAKER_DD*100}%")

    # Dữ liệu đã tải
    st.markdown("---")
    st.markdown("### 📂 Dữ liệu đã tải")
    files = list_available_data(config.DATA_DIR)
    if files:
        df_files = pd.DataFrame(files)
        df_files.columns = ["Tên file", "Đường dẫn", "Dung lượng (MB)", "Số nến"]
        st.dataframe(
            df_files[["Tên file", "Số nến", "Dung lượng (MB)"]],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Chưa có dữ liệu. Vào **📥 Tải dữ liệu** để bắt đầu.")


# ═══════════════════════════════════════════════════════════════
#  TRANG TẢI DỮ LIỆU
# ═══════════════════════════════════════════════════════════════
def page_download():
    """Trang tải dữ liệu từ Binance."""
    st.markdown("# 📥 Tải Dữ Liệu Từ Binance")
    st.markdown("Tải dữ liệu OHLCV lịch sử — không cần API key.")
    st.markdown("---")

    col1, col2 = st.columns([1, 1])

    with col1:
        symbol = st.text_input(
            "Cặp giao dịch",
            value="BTCUSDT",
            help="VD: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT",
        ).upper()

        interval = st.selectbox(
            "Khung thời gian",
            ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"],
            index=0,
        )

    with col2:
        mode = st.radio(
            "Chọn khoảng thời gian",
            ["Số ngày gần đây", "Ngày cụ thể"],
        )

        if mode == "Số ngày gần đây":
            days = st.slider("Số ngày", min_value=1, max_value=365, value=30)
            start_date = None
            end_date = None
        else:
            d1, d2 = st.columns(2)
            with d1:
                start_date = st.date_input(
                    "Từ ngày",
                    value=datetime.now() - timedelta(days=30),
                ).strftime("%Y-%m-%d")
            with d2:
                end_date = st.date_input(
                    "Đến ngày",
                    value=datetime.now(),
                ).strftime("%Y-%m-%d")
            days = 30

    force = st.checkbox("Tải lại dù đã có (ghi đè cache)", value=False)

    if st.button("🚀 Bắt đầu tải", type="primary", use_container_width=True):
        with st.spinner(f"Đang tải {symbol} khung {interval}..."):
            progress_bar = st.progress(0, text="Kết nối Binance...")

            csv_path = download_ohlcv(
                symbol=symbol,
                interval=interval,
                start_date=start_date,
                end_date=end_date,
                days_back=days,
                save_dir=config.DATA_DIR,
                force=force,
            )

            progress_bar.progress(100, text="Hoàn thành!")

        if csv_path:
            st.success(f"Đã tải thành công: `{csv_path}`")

            df = pd.read_csv(csv_path)
            st.markdown(f"**{len(df):,} nến** từ `{df.iloc[0, 0]}` đến `{df.iloc[-1, 0]}`")

            # Hiển thị biểu đồ nến nhanh
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            _show_candlestick_preview(df, symbol)
        else:
            st.error("Không tải được dữ liệu. Kiểm tra cặp giao dịch và kết nối mạng.")

    # Danh sách file đã tải
    st.markdown("---")
    st.markdown("### 📂 Dữ liệu đã tải")
    files = list_available_data(config.DATA_DIR)
    if files:
        for f in files:
            col_a, col_b, col_c = st.columns([3, 1, 1])
            col_a.text(f["file"])
            col_b.text(f"{f['rows']:,} nến")
            col_c.text(f"{f['size_mb']:.1f} MB")
    else:
        st.info("Chưa có dữ liệu nào.")


def _show_candlestick_preview(df: pd.DataFrame, symbol: str):
    """Biểu đồ nến xem trước (500 nến cuối)."""
    preview = df.tail(500)
    fig = go.Figure(data=[go.Candlestick(
        x=preview["timestamp"],
        open=preview["open"],
        high=preview["high"],
        low=preview["low"],
        close=preview["close"],
        increasing_line_color="#00e676",
        decreasing_line_color="#ff5252",
    )])
    fig.update_layout(
        title=f"{symbol} — 500 nến gần nhất",
        xaxis_title="Thời gian",
        yaxis_title="Giá (USD)",
        template="plotly_dark",
        height=400,
        xaxis_rangeslider_visible=False,
    )
    st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════
#  TRANG BACKTEST
# ═══════════════════════════════════════════════════════════════
def page_backtest():
    """Trang chạy backtest."""
    st.markdown("# 🔬 Backtest Chiến Lược")
    st.markdown("Mô phỏng giao dịch trên dữ liệu lịch sử.")
    st.markdown("---")

    # Chọn dữ liệu
    files = list_available_data(config.DATA_DIR)
    csv_files = glob.glob(os.path.join(config.DATA_DIR, "*.csv"))

    if not csv_files:
        st.warning("Chưa có dữ liệu. Vào **📥 Tải dữ liệu** để tải trước.")
        return

    selected_file = st.selectbox(
        "Chọn file dữ liệu",
        csv_files,
        format_func=lambda x: os.path.basename(x),
    )

    # Tham số chiến lược
    st.markdown("### ⚙️ Tham số chiến lược")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**Chỉ báo kỹ thuật**")
        ema_fast = st.number_input("EMA nhanh", min_value=2, max_value=50, value=config.EMA_FAST)
        ema_slow = st.number_input("EMA chậm", min_value=5, max_value=200, value=config.EMA_SLOW)
        rsi_period = st.number_input("Chu kỳ RSI", min_value=2, max_value=50, value=config.RSI_PERIOD)
        rsi_threshold = st.number_input("Ngưỡng RSI", min_value=10, max_value=90, value=config.RSI_THRESHOLD)
        use_rsi = st.checkbox("Bật bộ lọc RSI", value=config.USE_RSI_FILTER)

    with col2:
        st.markdown("**Chốt lời & Cắt lỗ**")
        tp_pct = st.slider("Chốt lời TP (%)", 0.1, 2.0, config.TP_PCT * 100, 0.1) / 100
        sl_pct = st.slider("Cắt lỗ SL (%)", 0.1, 2.0, config.SL_PCT * 100, 0.1) / 100
        st.markdown("**Mô phỏng**")
        trading_fee = st.slider("Phí giao dịch (%)", 0.0, 0.5, config.TRADING_FEE * 100, 0.01) / 100
        slippage = st.slider("Trượt giá (%)", 0.0, 0.2, config.SLIPPAGE * 100, 0.01) / 100

    with col3:
        st.markdown("**Quản lý rủi ro**")
        initial_capital = st.number_input("Vốn ban đầu (USD)", min_value=100, max_value=1_000_000, value=int(config.INITIAL_CAPITAL), step=1000)
        risk_per_trade = st.slider("Rủi ro/lệnh (%)", 0.1, 5.0, config.RISK_PER_TRADE * 100, 0.1) / 100
        max_daily_loss = st.slider("Lỗ tối đa/ngày (%)", 0.5, 10.0, config.MAX_DAILY_LOSS * 100, 0.5) / 100
        max_open_trades = st.number_input("Lệnh mở tối đa", min_value=1, max_value=10, value=config.MAX_OPEN_TRADES)
        circuit_breaker = st.slider("Ngắt mạch DD (%)", 1.0, 30.0, config.CIRCUIT_BREAKER_DD * 100, 1.0) / 100

    # Kiểm tra EMA
    if ema_fast >= ema_slow:
        st.error("EMA nhanh phải nhỏ hơn EMA chậm!")
        return

    st.markdown("---")

    # Nút chạy
    if st.button("🚀 Chạy Backtest", type="primary", use_container_width=True):
        _run_backtest(
            csv_path=selected_file,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            rsi_period=rsi_period,
            rsi_threshold=rsi_threshold,
            use_rsi=use_rsi,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            trading_fee=trading_fee,
            slippage=slippage,
            initial_capital=float(initial_capital),
            risk_per_trade=risk_per_trade,
            max_daily_loss=max_daily_loss,
            max_open_trades=max_open_trades,
            circuit_breaker=circuit_breaker,
        )


def _run_backtest(
    csv_path, ema_fast, ema_slow, rsi_period, rsi_threshold,
    use_rsi, tp_pct, sl_pct, trading_fee, slippage,
    initial_capital, risk_per_trade, max_daily_loss,
    max_open_trades, circuit_breaker,
):
    """Thực thi backtest và hiển thị kết quả."""
    progress = st.progress(0, text="Đang nạp dữ liệu...")

    # Nạp dữ liệu
    df = load_csv(csv_path)
    progress.progress(15, text="Đang tính chỉ báo kỹ thuật...")

    # Tính chỉ báo
    df = compute_indicators(df, ema_fast=ema_fast, ema_slow=ema_slow, rsi_period=rsi_period)
    progress.progress(30, text="Đang tạo tín hiệu giao dịch...")

    # Tạo tín hiệu
    df = generate_signals(df, rsi_threshold=rsi_threshold, use_rsi_filter=use_rsi)
    progress.progress(45, text="Đang chạy mô phỏng...")

    # Chạy backtest
    params = BacktestParams(
        initial_capital=initial_capital,
        trading_fee=trading_fee,
        slippage=slippage,
        risk_per_trade=risk_per_trade,
        max_daily_loss=max_daily_loss,
        max_open_trades=max_open_trades,
        circuit_breaker_dd=circuit_breaker,
        tp_pct=tp_pct,
        sl_pct=sl_pct,
    )

    bt = Backtester(params)
    start_time = time.time()
    trade_log, equity_curve = bt.run(df, silent=True)
    elapsed = time.time() - start_time
    progress.progress(80, text="Đang phân tích hiệu suất...")

    # Tính metrics
    metrics = calculate_metrics(trade_log, equity_curve, initial_capital)
    progress.progress(100, text=f"Hoàn thành! ({elapsed:.1f}s)")

    # Lưu vào session state
    st.session_state["last_metrics"] = metrics
    st.session_state["last_trade_log"] = trade_log
    st.session_state["last_equity_curve"] = equity_curve
    st.session_state["last_df"] = df
    st.session_state["last_elapsed"] = elapsed

    # Hiển thị kết quả
    _display_results(metrics, trade_log, equity_curve, df, initial_capital, elapsed)


def _display_results(metrics, trade_log, equity_curve, df, initial_capital, elapsed):
    """Hiển thị toàn bộ kết quả backtest."""
    st.markdown("---")
    st.markdown("## 📊 Kết Quả Backtest")

    # Thẻ chỉ số chính
    total_return = metrics.get("tong_loi_nhuan_pct", 0)
    return_color = "positive" if total_return >= 0 else "negative"

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        sign = "+" if total_return >= 0 else ""
        st.markdown(metric_card("Tổng lợi nhuận", f"{sign}{total_return:.2f}%", return_color), unsafe_allow_html=True)
    with c2:
        st.markdown(metric_card("Vốn cuối", f"${metrics.get('von_cuoi', 0):,.0f}", return_color), unsafe_allow_html=True)
    with c3:
        st.markdown(metric_card("Tỷ lệ thắng", f"{metrics.get('ty_le_thang', 0):.1f}%", "neutral"), unsafe_allow_html=True)
    with c4:
        pf = metrics.get("profit_factor", 0)
        pf_color = "positive" if pf > 1 else "negative" if pf < 1 else "neutral"
        pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"
        st.markdown(metric_card("Profit Factor", pf_str, pf_color), unsafe_allow_html=True)
    with c5:
        dd = metrics.get("drawdown_toi_da_pct", 0)
        dd_color = "positive" if dd < 5 else "negative" if dd > 15 else "neutral"
        st.markdown(metric_card("Max Drawdown", f"-{dd:.2f}%", dd_color), unsafe_allow_html=True)
    with c6:
        sharpe = metrics.get("ty_so_sharpe", 0)
        s_color = "positive" if sharpe > 1 else "negative" if sharpe < 0 else "neutral"
        st.markdown(metric_card("Sharpe Ratio", f"{sharpe:.2f}", s_color), unsafe_allow_html=True)

    st.markdown("")

    # Thống kê bổ sung
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tổng số lệnh", metrics.get("tong_so_lenh", 0))
    c2.metric("Lệnh thắng", metrics.get("so_lenh_thang", 0))
    c3.metric("Lệnh thua", metrics.get("so_lenh_thua", 0))
    c4.metric("Thời gian chạy", f"{elapsed:.1f}s")

    # Biểu đồ đường vốn
    st.markdown("---")
    st.markdown("### 📈 Biểu Đồ Đường Vốn")

    if not equity_curve.empty:
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            row_heights=[0.7, 0.3],
            subplot_titles=("Đường vốn (USD)", "Drawdown (%)"),
        )

        # Đường vốn
        fig.add_trace(go.Scatter(
            x=equity_curve["timestamp"],
            y=equity_curve["equity"],
            mode="lines",
            name="Vốn",
            line=dict(color="#2196F3", width=1.5),
            fill="tozeroy",
            fillcolor="rgba(33,150,243,0.1)",
        ), row=1, col=1)

        # Đường vốn ban đầu
        fig.add_hline(
            y=initial_capital, row=1, col=1,
            line_dash="dash", line_color="gray",
            annotation_text=f"Vốn ban đầu: ${initial_capital:,.0f}",
        )

        # Drawdown
        equity_s = equity_curve["equity"]
        peak = equity_s.cummax()
        dd_pct = ((peak - equity_s) / peak) * 100

        fig.add_trace(go.Scatter(
            x=equity_curve["timestamp"],
            y=dd_pct,
            mode="lines",
            name="Drawdown",
            line=dict(color="#ff5252", width=1),
            fill="tozeroy",
            fillcolor="rgba(255,82,82,0.2)",
        ), row=2, col=1)

        fig.update_layout(
            template="plotly_dark",
            height=550,
            showlegend=False,
            margin=dict(t=40, b=40),
        )
        fig.update_yaxes(title_text="USD", row=1, col=1)
        fig.update_yaxes(title_text="%", autorange="reversed", row=2, col=1)

        st.plotly_chart(fig, use_container_width=True)

    # Biểu đồ giá + tín hiệu
    st.markdown("### 🕯️ Biểu Đồ Giá & Tín Hiệu")
    _plot_price_signals(df)

    # Bảng nhật ký giao dịch
    st.markdown("---")
    st.markdown("### 📋 Nhật Ký Giao Dịch")
    if not trade_log.empty:
        st.dataframe(
            trade_log.style.applymap(
                lambda v: "color: #00e676" if isinstance(v, (int, float)) and v > 0
                else "color: #ff5252" if isinstance(v, (int, float)) and v < 0
                else "",
                subset=["lai_lo", "lai_lo_pct"] if "lai_lo" in trade_log.columns else [],
            ),
            use_container_width=True,
            height=400,
        )

        # Nút tải CSV
        csv_data = trade_log.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            "📥 Tải nhật ký CSV",
            data=csv_data,
            file_name="nhat_ky_giao_dich.csv",
            mime="text/csv",
        )
    else:
        st.info("Không có lệnh giao dịch nào.")

    # Phân bố lãi/lỗ
    if not trade_log.empty and "lai_lo" in trade_log.columns:
        st.markdown("### 📊 Phân Bố Lãi/Lỗ")
        fig_hist = go.Figure()
        fig_hist.add_trace(go.Histogram(
            x=trade_log["lai_lo"],
            nbinsx=40,
            marker_color=["#00e676" if x > 0 else "#ff5252" for x in trade_log["lai_lo"]],
            name="PnL",
        ))
        fig_hist.update_layout(
            template="plotly_dark",
            xaxis_title="Lãi/Lỗ (USD)",
            yaxis_title="Số lệnh",
            height=300,
        )
        st.plotly_chart(fig_hist, use_container_width=True)


def _plot_price_signals(df: pd.DataFrame):
    """Biểu đồ giá với EMA và tín hiệu mua."""
    # Lấy 2000 nến cuối để không quá nặng
    plot_df = df.tail(2000).copy()

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.7, 0.3],
        subplot_titles=("Giá & EMA", "RSI"),
    )

    # Nến
    fig.add_trace(go.Candlestick(
        x=plot_df["timestamp"],
        open=plot_df["open"],
        high=plot_df["high"],
        low=plot_df["low"],
        close=plot_df["close"],
        increasing_line_color="#00e676",
        decreasing_line_color="#ff5252",
        name="Giá",
    ), row=1, col=1)

    # EMA
    if "ema_fast" in plot_df.columns:
        fig.add_trace(go.Scatter(
            x=plot_df["timestamp"], y=plot_df["ema_fast"],
            line=dict(color="#FFD700", width=1),
            name="EMA nhanh",
        ), row=1, col=1)
    if "ema_slow" in plot_df.columns:
        fig.add_trace(go.Scatter(
            x=plot_df["timestamp"], y=plot_df["ema_slow"],
            line=dict(color="#FF6B6B", width=1),
            name="EMA chậm",
        ), row=1, col=1)

    # Tín hiệu mua
    if "signal" in plot_df.columns:
        buys = plot_df[plot_df["signal"] == 1]
        if not buys.empty:
            fig.add_trace(go.Scatter(
                x=buys["timestamp"],
                y=buys["low"] * 0.999,
                mode="markers",
                marker=dict(symbol="triangle-up", size=12, color="#00e676"),
                name="Tín hiệu MUA",
            ), row=1, col=1)

    # RSI
    if "rsi" in plot_df.columns:
        fig.add_trace(go.Scatter(
            x=plot_df["timestamp"], y=plot_df["rsi"],
            line=dict(color="#AB47BC", width=1),
            name="RSI",
        ), row=2, col=1)
        fig.add_hline(y=60, row=2, col=1, line_dash="dash", line_color="gray")
        fig.add_hline(y=40, row=2, col=1, line_dash="dash", line_color="gray")

    fig.update_layout(
        template="plotly_dark",
        height=550,
        xaxis_rangeslider_visible=False,
        margin=dict(t=40, b=40),
    )

    st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════
#  TRANG TỐI ƯU THAM SỐ
# ═══════════════════════════════════════════════════════════════
def page_optimize():
    """Trang tối ưu tham số chiến lược."""
    st.markdown("# ⚡ Tối Ưu Tham Số")
    st.markdown("Grid Search tìm bộ tham số tốt nhất theo tỷ số Sharpe.")
    st.markdown("---")

    # Chọn dữ liệu
    csv_files = glob.glob(os.path.join(config.DATA_DIR, "*.csv"))
    if not csv_files:
        st.warning("Chưa có dữ liệu. Vào **📥 Tải dữ liệu** để tải trước.")
        return

    selected_file = st.selectbox(
        "Chọn file dữ liệu",
        csv_files,
        format_func=lambda x: os.path.basename(x),
        key="opt_file",
    )

    # Không gian tìm kiếm
    st.markdown("### 🔧 Không gian tìm kiếm")
    col1, col2 = st.columns(2)

    with col1:
        ema_fast_range = st.slider("Dải EMA nhanh", 2, 30, (5, 15))
        ema_slow_range = st.slider("Dải EMA chậm", 10, 100, (20, 50))

    with col2:
        tp_min, tp_max = st.slider("Dải TP (%)", 0.1, 2.0, (0.2, 0.6), 0.1)
        sl_min, sl_max = st.slider("Dải SL (%)", 0.1, 2.0, (0.2, 0.6), 0.1)
        tp_step = st.selectbox("Bước TP/SL (%)", [0.1, 0.05, 0.2], index=0)

    # Tính số tổ hợp
    ema_f_count = ema_fast_range[1] - ema_fast_range[0] + 1
    ema_s_count = ema_slow_range[1] - ema_slow_range[0] + 1
    tp_values = [round(v / 100, 4) for v in range(int(tp_min * 100), int(tp_max * 100) + 1, int(tp_step * 100))]
    sl_values = [round(v / 100, 4) for v in range(int(sl_min * 100), int(sl_max * 100) + 1, int(tp_step * 100))]
    total_combos = ema_f_count * ema_s_count * len(tp_values) * len(sl_values)
    valid_combos = sum(
        1 for f in range(ema_fast_range[0], ema_fast_range[1] + 1)
        for s in range(ema_slow_range[0], ema_slow_range[1] + 1)
        if f < s
    ) * len(tp_values) * len(sl_values)

    st.info(f"Tổng tổ hợp hợp lệ: **{valid_combos:,}** (TP: {tp_values}, SL: {sl_values})")

    if valid_combos > 20_000:
        st.warning("Số tổ hợp lớn — quá trình tối ưu có thể mất nhiều thời gian.")

    st.markdown("---")

    if st.button("🚀 Bắt Đầu Tối Ưu", type="primary", use_container_width=True):
        from optimizer.grid_search import run_grid_search

        progress = st.progress(0, text="Đang nạp dữ liệu...")

        base_df = load_csv(selected_file)
        progress.progress(10, text=f"Đang chạy Grid Search ({valid_combos:,} tổ hợp)...")

        start_time = time.time()
        best_params, results_df = run_grid_search(
            base_df=base_df,
            initial_capital=config.INITIAL_CAPITAL,
            ema_fast_range=range(ema_fast_range[0], ema_fast_range[1] + 1),
            ema_slow_range=range(ema_slow_range[0], ema_slow_range[1] + 1),
            tp_values=tp_values,
            sl_values=sl_values,
            n_workers=1,
        )
        elapsed = time.time() - start_time
        progress.progress(100, text=f"Hoàn thành! ({elapsed:.0f}s)")

        if not best_params:
            st.error("Không tìm được tham số hợp lệ.")
            return

        # Hiển thị tham số tốt nhất
        st.markdown("### 🏆 Tham Số Tốt Nhất")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("EMA nhanh", best_params["ema_fast"])
        c2.metric("EMA chậm", best_params["ema_slow"])
        c3.metric("Chốt lời", f"{best_params['tp_pct']*100:.1f}%")
        c4.metric("Cắt lỗ", f"{best_params['sl_pct']*100:.1f}%")

        # Bảng top kết quả
        st.markdown("### 📊 Top 20 Tổ Hợp")
        if not results_df.empty:
            top20 = results_df.head(20).copy()
            top20["tp_pct"] = (top20["tp_pct"] * 100).round(1).astype(str) + "%"
            top20["sl_pct"] = (top20["sl_pct"] * 100).round(1).astype(str) + "%"
            top20 = top20.rename(columns={
                "ema_fast": "EMA nhanh",
                "ema_slow": "EMA chậm",
                "tp_pct": "TP",
                "sl_pct": "SL",
                "sharpe": "Sharpe",
                "loi_nhuan_pct": "Lợi nhuận %",
                "ty_le_thang": "Thắng %",
                "drawdown_pct": "DD %",
                "so_lenh": "Số lệnh",
                "profit_factor": "PF",
            })
            st.dataframe(top20, use_container_width=True, hide_index=True, height=500)

            # Tải CSV
            csv_data = results_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
            st.download_button(
                "📥 Tải toàn bộ kết quả CSV",
                data=csv_data,
                file_name="ket_qua_toi_uu.csv",
                mime="text/csv",
            )

        # Lưu vào session state để dùng ở trang backtest
        st.session_state["best_params"] = best_params
        st.session_state["opt_results"] = results_df

        st.success(
            f"Dùng tham số tốt nhất: vào **🔬 Backtest**, đặt "
            f"EMA={best_params['ema_fast']}/{best_params['ema_slow']}, "
            f"TP={best_params['tp_pct']*100:.1f}%, SL={best_params['sl_pct']*100:.1f}%"
        )


# ═══════════════════════════════════════════════════════════════
#  TRANG KẾT QUẢ
# ═══════════════════════════════════════════════════════════════
def page_results():
    """Trang xem kết quả lưu trữ."""
    st.markdown("# 📋 Kết Quả Đã Lưu")
    st.markdown("---")

    # Kết quả từ session hiện tại
    if "last_metrics" in st.session_state:
        st.markdown("### 📊 Kết Quả Backtest Gần Nhất")
        metrics = st.session_state["last_metrics"]
        trade_log = st.session_state.get("last_trade_log", pd.DataFrame())
        equity_curve = st.session_state.get("last_equity_curve", pd.DataFrame())

        c1, c2, c3, c4 = st.columns(4)
        total_return = metrics.get("tong_loi_nhuan_pct", 0)
        sign = "+" if total_return >= 0 else ""
        c1.metric("Tổng lợi nhuận", f"{sign}{total_return:.2f}%")
        c2.metric("Tỷ lệ thắng", f"{metrics.get('ty_le_thang', 0):.1f}%")
        c3.metric("Max Drawdown", f"-{metrics.get('drawdown_toi_da_pct', 0):.2f}%")
        c4.metric("Sharpe", f"{metrics.get('ty_so_sharpe', 0):.2f}")

        if not equity_curve.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=equity_curve["timestamp"],
                y=equity_curve["equity"],
                mode="lines",
                line=dict(color="#2196F3", width=1.5),
                fill="tozeroy",
                fillcolor="rgba(33,150,243,0.1)",
            ))
            fig.update_layout(
                template="plotly_dark",
                height=350,
                yaxis_title="Vốn (USD)",
            )
            st.plotly_chart(fig, use_container_width=True)

        if not trade_log.empty:
            st.dataframe(trade_log, use_container_width=True, height=300)
    else:
        st.info("Chưa có kết quả. Chạy **🔬 Backtest** trước.")

    # Kết quả tối ưu
    st.markdown("---")
    if "opt_results" in st.session_state:
        st.markdown("### ⚡ Kết Quả Tối Ưu Gần Nhất")
        opt_df = st.session_state["opt_results"]
        best = st.session_state.get("best_params", {})

        if best:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("EMA nhanh", best.get("ema_fast", "—"))
            c2.metric("EMA chậm", best.get("ema_slow", "—"))
            c3.metric("TP", f"{best.get('tp_pct', 0)*100:.1f}%")
            c4.metric("SL", f"{best.get('sl_pct', 0)*100:.1f}%")

        if not opt_df.empty:
            st.dataframe(opt_df.head(20), use_container_width=True, height=400)

    # Files output
    st.markdown("---")
    st.markdown("### 📂 File Output")
    output_files = glob.glob(os.path.join(config.OUTPUT_DIR, "*"))
    if output_files:
        for f in output_files:
            fname = os.path.basename(f)
            size = os.path.getsize(f) / 1024
            st.text(f"  {fname} ({size:.1f} KB)")
    else:
        st.info("Chưa có file output nào.")


# ═══════════════════════════════════════════════════════════════
#  TRANG GIAO DỊCH THỰC
# ═══════════════════════════════════════════════════════════════
def page_live_trading():
    """Trang giao dịch thực trên Binance."""
    st.markdown("# 🔴 Giao Dịch Thực")
    st.markdown("Kết nối Binance Spot — vào lệnh thật với tiền thật.")
    st.markdown("---")

    # ── Cấu hình kết nối ──
    st.markdown("### 🔑 Kết nối Binance")
    col_k1, col_k2 = st.columns(2)
    with col_k1:
        api_key = st.text_input("API Key", type="password", key="live_api_key")
    with col_k2:
        api_secret = st.text_input("API Secret", type="password", key="live_api_secret")

    # ── Tham số giao dịch ──
    st.markdown("### ⚙️ Tham số giao dịch")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        symbol = st.text_input("Cặp giao dịch", value="BTCUSDT", key="live_symbol").upper()
    with col2:
        ema_fast = st.number_input("EMA nhanh", 2, 50, config.EMA_FAST, key="live_ema_f")
        ema_slow = st.number_input("EMA chậm", 5, 200, config.EMA_SLOW, key="live_ema_s")
    with col3:
        tp_pct = st.slider("Chốt lời TP (%)", 0.1, 2.0, config.TP_PCT * 100, 0.1, key="live_tp") / 100
        sl_pct = st.slider("Cắt lỗ SL (%)", 0.1, 2.0, config.SL_PCT * 100, 0.1, key="live_sl") / 100
    with col4:
        refresh_sec = st.selectbox("Tự động cập nhật (giây)", [5, 10, 15, 30, 60], index=1, key="live_refresh")

    if ema_fast >= ema_slow:
        st.error("EMA nhanh phải nhỏ hơn EMA chậm!")
        return

    st.markdown("---")

    # ── Nút điều khiển ──
    col_btn1, col_btn2, col_btn3, col_btn4 = st.columns(4)

    with col_btn1:
        connect_btn = st.button("🟢 Kết nối & Bắt đầu", type="primary", use_container_width=True)
    with col_btn2:
        tick_btn = st.button("🔄 Cập nhật ngay", use_container_width=True)
    with col_btn3:
        close_all_btn = st.button("🛑 Đóng tất cả lệnh", use_container_width=True)
    with col_btn4:
        reset_btn = st.button("🗑️ Reset trạng thái", use_container_width=True)

    # ── Khởi tạo trader trong session ──
    if connect_btn:
        if not api_key or not api_secret:
            st.error("Vui lòng nhập API Key và API Secret!")
            return

        trader = LiveTrader(
            api_key=api_key,
            api_secret=api_secret,
            symbol=symbol,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
        )

        with st.spinner("Đang kết nối Binance..."):
            success = trader.connect()

        if success:
            st.session_state["live_trader"] = trader
            st.session_state["live_active"] = True
            st.success(f"Đã kết nối! Bắt đầu giao dịch {symbol}.")
            # Thực hiện tick đầu tiên
            status = trader.tick()
            st.session_state["live_status"] = status
        else:
            st.error("Kết nối thất bại. Kiểm tra API key và kết nối mạng.")
            return

    # ── Xử lý cập nhật ──
    trader: LiveTrader = st.session_state.get("live_trader")

    if trader and tick_btn:
        with st.spinner("Đang kiểm tra thị trường..."):
            status = trader.tick()
        st.session_state["live_status"] = status

    if trader and close_all_btn:
        with st.spinner("Đang đóng tất cả vị thế..."):
            trader.close_all()
            status = trader.tick()
        st.session_state["live_status"] = status
        st.success("Đã đóng tất cả vị thế.")

    if trader and reset_btn:
        trader.reset_state()
        st.session_state.pop("live_trader", None)
        st.session_state.pop("live_status", None)
        st.session_state["live_active"] = False
        st.info("Đã reset. Kết nối lại để tiếp tục.")
        st.rerun()

    # ── Auto-refresh ──
    if st.session_state.get("live_active") and trader:
        auto_on = st.checkbox("Bật tự động cập nhật", value=True, key="live_auto")
        if auto_on:
            placeholder = st.empty()
            for _ in range(1):
                status = trader.tick()
                st.session_state["live_status"] = status
                time.sleep(0.1)

    # ── Hiển thị trạng thái ──
    status = st.session_state.get("live_status")
    if status:
        _render_live_dashboard(status)
    elif not trader:
        st.info(
            "Nhập API Key + API Secret → nhấn **🟢 Kết nối & Bắt đầu**.\n\n"
            "Sau khi kết nối, nhấn **🔄 Cập nhật ngay** mỗi khi muốn kiểm tra thị trường và vào lệnh."
        )

    # Auto-rerun
    if st.session_state.get("live_active") and st.session_state.get("live_auto", False):
        time.sleep(refresh_sec)
        st.rerun()


def _render_live_dashboard(status: Dict):
    """Hiển thị dashboard giao dịch thực."""
    st.markdown("---")

    # Trạng thái kết nối
    if status["connected"]:
        status_color = "🟢" if not status["circuit_breaker"] else "🔴"
        status_text = status["status"] if not status["circuit_breaker"] else "NGẮT MẠCH — Dừng giao dịch"
        st.markdown(f"### {status_color} {status_text} | {status['symbol']} | Cập nhật: {status['last_update']}")
    else:
        st.markdown("### 🔴 Chưa kết nối")
        return

    # Thẻ chỉ số chính
    c1, c2, c3, c4, c5, c6 = st.columns(6)

    with c1:
        st.markdown(metric_card(
            "Giá hiện tại",
            f"${status['last_price']:,.2f}",
            "neutral",
        ), unsafe_allow_html=True)
    with c2:
        pnl = status["total_pnl_pct"]
        color = "positive" if pnl >= 0 else "negative"
        sign = "+" if pnl >= 0 else ""
        st.markdown(metric_card("Tổng PnL", f"{sign}{pnl:.2f}%", color), unsafe_allow_html=True)
    with c3:
        st.markdown(metric_card(
            "Vốn hiện tại",
            f"${status['current_equity']:,.2f}",
            "positive" if status['current_equity'] >= status['initial_equity'] else "negative",
        ), unsafe_allow_html=True)
    with c4:
        dd = status["drawdown_pct"]
        dd_color = "positive" if dd < 3 else "negative" if dd > 8 else "neutral"
        st.markdown(metric_card("Drawdown", f"-{dd:.2f}%", dd_color), unsafe_allow_html=True)
    with c5:
        dpnl = status["daily_pnl"]
        d_color = "positive" if dpnl >= 0 else "negative"
        d_sign = "+" if dpnl >= 0 else ""
        st.markdown(metric_card("PnL hôm nay", f"{d_sign}{dpnl:.2f}$", d_color), unsafe_allow_html=True)
    with c6:
        sig_text = "MUA" if status["last_signal"] == 1 else "—"
        sig_color = "positive" if status["last_signal"] == 1 else "neutral"
        st.markdown(metric_card("Tín hiệu", sig_text, sig_color), unsafe_allow_html=True)

    st.markdown("")

    # Thông tin bổ sung
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Vốn ban đầu", f"${status['initial_equity']:,.2f}")
    c2.metric("Đỉnh vốn", f"${status['peak_equity']:,.2f}")
    c3.metric("Lệnh mở", f"{status['open_positions']}/{config.MAX_OPEN_TRADES}")
    c4.metric("Tổng lệnh đã đóng", status["total_trades"])

    # Vị thế đang mở
    st.markdown("---")
    st.markdown("### 📌 Vị Thế Đang Mở")
    positions = status.get("positions", [])
    if positions:
        for pos in positions:
            entry_p = pos["entry_price"]
            unrealized = (status["last_price"] - entry_p) * pos["quantity"]
            unrealized_pct = ((status["last_price"] - entry_p) / entry_p) * 100
            u_sign = "+" if unrealized >= 0 else ""
            u_color = "🟢" if unrealized >= 0 else "🔴"

            with st.container():
                pc1, pc2, pc3, pc4, pc5, pc6 = st.columns(6)
                pc1.markdown(f"**{pos['id']}**")
                pc2.metric("Giá vào", f"${entry_p:,.2f}")
                pc3.metric("Số lượng", f"{pos['quantity']:.6f}")
                pc4.metric("TP", f"${pos['tp_price']:,.2f}")
                pc5.metric("SL", f"${pos['sl_price']:,.2f}")
                pc6.metric(f"{u_color} Lãi/Lỗ tạm",  f"{u_sign}{unrealized:.2f}$ ({u_sign}{unrealized_pct:.2f}%)")
    else:
        st.info("Không có vị thế đang mở.")

    # Lịch sử giao dịch
    history_file = os.path.join(config.OUTPUT_DIR, "lich_su_giao_dich_thuc.csv")
    if os.path.isfile(history_file):
        st.markdown("---")
        st.markdown("### 📋 Lịch Sử Giao Dịch Thực")
        hist_df = pd.read_csv(history_file)
        if not hist_df.empty:
            st.dataframe(hist_df.sort_index(ascending=False), use_container_width=True, height=300)

            csv_data = hist_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
            st.download_button(
                "📥 Tải lịch sử CSV",
                data=csv_data,
                file_name="lich_su_giao_dich_thuc.csv",
                mime="text/csv",
            )

    # Log
    st.markdown("---")
    st.markdown("### 📝 Nhật Ký Hoạt Động")
    logs = status.get("logs", [])
    if logs:
        log_text = "\n".join(reversed(logs[-30:]))
        st.code(log_text, language=None)
    else:
        st.info("Chưa có hoạt động nào.")


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    local_css()
    page = render_sidebar()

    if "🏠" in page:
        page_home()
    elif "📥" in page:
        page_download()
    elif "🔬" in page:
        page_backtest()
    elif "⚡" in page:
        page_optimize()
    elif "🔴" in page:
        page_live_trading()
    elif "📋" in page:
        page_results()


if __name__ == "__main__":
    main()
