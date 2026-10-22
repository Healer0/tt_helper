# SPDX-License-Identifier: GPL-3.0-only
"""PoC 0.3：验证 mss 能否截到微信小游戏画面（不黑屏、不冻结）。

用法（小游戏置于前台后运行）：
    python tools/poc/poc_capture.py
可选参数：
    --hwnd <十进制句柄>   指定窗口，默认取前台窗口
    --frames 30           抓取帧数（默认 30，间隔 0.1 秒共约 3 秒）
    --interval 0.1        帧间隔（秒）
    --out capture_out     输出目录（默认 capture_out）

判定标准：
    所有帧标准差 > 0 且颜色与肉眼一致；相邻帧差异明显（画面在动而非冻结帧）；
    单帧抓取耗时中位数 < 60ms（对应 Runtime.capture_budget 上限）。
失败处理：
    1) 微信设置里关闭“使用硬件加速”（或候选参数 --disable-gpu）后重启微信重测；
    2) 仍黑屏/花屏 → 需要换 dxcam / Windows Graphics Capture 后端（新增可选依赖）。
"""
import argparse
import statistics
import sys
import time
from pathlib import Path

import numpy as np


def grab_box(sct, box):
    shot = sct.grab({"left": box[0], "top": box[1], "width": box[2], "height": box[3]})
    return np.frombuffer(shot.rgb, np.uint8).reshape(shot.height, shot.width, 3)


def main():
    if sys.platform != "win32":
        print("本脚本需要 Windows。")
        return 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hwnd", type=int, default=0, help="目标窗口句柄；0 表示前台窗口")
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--interval", type=float, default=0.1)
    parser.add_argument("--out", default="capture_out")
    args = parser.parse_args()

    import ctypes as C
    from fisher.windows import enable_dpi_awareness, Windows

    enable_dpi_awareness()
    win = Windows()
    hwnd = args.hwnd or C.windll.user32.GetForegroundWindow()
    if not C.windll.user32.IsWindow(hwnd):
        print("无效窗口句柄。")
        return 1
    try:
        box = win.client_box(hwnd)
    except OSError as exc:
        print(f"无法取得窗口位置：{exc}")
        return 1
    print(f"目标窗口：{win.title(hwnd)}  区域 {box}")

    import mss
    import cv2
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    stats = []
    last = None
    with mss.mss() as sct:
        for i in range(args.frames):
            t0 = time.perf_counter()
            frame = grab_box(sct, box)
            elapsed = time.perf_counter() - t0
            stats.append((elapsed, float(frame.std()),
                          float(np.mean(frame < 16)), float(np.mean(frame > 240))))
            if i % 5 == 0:
                cv2.imwrite(str(out / f"frame_{i:03d}.png"), frame[:, :, ::-1])
            last = frame
            time.sleep(args.interval)
    # 关闭后重抓相邻帧，计算画面运动量（排除静态画面误判）。
    diffs = []
    with mss.mss() as sct:
        for _ in range(min(args.frames, 10)):
            t0 = time.perf_counter()
            cur = grab_box(sct, box)
            stats.append((time.perf_counter() - t0, float(cur.std()),
                          float(np.mean(cur < 16)), float(np.mean(cur > 240))))
            diffs.append(float(np.mean(np.abs(cur.astype(np.int16) - last.astype(np.int16)))))
            last = cur
            time.sleep(args.interval)

    times = [s[0] for s in stats]
    print(f"\n抓取耗时：中位数 {statistics.median(times)*1000:.1f}ms  最大 {max(times)*1000:.1f}ms"
          + ("  通过（<60ms）" if statistics.median(times) < 0.060 else "  超预算（>=60ms）"))
    stds = [s[1] for s in stats]
    print(f"帧标准差：最小 {min(stds):.1f}  最大 {max(stds):.1f}"
          + ("  通过（>0，非黑/白屏）" if min(stds) > 0 else "  失败（存在纯色帧）"))
    print(f"近黑像素比例：中位数 {statistics.median(s[2])*100:.1f}%   近白：{statistics.median(s[3])*100:.1f}%")
    print(f"相邻帧平均差：中位数 {statistics.median(diffs):.1f}"
          + ("  通过（画面在动）" if statistics.median(diffs) > 1 else "  注意：画面可能冻结"))
    print(f"样本帧已保存到 {out}/（每 5 帧一张，供 replay.py 离线验证）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
