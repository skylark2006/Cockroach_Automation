# -*- coding: utf-8 -*-
"""D1 实时力曲线窗口。

不打开传感器串口，只读取 ForceSensor 写出的 CSV。
用法：
  python tools/drill_plot/force_plot.py --watch runtime/motion_logs
  python tools/drill_plot/force_plot.py --csv runtime/motion_logs/sensor_xxx.csv
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def read_csv(path: Path):
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return [], []
    times, values = [], []
    for row in csv.DictReader(lines):
        try:
            mono = float(row["monotonic"])
            raw = float(row["raw"])
        except Exception:
            continue
        times.append(mono)
        values.append(raw)
    if not times:
        return [], []
    base = times[0]
    return [t - base for t in times], values


def detect_drop(values):
    if len(values) < 3:
        return None, 0.0
    peak = values[0]
    max_drop = 0.0
    index = None
    for i, value in enumerate(values):
        if value > peak:
            peak = value
        drop = peak - value
        if drop > max_drop:
            max_drop = drop
            index = i
    value_range = max(values) - min(values)
    threshold = max(5.0, 0.05 * value_range)
    if max_drop >= threshold:
        return index, max_drop
    return None, max_drop


def newest_new_csv(directory: Path, known: set[Path]):
    try:
        files = sorted(directory.glob("sensor_*.csv"), key=lambda p: p.stat().st_mtime)
    except Exception:
        return None
    for path in files:
        if path not in known:
            known.add(path)
            return path
    return None


def main():
    parser = argparse.ArgumentParser(description="D1 实时力曲线")
    parser.add_argument("--watch", help="监视目录，等待新的 sensor_*.csv")
    parser.add_argument("--csv", help="直接读取指定 CSV")
    parser.add_argument("--interval", type=float, default=0.2)
    args = parser.parse_args()

    watch_dir = Path(args.watch) if args.watch else None
    if watch_dir:
        watch_dir.mkdir(parents=True, exist_ok=True)
    current = Path(args.csv) if args.csv else None
    known: set[Path] = set()
    if watch_dir and current is None:
        known = set(watch_dir.glob("sensor_*.csv"))

    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(9.0, 6.0),
        gridspec_kw={"height_ratios": [2.2, 1.0]},
    )
    fig.subplots_adjust(left=0.08, right=0.97, top=0.92, bottom=0.08, hspace=0.35)
    fig.canvas.manager.set_window_title("D1 实时力曲线")

    line, = ax.plot([], [], color="#1677ff", lw=1.6)
    marker = ax.axvline(0, color="#d4380d", lw=1.5, ls="--", visible=False)
    ax.set_xlabel("时间 / s")
    ax.set_ylabel("raw")
    ax.grid(True, alpha=0.25)
    status = ax.text(0.01, 0.98, "等待 D1 新的 sensor CSV...", transform=ax.transAxes,
                     va="top", ha="left", fontsize=10, color="#666666")

    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1)
    ax2.axis("off")
    ax2.set_title("穿刺示意（按时间近似，不是真实图像）", fontsize=9)
    sample_patch = Rectangle((0.24, 0.14), 0.52, 0.26, facecolor="#d9c7a3", edgecolor="#8c6b3f")
    ax2.add_patch(sample_patch)
    ax2.add_patch(Rectangle((0.47, 0.14), 0.06, 0.26, facecolor="white", edgecolor="#8c6b3f"))
    bit_line, = ax2.plot([0.5, 0.5], [0.84, 0.94], color="#555555", lw=5)
    bit_tip, = ax2.plot([0.5], [0.84], marker="v", color="#555555", markersize=8)
    force_text = ax2.text(0.04, 0.92, "force: -", transform=ax2.transAxes, fontsize=10)
    phase_text = ax2.text(0.04, 0.78, "等待数据", transform=ax2.transAxes, fontsize=10)

    win = fig.canvas.manager.window
    try:
        win.attributes("-topmost", True)
        win.geometry("+60+60")
        win.lift()
    except Exception:
        pass

    last_size = -1
    last_values = []
    last_times = []

    while plt.fignum_exists(fig.number):
        if watch_dir and current is None:
            new_path = newest_new_csv(watch_dir, known)
            if new_path is not None:
                current = new_path
                last_size = -1
                last_times = []
                last_values = []
                marker.set_visible(False)
                sample_patch.set_facecolor("#d9c7a3")
                phase_text.set_text("等待数据")
                status.set_text(f"已连接：{current.name}")
        if current is not None:
            try:
                size = current.stat().st_size
            except Exception:
                size = -1
            if size != last_size:
                last_size = size
                last_times, last_values = read_csv(current)
                if last_times:
                    line.set_data(last_times, last_values)
                    x_end = max(10.0, last_times[-1] + 1.0)
                    ax.set_xlim(max(0.0, x_end - 12.0), x_end)
                    vmin, vmax = min(last_values), max(last_values)
                    margin = max(2.0, (vmax - vmin) * 0.12)
                    ax.set_ylim(vmin - margin, vmax + margin)
                    drop_index, drop_value = detect_drop(last_values)
                    if drop_index is not None:
                        marker.set_xdata([last_times[drop_index], last_times[drop_index]])
                        marker.set_visible(True)
                        status.set_text(f"疑似刺穿：t={last_times[drop_index]:.2f}s，跌落={drop_value:.1f}")
                        sample_patch.set_facecolor("#f4b6a6")
                        phase_text.set_text("疑似刺穿")
                    else:
                        marker.set_visible(False)
                        status.set_text(f"D1 运行中：{current.name}")
                        phase_text.set_text("下钻中")
                    force_text.set_text(f"force: {last_values[-1]:.1f}")
                    elapsed = last_times[-1]
                    bit_y = max(0.40, 0.84 - min(1.0, elapsed / 6.0) * 0.44)
                    bit_line.set_ydata([bit_y, 0.94])
                    bit_tip.set_ydata([bit_y])
                    fig.canvas.draw_idle()
        plt.pause(args.interval)

    plt.close(fig)


if __name__ == "__main__":
    main()
