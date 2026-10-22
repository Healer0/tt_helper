# SPDX-License-Identifier: GPL-3.0-only
"""PoC 0.1：枚举微信小游戏窗口，确认是否存在 client 区等于游戏画面的独立 HWND。

用法（Windows 上打开微信并进入小游戏后运行）：
    python tools/poc/poc_windows.py

输出每行：hwnd / 类名 / 进程名 / 标题 / client 区；并对含“微信”的窗口追加子窗口列表。
判定标准：
    结果 A：存在 client 区恰好等于小游戏画面的稳定 HWND（后续可直接复用现有框选流程）。
    结果 B：小游戏只是微信主窗口 client 区内的一块像素（无独立 HWND），
            继续跑 poc_launch.py 尝试沉浸式窗口参数。
诊断脚本不进入发布包，也不修改任何现有代码。
"""
import ctypes as C
from ctypes import wintypes as T
import sys


def enable_dpi_awareness():
    try:
        C.windll.user32.SetProcessDpiAwarenessContext(C.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            C.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            C.windll.user32.SetProcessDPIAware()


def process_name(pid):
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = C.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return "?"
    try:
        buf = C.create_unicode_buffer(1024)
        size = T.DWORD(len(buf))
        if C.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, C.byref(size)):
            return buf.value.rsplit("\\", 1)[-1]
        return "?"
    finally:
        C.windll.kernel32.CloseHandle(handle)


def main():
    if sys.platform != "win32":
        print("本脚本需要 Windows。")
        return 1
    enable_dpi_awareness()
    u = C.WinDLL("user32", use_last_error=True)
    u.IsWindowVisible.argtypes = [T.HWND]
    u.GetWindowTextLengthW.argtypes = [T.HWND]
    u.GetWindowTextW.argtypes = [T.HWND, T.LPWSTR, C.c_int]
    u.GetClassNameW.argtypes = [T.HWND, T.LPWSTR, C.c_int]
    u.GetWindowThreadProcessId.argtypes = [T.HWND, C.POINTER(T.DWORD)]
    u.GetClientRect.argtypes = [T.HWND, C.POINTER(T.RECT)]
    u.IsIconic.argtypes = [T.HWND]

    rows = []

    @C.WINFUNCTYPE(T.BOOL, T.HWND, T.LPARAM)
    def callback(hwnd, param):
        if not u.IsWindowVisible(hwnd):
            return True
        length = u.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        title = C.create_unicode_buffer(length + 1)
        u.GetWindowTextW(hwnd, title, len(title))
        cls = C.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, cls, len(cls))
        pid = T.DWORD()
        u.GetWindowThreadProcessId(hwnd, C.byref(pid))
        rect = T.RECT()
        if u.IsIconic(hwnd) or not u.GetClientRect(hwnd, C.byref(rect)):
            return True
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w > 100 and h > 100:
            rows.append((hwnd, cls.value, process_name(pid.value), title.value, w, h))
        return True

    u.EnumWindows(callback, 0)
    print(f"共 {len(rows)} 个可见窗口（client 区 > 100×100）：")
    for hwnd, cls, proc, title, w, h in sorted(rows, key=lambda r: (r[2], r[3].casefold())):
        mark = " <-- 疑似小游戏窗口" if "微信" in title or "wechat" in title.casefold() else ""
        print(f"  hwnd={hwnd:>12}  {cls:<28} {proc:<22} {w:>5}x{h:<5}  {title}{mark}")

    print("\n含“微信/WeChat”窗口的子窗口列表（判断小游戏是否独立 HWND）：")

    @C.WINFUNCTYPE(T.BOOL, T.HWND, T.LPARAM)
    def child_callback(hwnd, parent):
        cls = C.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, cls, len(cls))
        length = u.GetWindowTextLengthW(hwnd)
        title = C.create_unicode_buffer(length + 1)
        u.GetWindowTextW(hwnd, title, len(title))
        rect = T.RECT()
        u.GetClientRect(hwnd, C.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w > 100 and h > 100:
            print(f"    child hwnd={hwnd:>12}  {cls.value:<28} {w:>5}x{h:<5}  {title.value}")
        return True

    for hwnd, _, _, title, _, _ in rows:
        if "微信" in title or "wechat" in title.casefold():
            print(f"  {title} (hwnd={hwnd}) 的子窗口：")
            u.EnumChildWindows(hwnd, child_callback, hwnd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
