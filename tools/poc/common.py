# SPDX-License-Identifier: GPL-3.0-only
"""PoC 共享的 Windows 类型声明、目标校验和可取消等待。"""
import argparse
import ctypes as C
from ctypes import wintypes as T
import math
import time

from fisher.wechat import is_wechat_process
from fisher.windows import Windows



class DiagnosticWindows(Windows):
    def __init__(self):
        super().__init__()
        self.u.GetClassNameW.argtypes = [T.HWND, T.LPWSTR, C.c_int]
        self.u.GetClassNameW.restype = C.c_int
        self.u.EnumChildWindows.argtypes = [T.HWND, self.callback_type, T.LPARAM]
        self.u.EnumChildWindows.restype = T.BOOL

    def window_info(self, hwnd):
        cls = C.create_unicode_buffer(256)
        self.u.GetClassNameW(hwnd, cls, len(cls))
        return {"hwnd": int(hwnd), "title": self.title(hwnd), "class": cls.value,
                "process": self.process_name(hwnd), "box": self.client_box(hwnd)}

    def diagnostic_windows(self, parent=None):
        rows = []

        @self.callback_type
        def callback(hwnd, param):
            if self.u.IsWindowVisible(hwnd):
                try:
                    info = self.window_info(hwnd)
                    if min(info["box"][2:]) > 100:
                        rows.append(info)
                except OSError:
                    pass
            return True

        if parent is None:
            self.u.EnumWindows(callback, 0)
        else:
            self.u.EnumChildWindows(parent, callback, 0)
        return rows


def is_wechat(info):
    return is_wechat_process(info["process"])


def resolve_target(win, hwnd=0):
    """在倒计时之后解析目标，拒绝误选终端等非微信窗口。"""
    hwnd = hwnd or win.foreground_window()
    if not hwnd:
        raise OSError("没有可用的目标窗口")
    info = win.window_info(hwnd)
    if not is_wechat(info):
        raise OSError("所选窗口不属于微信，请切回小游戏或指定正确的 --hwnd")
    if not win.foreground_matches(hwnd):
        raise OSError("目标游戏窗口不在前台，请切回小游戏后重试")
    return hwnd, info["box"]


def screen_box(box):
    return dict(zip(("left", "top", "width", "height"), box))


def cancelled(win):
    return win.key_down(0x78) or win.key_down(0x1B)  # F9 / Escape


def wait_for(seconds, is_cancelled):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        if is_cancelled():
            return False
        time.sleep(min(.05, max(0, deadline - time.perf_counter())))
    return not is_cancelled()


def finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise argparse.ArgumentTypeError("必须是有限数值")
    return number


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("必须是正整数")
    return number


def normalized(value):
    number = finite_float(value)
    if not 0 <= number <= 1:
        raise argparse.ArgumentTypeError("比例坐标必须在 0～1 之间")
    return number
