# SPDX-License-Identifier: GPL-3.0-only
"""验证微信点击响应；会真实点击。默认倒计时后取前台微信窗口，F9/Esc 取消。

从仓库根目录运行：python -m tools.poc.poc_click --hwnd 十进制句柄 --n 1
也支持 python tools/poc/poc_click.py。X/Y 相对整个窗口客户区，不是 Runtime 的 crop。
"""
import argparse
from pathlib import Path
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.poc.common import (DiagnosticWindows, cancelled, finite_float, normalized,
                              positive_int, resolve_target, screen_box, wait_for)
from fisher.windows import enable_dpi_awareness


def run_clicks(win, args):
    print(f"{args.countdown:g} 秒后确认目标并点击；请切回小游戏，F9/Esc 取消。")
    stop = lambda: cancelled(win)
    if not wait_for(args.countdown, stop):
        raise OSError("已取消，未发送点击")
    hwnd, original = resolve_target(win, args.hwnd)
    print(f"目标窗口：{win.title(hwnd)}  区域 {original}")

    def guard():
        return win.client_box(hwnd) == original

    for index in range(args.n):
        if stop() or not win.foreground_matches(hwnd) or not guard():
            raise OSError("目标焦点、位置或尺寸变化，已停止点击")
        started = time.perf_counter()
        sent = win.click_at(hwnd, screen_box(original), args.x, args.y, args.hold, stop, guard,
                            jitter_ratio=getattr(args, "jitter_percent", 1.5)/100)
        if not sent or win.interrupted:
            raise OSError("点击已取消或目标失焦，已停止后续输入")
        print(f"第 {index+1}/{args.n} 次点击已发送（耗时 {time.perf_counter()-started:.3f}s）")
        if index + 1 < args.n and not wait_for(2, stop):
            raise OSError("已取消后续点击")
    print("请人工确认游戏阶段是否变化，并记录响应延迟；发送成功不代表游戏已接收。")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hwnd", type=positive_int, default=0)
    parser.add_argument("--n", type=positive_int, default=1)
    parser.add_argument("--x", type=normalized, default=.5)
    parser.add_argument("--y", type=normalized, default=.5)
    parser.add_argument("--hold", type=finite_float, default=30)
    parser.add_argument("--jitter-percent", type=finite_float, default=1.5,
                        help="随机半径占客户区短边的百分比（0～5，0关闭）")
    parser.add_argument("--countdown", type=finite_float, default=5)
    args = parser.parse_args(argv)
    if not 10 <= args.hold <= 150 or not 0 <= args.countdown <= 60 or not 0 <= args.jitter_percent <= 5:
        parser.error("hold 须为 10～150 毫秒，countdown 须为 0～60 秒，jitter-percent 须为 0～5")
    if sys.platform != "win32":
        print("本脚本需要 Windows。")
        return 1
    enable_dpi_awareness()
    try:
        run_clicks(DiagnosticWindows(), args)
    except (OSError, ValueError) as exc:
        print(f"未通过：{exc}")
        return 1
    except KeyboardInterrupt:
        print("已取消点击。")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
