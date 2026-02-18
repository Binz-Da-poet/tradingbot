"""
Tối ưu tham số chiến lược bằng Grid Search.

Tìm kiếm tổ hợp tham số tốt nhất dựa trên tỷ số Sharpe.
Sử dụng multiprocessing để chạy song song.
"""

import itertools
import multiprocessing as mp
from functools import partial
from typing import Dict, List, Tuple

import pandas as pd
import numpy as np

from core.data_handler import compute_indicators
from core.strategy import generate_signals
from core.backtester import Backtester, BacktestParams
from core.metrics import calculate_metrics
import config


def _run_single_backtest(
    param_combo: Tuple,
    base_df: pd.DataFrame,
    initial_capital: float,
) -> Dict:
    """
    Chạy một backtest với bộ tham số cụ thể.
    Được gọi bởi worker trong pool đa tiến trình.

    Trả về dict chứa tham số + kết quả hiệu suất.
    """
    ema_fast, ema_slow, tp_pct, sl_pct = param_combo

    # Bỏ qua tổ hợp không hợp lệ
    if ema_fast >= ema_slow:
        return None

    try:
        # Tính chỉ báo với tham số mới
        df = compute_indicators(
            base_df.copy(),
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            rsi_period=config.RSI_PERIOD,
        )

        # Tạo tín hiệu
        df = generate_signals(
            df,
            rsi_threshold=config.RSI_THRESHOLD,
            use_rsi_filter=config.USE_RSI_FILTER,
        )

        # Chạy backtest
        params = BacktestParams(
            initial_capital=initial_capital,
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
        trade_log, equity_curve = bt.run(df, silent=True)

        # Tính chỉ số hiệu suất
        metrics = calculate_metrics(trade_log, equity_curve, initial_capital)

        return {
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "tp_pct": tp_pct,
            "sl_pct": sl_pct,
            "sharpe": metrics["ty_so_sharpe"],
            "loi_nhuan_pct": metrics["tong_loi_nhuan_pct"],
            "ty_le_thang": metrics["ty_le_thang"],
            "drawdown_pct": metrics["drawdown_toi_da_pct"],
            "so_lenh": metrics["tong_so_lenh"],
            "profit_factor": metrics["profit_factor"],
        }
    except Exception:
        return None


# Hàm wrapper cấp module cho pickle (multiprocessing yêu cầu)
def _worker(args):
    """Wrapper để multiprocessing có thể serialize."""
    param_combo, base_df_bytes, initial_capital = args
    base_df = pd.read_pickle(base_df_bytes)
    return _run_single_backtest(param_combo, base_df, initial_capital)


def run_grid_search(
    base_df: pd.DataFrame,
    initial_capital: float = None,
    ema_fast_range=None,
    ema_slow_range=None,
    tp_values=None,
    sl_values=None,
    n_workers: int = None,
) -> Tuple[Dict, pd.DataFrame]:
    """
    Chạy grid search để tìm tham số tốt nhất.

    Tham số:
        base_df: DataFrame gốc (chưa tính chỉ báo, chỉ có OHLCV)
        initial_capital: vốn ban đầu
        ema_fast_range: dải EMA nhanh
        ema_slow_range: dải EMA chậm
        tp_values: danh sách giá trị TP
        sl_values: danh sách giá trị SL
        n_workers: số tiến trình song song (mặc định = số CPU)

    Trả về:
        (tham_số_tốt_nhất: dict, bảng_kết_quả: DataFrame)
    """
    if initial_capital is None:
        initial_capital = config.INITIAL_CAPITAL
    if ema_fast_range is None:
        ema_fast_range = config.OPTIMIZE_EMA_FAST_RANGE
    if ema_slow_range is None:
        ema_slow_range = config.OPTIMIZE_EMA_SLOW_RANGE
    if tp_values is None:
        tp_values = config.OPTIMIZE_TP_VALUES
    if sl_values is None:
        sl_values = config.OPTIMIZE_SL_VALUES
    if n_workers is None:
        n_workers = max(1, mp.cpu_count() - 1)

    # Tạo tất cả tổ hợp tham số
    all_combos = list(itertools.product(
        ema_fast_range, ema_slow_range, tp_values, sl_values
    ))

    # Lọc bỏ tổ hợp không hợp lệ
    valid_combos = [(f, s, t, l) for f, s, t, l in all_combos if f < s]

    print(f"\n{'═' * 50}")
    print(f"  TỐI ƯU THAM SỐ - GRID SEARCH")
    print(f"{'═' * 50}")
    print(f"  Tổng tổ hợp hợp lệ: {len(valid_combos)}")
    print(f"  Số tiến trình: {n_workers}")
    print(f"  EMA nhanh: {list(ema_fast_range)}")
    print(f"  EMA chậm: {list(ema_slow_range)}")
    print(f"  TP: {tp_values}")
    print(f"  SL: {sl_values}")
    print(f"{'─' * 50}")

    # Lưu DataFrame tạm thời cho multiprocessing
    import tempfile, io
    buffer = io.BytesIO()
    base_df.to_pickle(buffer)
    buffer.seek(0)
    df_bytes = buffer

    # Chạy tuần tự nếu ít tổ hợp, song song nếu nhiều
    results = []
    if len(valid_combos) <= 50 or n_workers <= 1:
        # Chạy tuần tự
        for i, combo in enumerate(valid_combos):
            result = _run_single_backtest(combo, base_df, initial_capital)
            if result is not None:
                results.append(result)
            if (i + 1) % 100 == 0 or (i + 1) == len(valid_combos):
                print(f"  Tiến trình: {i + 1}/{len(valid_combos)} "
                      f"({(i + 1) / len(valid_combos) * 100:.0f}%)")
    else:
        # Chạy song song
        import io as _io

        # Dùng cách tiếp cận đơn giản hơn: chia batch
        batch_size = max(1, len(valid_combos) // (n_workers * 4))
        completed = 0

        with mp.Pool(processes=n_workers) as pool:
            func = partial(
                _run_single_backtest,
                base_df=base_df,
                initial_capital=initial_capital,
            )
            for result in pool.imap_unordered(func, valid_combos, chunksize=batch_size):
                if result is not None:
                    results.append(result)
                completed += 1
                if completed % 500 == 0 or completed == len(valid_combos):
                    print(f"  Tiến trình: {completed}/{len(valid_combos)} "
                          f"({completed / len(valid_combos) * 100:.0f}%)")

    if not results:
        print("  [Cảnh báo] Không có kết quả nào hợp lệ từ grid search!")
        return {}, pd.DataFrame()

    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values("sharpe", ascending=False).reset_index(drop=True)

    # In top 10 kết quả
    print(f"\n{'─' * 50}")
    print(f"  TOP 10 TỔ HỢP THAM SỐ (theo Tỷ số Sharpe)")
    print(f"{'─' * 50}")
    print(f"  {'#':>3} {'EMA_F':>5} {'EMA_S':>5} {'TP%':>6} {'SL%':>6} "
          f"{'Sharpe':>7} {'LN%':>7} {'Thắng%':>7} {'DD%':>6} {'Lệnh':>5}")
    print(f"  {'─' * 63}")

    for i, row in results_df.head(10).iterrows():
        print(f"  {i + 1:>3} {row['ema_fast']:>5.0f} {row['ema_slow']:>5.0f} "
              f"{row['tp_pct'] * 100:>5.1f}% {row['sl_pct'] * 100:>5.1f}% "
              f"{row['sharpe']:>7.2f} {row['loi_nhuan_pct']:>6.2f}% "
              f"{row['ty_le_thang']:>6.1f}% {row['drawdown_pct']:>5.1f}% "
              f"{row['so_lenh']:>5.0f}")

    print(f"{'═' * 50}")

    # Trả về bộ tham số tốt nhất
    best = results_df.iloc[0]
    best_params = {
        "ema_fast": int(best["ema_fast"]),
        "ema_slow": int(best["ema_slow"]),
        "tp_pct": float(best["tp_pct"]),
        "sl_pct": float(best["sl_pct"]),
    }

    print(f"\n  Tham số tốt nhất:")
    print(f"    EMA nhanh = {best_params['ema_fast']}")
    print(f"    EMA chậm  = {best_params['ema_slow']}")
    print(f"    Chốt lời  = {best_params['tp_pct'] * 100:.1f}%")
    print(f"    Cắt lỗ    = {best_params['sl_pct'] * 100:.1f}%")
    print(f"    Sharpe    = {best['sharpe']:.2f}")
    print()

    return best_params, results_df
