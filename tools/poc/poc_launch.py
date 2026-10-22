# SPDX-License-Identifier: GPL-3.0-only
"""PoC 0.2：定位微信并尝试以候选参数启动，观察小游戏是否以无边框独立窗口弹出。

适用场景：poc_windows.py 判定为结果 B（小游戏无独立 HWND，只是主窗口内的一块像素）。

用法（先完全退出微信）：
    python tools/poc/poc_launch.py [--args "--disable-gpu"] [--no-launch]

脚本会：
    1) 从常见路径与注册表定位 WeChat.exe（或 Weixin.exe）；
    2) 用给定参数启动微信（默认不带参数，仅打印路径）；
    3) 每 2 秒枚举一次窗口，共 20 秒，打印新增的含“微信/小游戏”的窗口。

候选参数按经验整理、以实测为准，可逐个尝试：
    --disable-gpu         关闭硬件加速（若截屏黑屏，重点试这个）
    --disable-software-rasterizer
    --mini-program-window-style=immersive
    --force-device-scale-factor=1
启动后请手动打开小游戏，再用 poc_windows.py 确认窗口结构。
此脚本只启动与枚举，不做判定，也不修改任何现有代码。
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

import winreg


def find_wechat_exe():
    candidates = [
        Path(r"C:\Program Files\Tencent\WeChat\WeChat.exe"),
        Path(r"C:\Program Files (x86)\Tencent\WeChat\WeChat.exe"),
        Path(r"C:\Program Files\Tencent\WeChat\Weixin.exe"),
        Path(r"C:\Program Files (x86)\Tencent\WeChat\Weixin.exe"),
    ]
    for path in candidates:
        if path.is_file():
            return path
    keys = [
        (winreg.HKEY_CURRENT_USER, r"Software\Tencent\WeChat"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Tencent\WeChat"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Tencent\WeChat"),
    ]
    for root, sub in keys:
        try:
            with winreg.OpenKey(root, sub) as key:
                value, _ = winreg.QueryValueEx(key, "InstallPath")
                for name in ("WeChat.exe", "Weixin.exe"):
                    path = Path(value) / name
                    if path.is_file():
                        return path
        except OSError:
            continue
    return None


def main():
    if sys.platform != "win32":
        print("本脚本需要 Windows。")
        return 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--args", default="", help="附加启动参数（用引号包裹）")
    parser.add_argument("--no-launch", action="store_true", help="只定位并打印路径，不启动")
    args = parser.parse_args()

    exe = find_wechat_exe()
    if not exe:
        print("未找到 WeChat.exe。请手动指定路径后重试，或检查是否使用了商店版微信。")
        return 1
    print(f"定位到微信：{exe}")
    if args.no_launch:
        return 0
    cmd = [str(exe)] + (args.args.split() if args.args.strip() else [])
    print(f"启动命令：{' '.join(cmd)}")
    subprocess.Popen(cmd, close_fds=True)
    print("等待 8 秒后开始枚举窗口（共 20 秒），请在此期间打开小游戏…")
    time.sleep(8)
    seen = set()
    for round_no in range(10):
        try:
            from fisher.windows import enable_dpi_awareness, Windows
            enable_dpi_awareness()
            win = Windows()
            rows = win.windows("wechat", include_other=True)
        except ValueError:
            rows = win.windows("ldplayer", include_other=True)
        fresh = [(hwnd, title) for hwnd, title in rows if hwnd not in seen]
        seen.update(hwnd for hwnd, _ in rows)
        if fresh:
            print(f"  +{round_no * 2}s 新增窗口：")
            for hwnd, title in fresh:
                print(f"      hwnd={hwnd}  {title}")
        else:
            print(f"  +{round_no * 2}s 无新增窗口")
        time.sleep(2)
    print("枚举结束。若小游戏无独立窗口，请换启动参数重试；全部失败则需在方案中引入 game_rect 偏移支持。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
