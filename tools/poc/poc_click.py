# SPDX-License-Identifier: GPL-3.0-only
"""PoC 0.4：验证 SendInput 鼠标点击能否触发微信小游戏的触摸事件。

用法（小游戏置于前台，先停在安全界面如下钩按钮页）：
    python tools/poc/poc_click.py
可选参数：
    --hwnd <十进制句柄>   目标窗口，默认前台窗口
    --n 3                 点击次数（默认 3，每次间隔 2 秒）
    --x 0.5 --y 0.5       点击位置（窗口 client 区归一化坐标，默认画面中央）
    --hold 30             按下到抬起的间隔（毫秒，默认 30，模拟真实短按）

判定标准：点击“下钩/抛竿按钮”位置能触发阶段变化（进入等待上钩），
或点击画面任意位置能触发拉钩；同时用秒表粗测游戏响应延迟。
失败处理：
    1) 检查 MOUSEEVENTF_ABSOLUTE 的 0-65535 坐标映射与 DPI 感知；
    2) 尝试更长 hold（如 60ms）区分短按/长按语义；
    3) 仍无效 → 阶段 0.4 不通过，暂缓后续代码改造。
注意：本脚本会真实点击前台窗口；若游戏有防作弊检测并出现告警，立即停止。
"""
import argparse
import ctypes as C
from ctypes import wintypes as T
import sys
import time


# INPUT 结构必须保留完整 union；仅定义 MOUSEINPUT 会导致 64 位结构尺寸错误。
UPTR = C.c_size_t
class KEYBDINPUT(C.Structure):
    _fields_ = [("wVk", T.WORD), ("wScan", T.WORD), ("dwFlags", T.DWORD), ("time", T.DWORD), ("dwExtraInfo", UPTR)]
class MOUSEINPUT(C.Structure):
    _fields_ = [("dx", T.LONG), ("dy", T.LONG), ("mouseData", T.DWORD), ("dwFlags", T.DWORD), ("time", T.DWORD), ("dwExtraInfo", UPTR)]
class HARDWAREINPUT(C.Structure):
    _fields_ = [("uMsg", T.DWORD), ("wParamL", T.WORD), ("wParamH", T.WORD)]
class INPUTUNION(C.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]
class INPUT(C.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", T.DWORD), ("u", INPUTUNION)]

MOVE = 0x0001
LEFTDOWN = 0x0002
LEFTUP = 0x0004
ABSOLUTE = 0x8000
VIRTUALDESK = 0x4000


def click(client_box, x_norm, y_norm, hold_ms):
    u = C.WinDLL("user32", use_last_error=True)
    u.SendInput.argtypes = [T.UINT, C.POINTER(INPUT), C.c_int]
    u.SendInput.restype = T.UINT
    u.GetSystemMetrics.argtypes = [T.c_int]
    u.GetSystemMetrics.restype = T.c_int
    # SM_XVIRTUALSCREEN=76, SM_YVIRTUALSCREEN=77, SM_CXVIRTUALSCREEN=78, SM_CYVIRTUALSCREEN=79
    vx, vy, vw, vh = (u.GetSystemMetrics(i) for i in (76, 77, 78, 79))
    left, top, width, height = client_box
    x = max(0.0, min(1.0, x_norm))
    y = max(0.0, min(1.0, y_norm))
    px, py = left + x * (width - 1), top + y * (height - 1)
    if not (vx <= px < vx + vw and vy <= py < vy + vh):
        raise ValueError(f"点击坐标超出虚拟屏幕：({px}, {py})")
    ax = round((px - vx) * 65535 / (vw - 1))
    ay = round((py - vy) * 65535 / (vh - 1))
    move = INPUT(type=0, mi=MOUSEINPUT(ax, ay, 0, MOVE | ABSOLUTE | VIRTUALDESK, 0, 0))
    down = INPUT(type=0, mi=MOUSEINPUT(0, 0, 0, LEFTDOWN, 0, 0))
    up = INPUT(type=0, mi=MOUSEINPUT(0, 0, 0, LEFTUP, 0, 0))
    sent = u.SendInput(2, (INPUT * 2)(move, down), C.sizeof(INPUT))
    if sent != 2:
        raise OSError("点击发送失败（移动+按下）")
    time.sleep(hold_ms / 1000)
    sent = u.SendInput(1, C.byref(up), C.sizeof(INPUT))
    if sent != 1:
        raise OSError("点击发送失败（抬起）")


def main():
    if sys.platform != "win32":
        print("本脚本需要 Windows。")
        return 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hwnd", type=int, default=0)
    parser.add_argument("--n", type=int, default=3)
    parser.add_argument("--x", type=float, default=0.5)
    parser.add_argument("--y", type=float, default=0.5)
    parser.add_argument("--hold", type=float, default=30)
    args = parser.parse_args()

    from fisher.windows import enable_dpi_awareness, Windows

    enable_dpi_awareness()
    win = Windows()
    hwnd = args.hwnd or C.windll.user32.GetForegroundWindow()
    box = win.client_box(hwnd)
    print(f"目标窗口：{win.title(hwnd)}  区域 {box}")
    print(f"5 秒后开始在归一化位置 ({args.x}, {args.y}) 点击 {args.n} 次（按住 {args.hold}ms，间隔 2 秒）…")
    print("请立即切回小游戏窗口并停在安全界面。")
    time.sleep(5)
    for i in range(args.n):
        t0 = time.perf_counter()
        click(box, args.x, args.y, args.hold)
        print(f"第 {i + 1}/{args.n} 次点击已发送（耗时 {time.perf_counter() - t0:.3f}s），观察游戏是否响应。")
        time.sleep(2)
    print("完成。请人工确认：点击是否触发了阶段变化？响应延迟大约多少？")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
