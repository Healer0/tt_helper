# SPDX-License-Identifier: GPL-3.0-only
"""枚举微信窗口结构，不截图、不发送输入。

运行 python -m tools.poc.poc_windows，或 python tools/poc/poc_windows.py。
默认仅打印微信相关窗口；--all 才包括其他应用。固定父窗口内的游戏区域可先用 crop。
"""
import argparse
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.poc.common import DiagnosticWindows, is_wechat
from fisher.windows import enable_dpi_awareness


def print_window(info, prefix=""):
    left, top, width, height = info["box"]
    print(f'{prefix}hwnd={info["hwnd"]}  {info["class"]}  {info["process"]}  '
          f'{width}x{height} @ ({left},{top})  {info["title"]}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="包括其他应用的窗口标题")
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        print("本脚本需要 Windows。")
        return 1
    enable_dpi_awareness()
    win = DiagnosticWindows()
    rows = sorted(win.diagnostic_windows(), key=lambda item: (item["process"], item["title"]))
    selected = [info for info in rows if args.all or is_wechat(info)]
    print(f"共 {len(selected)} 个匹配的可见窗口：")
    for info in selected:
        print_window(info)
        if is_wechat(info):
            for child in win.diagnostic_windows(info["hwnd"]):
                print_window(child, "    child ")
    if not selected:
        print("未找到微信游戏窗口，请打开小游戏后重试。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
