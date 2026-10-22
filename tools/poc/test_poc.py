# SPDX-License-Identifier: GPL-3.0-only
"""开发专用 PoC 回归；使用伪窗口，不发送系统输入，不进入发布包。"""
import contextlib
import ctypes as C
from ctypes import wintypes as T
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import numpy as np

from fisher.windows import Windows
from tools.poc import common, poc_capture, poc_click, poc_launch, poc_windows


class FakeWindow:
    click_at = Windows.click_at
    interrupted = False
    owns_space = False

    def __init__(self):
        self.foreground = 10
        self.box = (20, 30, 336, 598)
        self.pressed = set()
        self.calls = []
        self.after_down = self.after_up = lambda: None
        self.u = SimpleNamespace(SendInput=self.send_input)

    def send_input(self, count, ptr, size):
        self.calls.append(count)
        (self.after_down if count == 2 else self.after_up)()
        return count

    def foreground_window(self): return self.foreground
    def foreground_matches(self, hwnd): return self.foreground == hwnd
    def title(self, hwnd): return "微信小游戏" if hwnd == 10 else "终端"
    def client_box(self, hwnd): return self.box
    def key_down(self, key): return key in self.pressed
    def virtual_screen(self): return (0, 0, 1920, 1080)
    def window_info(self, hwnd):
        return dict(title=self.title(hwnd), process="WeChatAppEx.exe" if hwnd == 10 else "pwsh.exe",
                    box=self.client_box(hwnd))


class PocTests(unittest.TestCase):
    def args(self, **kwargs):
        return SimpleNamespace(**dict(dict(hwnd=0, n=1, x=.5, y=.5, hold=10, countdown=5), **kwargs))

    def run_clicks(self, win, args=None, wait=None):
        with contextlib.redirect_stdout(io.StringIO()), patch.object(poc_click, "wait_for", side_effect=wait or (lambda *args: True)):
            poc_click.run_clicks(win, args or self.args())

    def test_target_is_chosen_after_countdown_and_terminal_is_rejected(self):
        win = FakeWindow()
        win.foreground = 20
        with self.assertRaises(OSError):
            self.run_clicks(win)
        self.assertEqual(win.calls, [])
        def switch_to_game(*args):
            win.foreground = 10
            return True
        self.run_clicks(win, wait=switch_to_game)
        self.assertEqual(win.calls, [2, 1])

    def test_focus_loss_between_clicks_stops_remaining_input(self):
        win = FakeWindow()
        win.after_up = lambda: setattr(win, "foreground", 20)
        with self.assertRaises(OSError):
            self.run_clicks(win, self.args(n=3))
        self.assertEqual(win.calls, [2, 1])

    def test_geometry_change_inside_input_guard_sends_nothing(self):
        win = FakeWindow()
        win.client_box = Mock(side_effect=[win.box, win.box, (25, 30, 336, 598)])
        with self.assertRaises(OSError):
            self.run_clicks(win)
        self.assertEqual(win.calls, [])

    def test_cancel_during_hold_releases_and_stops_remaining_clicks(self):
        win = FakeWindow()
        win.after_down = lambda: win.pressed.add(0x78)
        with self.assertRaises(OSError):
            self.run_clicks(win, self.args(n=3))
        self.assertEqual(win.calls, [2, 1])
        self.assertTrue(win.interrupted)

    def test_keyboard_interrupt_after_down_still_releases(self):
        win = FakeWindow()
        def interrupt():
            win.key_down = Mock(side_effect=KeyboardInterrupt)
        win.after_down = interrupt
        with self.assertRaises(KeyboardInterrupt):
            self.run_clicks(win)
        self.assertEqual(win.calls, [2, 1])

    def test_cancelled_countdown_sends_nothing(self):
        win = FakeWindow()
        with self.assertRaises(OSError):
            self.run_clicks(win, wait=lambda *args: False)
        self.assertEqual(win.calls, [])

    def test_capture_reports_motion_and_rejects_frozen_or_solid_frames(self):
        first = np.zeros((4, 4, 3), np.uint8)
        first[:2] = 100
        second = 255 - first
        cases = (([first, second], 0), ([first, first], 1), ([first*0, first*0], 1))
        for frames, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                win = FakeWindow()
                args = self.args(frames=2, interval=.1, out=tmp)
                with contextlib.redirect_stdout(io.StringIO()), patch("mss.mss"), \
                     patch.object(poc_capture, "wait_for", return_value=True), \
                     patch.object(poc_capture, "grab_box", side_effect=frames), \
                     patch.object(poc_capture, "write_image"):
                    self.assertEqual(poc_capture.capture_frames(win, args), expected)
                report = json.loads((Path(tmp) / "report.json").read_text(encoding="utf-8"))
                self.assertEqual(report["passed"], expected == 0)
                self.assertEqual(win.calls, [])

    def test_capture_stops_on_focus_loss_before_grabbing(self):
        win = FakeWindow()
        # 初次目标确认通过，实际截图前失焦。
        win.foreground_matches = Mock(side_effect=[True, False])
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()), \
             patch("mss.mss"), patch.object(poc_capture, "wait_for", return_value=True), \
             patch.object(poc_capture, "grab_box") as grab, self.assertRaises(OSError):
            poc_capture.capture_frames(win, self.args(frames=2, interval=.1, out=tmp))
        grab.assert_not_called()

    def test_rejects_nonfinite_coordinates_and_invalid_capture_parameters(self):
        cases = ((poc_click, ["--x", "nan"]), (poc_click, ["--hold", "-1"]),
                 (poc_click, ["--jitter-percent", "6"]),
                 (poc_click, ["--n", "0"]), (poc_capture, ["--frames", "1"]),
                 (poc_capture, ["--interval", "nan"]))
        for module, args in cases:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                module.main(args)
            self.assertEqual(exc.exception.code, 2)

    def test_non_windows_entry_points_fail_before_accessing_native_api(self):
        for module in (poc_click, poc_capture, poc_launch, poc_windows):
            with self.subTest(module=module.__name__), patch.object(sys, "platform", "linux"), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(module.main([]), 1)

    def test_direct_and_module_help_entry_points(self):
        root = Path(__file__).resolve().parents[2]
        for name in ("poc_click", "poc_capture", "poc_launch", "poc_windows"):
            for entry in ([str(root / "tools/poc" / (name + ".py"))], ["-m", "tools.poc." + name]):
                with self.subTest(entry=entry):
                    result = subprocess.run([sys.executable, "-X", "utf8", *entry, "--help"], cwd=root,
                                            capture_output=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))

    def test_process_handle_is_forwarded_and_closed_without_truncation(self):
        win = common.DiagnosticWindows.__new__(common.DiagnosticWindows)
        handle = (1 << 40) + 1
        def pid(hwnd, ptr): ptr._obj.value = 123
        def image(handle_arg, flags, buf, size):
            self.assertEqual(handle_arg, handle)
            buf.value = r"C:\Tencent\WeChatAppEx.exe"
            return True
        win.u = SimpleNamespace(GetWindowThreadProcessId=pid)
        win.k = SimpleNamespace(OpenProcess=Mock(return_value=handle), QueryFullProcessImageNameW=image,
                                CloseHandle=Mock())
        self.assertEqual(win.process_name(10), "WeChatAppEx.exe")
        win.k.CloseHandle.assert_called_once_with(handle)

    @unittest.skipUnless(sys.platform == "win32", "Windows native ABI")
    def test_native_handle_prototypes_use_pointer_width(self):
        win = common.DiagnosticWindows()
        self.assertIs(win.k.OpenProcess.restype, T.HANDLE)
        self.assertEqual(win.k.CloseHandle.argtypes, [T.HANDLE])
        self.assertEqual(win.k.QueryFullProcessImageNameW.argtypes[0], T.HANDLE)
        self.assertIs(win.u.GetForegroundWindow.restype, T.HWND)
        self.assertEqual(C.sizeof(T.HANDLE), C.sizeof(C.c_void_p))


if __name__ == "__main__":
    unittest.main()
