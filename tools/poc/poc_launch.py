# SPDX-License-Identifier: GPL-3.0-only
"""定位微信并按需启动；不会点击或截图。候选启动参数的效果需实测。

运行 python -m tools.poc.poc_launch --no-launch 只定位，不启动。
运行 python -m tools.poc.poc_launch --args=--disable-gpu 会启动微信。
也支持直接脚本路径。--exe 可显式指定微信路径，F9/Esc 结束后续窗口枚举。
"""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.poc.common import DiagnosticWindows, cancelled, is_wechat, wait_for
from fisher.windows import enable_dpi_awareness


def find_wechat_exe():
    import winreg
    candidates = []
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        for folder in ("WeChat", "Weixin"):
            candidates.extend(Path(base) / "Tencent" / folder / name for name in ("WeChat.exe", "Weixin.exe"))
    keys = [(root, prefix + family) for root, prefix in (
        (winreg.HKEY_CURRENT_USER, "Software\\Tencent\\"),
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\Tencent\\"),
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\Tencent\\"))
        for family in ("WeChat", "Weixin")]
    for root, sub in keys:
        try:
            with winreg.OpenKey(root, sub) as key:
                value, _ = winreg.QueryValueEx(key, "InstallPath")
                candidates.extend(Path(value) / name for name in ("WeChat.exe", "Weixin.exe"))
        except OSError:
            continue
    return next((path for path in candidates if path.is_file()), None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, help="显式指定微信可执行文件")
    parser.add_argument("--args", default="", help="候选启动参数，例如 --args=--disable-gpu")
    parser.add_argument("--no-launch", action="store_true", help="只定位并打印路径")
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        print("本脚本需要 Windows。")
        return 1
    exe = args.exe or find_wechat_exe()
    if not exe or not exe.is_file():
        print("未找到微信，请用 --exe 指定路径。")
        return 1
    print(f"定位到微信：{exe}")
    if args.no_launch:
        return 0
    try:
        cmd = [str(exe)] + shlex.split(args.args)
        subprocess.Popen(cmd, close_fds=True)
        enable_dpi_awareness()
        win = DiagnosticWindows()
        stop = lambda: cancelled(win)
        print("等待 8 秒后枚举微信窗口，共 20 秒；请打开小游戏，F9/Esc 取消枚举。")
        if not wait_for(8, stop):
            return 130
        seen = set()
        for round_no in range(10):
            rows = [info for info in win.diagnostic_windows() if is_wechat(info)]
            for info in rows:
                if info["hwnd"] not in seen:
                    print(f'  +{round_no*2}s hwnd={info["hwnd"]}  {info["process"]}  {info["title"]}')
            seen.update(info["hwnd"] for info in rows)
            if not wait_for(2, stop):
                return 130
    except (OSError, ValueError) as exc:
        print(f"启动或枚举失败：{exc}")
        return 1
    except KeyboardInterrupt:
        return 130
    print("枚举结束；无独立窗口时先验证父窗口内的现有 crop，再决定是否扩展区域定位。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
