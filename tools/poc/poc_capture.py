# SPDX-License-Identifier: GPL-3.0-only
"""验证 mss 的微信画面、运动量和截图耗时；保存样本，不发送输入。

运行 python -m tools.poc.poc_capture --hwnd 十进制句柄 --out snapshots。
也支持直接脚本路径。倒计时后确认目标，F9/Esc 取消；截图时保持游戏可见。
退出码 1 表示异常、纯色、冻结或超预算；正确画面仍需人工核对。
"""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from tools.poc.common import (DiagnosticWindows, cancelled, finite_float, positive_int,
                              resolve_target, screen_box, wait_for)
from fisher.windows import enable_dpi_awareness
from fisher.vision import write_image


def grab_box(sct, box):
    shot = sct.grab(screen_box(box))
    return np.frombuffer(shot.rgb, np.uint8).reshape(shot.height, shot.width, 3)


def capture_frames(win, args):
    import mss
    stop = lambda: cancelled(win)
    print(f"{args.countdown:g} 秒后确认截图目标；请切回小游戏，F9/Esc 取消。")
    if not wait_for(args.countdown, stop):
        raise OSError("已取消截图")
    hwnd, box = resolve_target(win, args.hwnd)
    print(f"目标窗口：{win.title(hwnd)}  区域 {box}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stats, diffs = [], []
    last = None
    with mss.mss() as sct:
        for index in range(args.frames):
            if stop() or not win.foreground_matches(hwnd) or win.client_box(hwnd) != box:
                raise OSError("目标焦点、位置或尺寸变化，已停止截图")
            started = time.perf_counter()
            frame = grab_box(sct, box)
            elapsed = time.perf_counter() - started
            stats.append((elapsed, float(frame.std()), float(np.mean(frame < 16)),
                          float(np.mean(frame > 240))))
            if last is not None:
                diffs.append(float(np.mean(np.abs(frame.astype(np.int16) - last.astype(np.int16)))))
            if index % 5 == 0:
                write_image(out / f"frame_{index:03d}.png", frame[:, :, ::-1])
            last = frame
            if index + 1 < args.frames and not wait_for(args.interval, stop):
                raise OSError("已取消后续截图")
    report = {"frames": len(stats), "median_ms": statistics.median(s[0] for s in stats)*1000,
              "max_ms": max(s[0] for s in stats)*1000, "min_std": min(s[1] for s in stats),
              "median_frame_difference": statistics.median(diffs),
              "median_dark_fraction": statistics.median(s[2] for s in stats),
              "median_white_fraction": statistics.median(s[3] for s in stats)}
    report["passed"] = (report["median_ms"] < 60 and report["min_std"] > 0
                        and report["median_frame_difference"] > 1)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"样本帧和统计已保存到 {out}；请核对画面内容及各阶段识别。")
    return 0 if report["passed"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hwnd", type=positive_int, default=0)
    parser.add_argument("--frames", type=positive_int, default=30)
    parser.add_argument("--interval", type=finite_float, default=.1)
    parser.add_argument("--countdown", type=finite_float, default=5)
    parser.add_argument("--out", default="snapshots")
    args = parser.parse_args(argv)
    if args.frames < 2 or not .01 <= args.interval <= 10 or not 0 <= args.countdown <= 60:
        parser.error("frames 须 >=2，interval 须为 0.01～10 秒，countdown 须为 0～60 秒")
    if sys.platform != "win32":
        print("本脚本需要 Windows。")
        return 1
    enable_dpi_awareness()
    try:
        return capture_frames(DiagnosticWindows(), args)
    except (OSError, ValueError) as exc:
        print(f"未通过：{exc}")
        return 1
    except KeyboardInterrupt:
        print("已取消截图。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
