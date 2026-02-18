"""
Phân tích hiệu suất giao dịch.

Tính toán các chỉ số:
- Tổng lợi nhuận
- Tỷ lệ thắng
- Profit Factor
- Drawdown tối đa
- Tỷ số Sharpe
Vẽ biểu đồ đường vốn và xuất nhật ký giao dịch.
"""

import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")  # Backend không cần GUI
import matplotlib.pyplot as plt


def calculate_metrics(
    trade_log: pd.DataFrame,
    equity_curve: pd.DataFrame,
    initial_capital: float,
) -> dict:
    """
    Tính toán tất cả chỉ số hiệu suất.

    Trả về dict với các chỉ số chính.
    """
    metrics = {}

    # --- Thống kê cơ bản ---
    total_trades = len(trade_log)
    metrics["tong_so_lenh"] = total_trades

    if total_trades == 0:
        metrics["tong_loi_nhuan_pct"] = 0.0
        metrics["ty_le_thang"] = 0.0
        metrics["profit_factor"] = 0.0
        metrics["drawdown_toi_da_pct"] = 0.0
        metrics["ty_so_sharpe"] = 0.0
        metrics["tong_phi"] = 0.0
        metrics["so_lenh_thang"] = 0
        metrics["so_lenh_thua"] = 0
        metrics["von_cuoi"] = initial_capital
        return metrics

    # --- Tổng lợi nhuận ---
    final_equity = equity_curve["equity"].iloc[-1]
    total_return = (final_equity - initial_capital) / initial_capital
    metrics["tong_loi_nhuan_pct"] = round(total_return * 100, 2)
    metrics["von_cuoi"] = round(final_equity, 2)

    # --- Tỷ lệ thắng ---
    winning = trade_log[trade_log["lai_lo"] > 0]
    losing = trade_log[trade_log["lai_lo"] <= 0]
    metrics["so_lenh_thang"] = len(winning)
    metrics["so_lenh_thua"] = len(losing)
    metrics["ty_le_thang"] = round(
        (len(winning) / total_trades) * 100, 2
    ) if total_trades > 0 else 0.0

    # --- Profit Factor ---
    gross_profit = winning["lai_lo"].sum() if len(winning) > 0 else 0
    gross_loss = abs(losing["lai_lo"].sum()) if len(losing) > 0 else 0
    metrics["profit_factor"] = round(
        gross_profit / gross_loss, 2
    ) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0

    # --- Tổng phí ---
    metrics["tong_phi"] = round(trade_log["phi"].sum(), 2)

    # --- Drawdown tối đa ---
    equity_series = equity_curve["equity"]
    peak = equity_series.cummax()
    drawdown = (peak - equity_series) / peak
    metrics["drawdown_toi_da_pct"] = round(drawdown.max() * 100, 2)

    # --- Tỷ số Sharpe (năm hóa) ---
    # Tính lợi nhuận theo từng bước thời gian
    returns = equity_series.pct_change().dropna()
    if len(returns) > 1 and returns.std() > 0:
        # Giả sử dữ liệu 1 phút → 525,600 phút/năm
        minutes_per_year = 525_600
        sharpe = (returns.mean() / returns.std()) * np.sqrt(minutes_per_year)
        metrics["ty_so_sharpe"] = round(sharpe, 2)
    else:
        metrics["ty_so_sharpe"] = 0.0

    # --- Lãi/lỗ trung bình ---
    metrics["lai_tb_lenh_thang"] = round(
        winning["lai_lo"].mean(), 2
    ) if len(winning) > 0 else 0.0
    metrics["lo_tb_lenh_thua"] = round(
        losing["lai_lo"].mean(), 2
    ) if len(losing) > 0 else 0.0

    return metrics


def print_summary(metrics: dict):
    """In bảng báo cáo hiệu suất ra console."""
    print()
    print("═" * 50)
    print("        BÁO CÁO HIỆU SUẤT GIAO DỊCH")
    print("═" * 50)

    total_return = metrics.get("tong_loi_nhuan_pct", 0)
    sign = "+" if total_return >= 0 else ""

    print(f"  Vốn cuối:              {metrics.get('von_cuoi', 0):>12,.2f} USD")
    print(f"  Tổng lợi nhuận:        {sign}{total_return:>11.2f}%")
    print(f"  Tổng số lệnh:          {metrics.get('tong_so_lenh', 0):>12}")
    print(f"  Số lệnh thắng:         {metrics.get('so_lenh_thang', 0):>12}")
    print(f"  Số lệnh thua:          {metrics.get('so_lenh_thua', 0):>12}")
    print(f"  Tỷ lệ thắng:           {metrics.get('ty_le_thang', 0):>11.2f}%")
    print(f"  Profit Factor:         {metrics.get('profit_factor', 0):>12.2f}")
    print(f"  Drawdown tối đa:       {metrics.get('drawdown_toi_da_pct', 0):>11.2f}%")
    print(f"  Tỷ số Sharpe:          {metrics.get('ty_so_sharpe', 0):>12.2f}")
    print(f"  Lãi TB lệnh thắng:    {metrics.get('lai_tb_lenh_thang', 0):>12.2f} USD")
    print(f"  Lỗ TB lệnh thua:      {metrics.get('lo_tb_lenh_thua', 0):>12.2f} USD")
    print(f"  Tổng phí giao dịch:   {metrics.get('tong_phi', 0):>12.2f} USD")
    print("═" * 50)
    print()


def plot_equity_curve(
    equity_curve: pd.DataFrame,
    save_path: str,
    title: str = "Biểu Đồ Đường Vốn",
):
    """Vẽ và lưu biểu đồ đường vốn."""
    if equity_curve.empty:
        print("  [Biểu đồ] Không có dữ liệu để vẽ.")
        return

    os.makedirs(os.path.dirname(save_path) if os.path.dirname(save_path) else ".", exist_ok=True)

    fig, axes = plt.subplots(2, 1, figsize=(14, 8), gridspec_kw={"height_ratios": [3, 1]})

    # --- Biểu đồ đường vốn ---
    ax1 = axes[0]
    ax1.plot(
        equity_curve["timestamp"],
        equity_curve["equity"],
        color="#2196F3",
        linewidth=1.0,
        label="Vốn (USD)",
    )
    ax1.fill_between(
        equity_curve["timestamp"],
        equity_curve["equity"],
        alpha=0.1,
        color="#2196F3",
    )
    ax1.set_title(title, fontsize=14, fontweight="bold")
    ax1.set_ylabel("Vốn (USD)", fontsize=11)
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.3)

    # --- Biểu đồ drawdown ---
    ax2 = axes[1]
    equity_series = equity_curve["equity"]
    peak = equity_series.cummax()
    drawdown_pct = ((peak - equity_series) / peak) * 100

    ax2.fill_between(
        equity_curve["timestamp"],
        drawdown_pct,
        color="#F44336",
        alpha=0.4,
    )
    ax2.set_title("Drawdown (%)", fontsize=12)
    ax2.set_ylabel("Drawdown (%)", fontsize=11)
    ax2.set_xlabel("Thời gian", fontsize=11)
    ax2.grid(True, alpha=0.3)
    ax2.invert_yaxis()

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [Biểu đồ] Đã lưu biểu đồ đường vốn tại: {save_path}")


def export_trade_log(trade_log: pd.DataFrame, save_path: str):
    """Xuất nhật ký giao dịch ra file CSV."""
    os.makedirs(os.path.dirname(save_path) if os.path.dirname(save_path) else ".", exist_ok=True)
    trade_log.to_csv(save_path, index=False, encoding="utf-8-sig")
    print(f"  [Nhật ký] Đã xuất {len(trade_log)} lệnh ra: {save_path}")
