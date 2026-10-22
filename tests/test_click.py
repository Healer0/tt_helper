# SPDX-License-Identifier: GPL-3.0-only
"""鼠标点击注入：坐标映射纯函数与click_at守卫回归。"""
import unittest
from fisher.windows import Windows, click_point, absolute_mouse_coords


class ClickPointTests(unittest.TestCase):
    def test_normalized_corners_map_to_box_pixels(self):
        box = {"left": 10, "top": 20, "width": 336, "height": 598}
        self.assertEqual(click_point(box, 0, 0), (10, 20))
        self.assertEqual(click_point(box, 1, 1), (345, 617))
        self.assertEqual(click_point(box, .5, .5), (178, 318))

    def test_out_of_range_normalized_values_clamp_into_box(self):
        box = {"left": 0, "top": 0, "width": 336, "height": 598}
        self.assertEqual(click_point(box, -1, 2), (0, 597))

    def test_tiny_box_is_rejected(self):
        for box in ({"left": 0, "top": 0, "width": 2, "height": 598},
                    {"left": 0, "top": 0, "width": 336, "height": 1}):
            with self.subTest(box=box), self.assertRaises(ValueError):
                click_point(box, .5, .5)

    def test_absolute_mapping_uses_full_virtual_screen_range(self):
        self.assertEqual(absolute_mouse_coords(0, 0, 0, 0, 1920, 1080), (0, 0))
        self.assertEqual(absolute_mouse_coords(1919, 1079, 0, 0, 1920, 1080), (65535, 65535))
        x, y = absolute_mouse_coords(960, 540, 0, 0, 1920, 1080)
        # 中点落在量程中点附近（公式按 vw-1 归一化，与整数量程中点相差 40 单位内）。
        self.assertAlmostEqual(x, 32768, delta=40)
        self.assertAlmostEqual(y, 32768, delta=40)

    def test_absolute_mapping_offsets_by_virtual_origin(self):
        self.assertEqual(absolute_mouse_coords(-640, 0, -640, 0, 1920, 1080), (0, 0))

    def test_outside_virtual_screen_is_rejected(self):
        with self.assertRaises(ValueError):
            absolute_mouse_coords(1920, 0, 0, 0, 1920, 1080)
        with self.assertRaises(ValueError):
            absolute_mouse_coords(0, -1, 0, 0, 1920, 1080)

    def test_invalid_screen_is_rejected(self):
        with self.assertRaises(ValueError):
            absolute_mouse_coords(0, 0, 0, 0, 1, 1080)


class ClickGuardTests(unittest.TestCase):
    BOX = {"left": 0, "top": 0, "width": 336, "height": 598}

    class User32:
        def __init__(self):
            self.calls = []

        def SendInput(self, n, ptr, size):
            self.calls.append(n)
            return n

    def instance(self, foreground=True, pressed=()):
        win = Windows.__new__(Windows)
        win.foreground_matches = lambda hwnd: foreground
        win.key_down = lambda key: key in pressed
        win.virtual_screen = lambda: (0, 0, 1920, 1080)
        win.u = self.User32()
        win.owns_space = False
        win.interrupted = False
        return win

    def test_no_input_without_focus(self):
        win = self.instance(False)
        self.assertFalse(win.click_at(1, self.BOX, .5, .5, 10, lambda: False))
        self.assertEqual(win.u.calls, [])
        self.assertIsNone(win.last_key_down_at)

    def test_no_input_when_cancelled_or_geometry_changes(self):
        for cancel, guard in ((True, True), (False, False)):
            win = self.instance()
            self.assertFalse(win.click_at(1, self.BOX, .5, .5, 10, lambda: cancel, lambda: guard))
            self.assertEqual(win.u.calls, [])

    def test_click_sends_move_down_then_up_and_records_times(self):
        win = self.instance()
        self.assertTrue(win.click_at(1, self.BOX, .5, .5, 10, lambda: False))
        self.assertEqual(win.u.calls, [2, 1])
        self.assertFalse(win.owns_space)
        self.assertFalse(win.interrupted)
        self.assertIsNotNone(win.last_key_down_at)
        self.assertIsNotNone(win.last_key_up_at)
        self.assertEqual(win.last_click_at, win.last_key_down_at)

    def test_manual_modifiers_pause_input(self):
        win = self.instance(pressed=(0x11,))
        with self.assertRaises(OSError):
            win.click_at(1, self.BOX, .5, .5, 10, lambda: False)
        self.assertEqual(win.u.calls, [])

    def test_manual_mouse_buttons_pause_input(self):
        for key in (0x01, 0x02, 0x04):
            win = self.instance(pressed=(key,))
            with self.assertRaises(OSError):
                win.click_at(1, self.BOX, .5, .5, 10, lambda: False)
            self.assertEqual(win.u.calls, [])

    def test_cancel_during_hold_still_releases_and_marks_interruption(self):
        win = self.instance()
        polls = [False, False, True]

        def cancelled():
            return polls.pop(0) if polls else True

        self.assertTrue(win.click_at(1, self.BOX, .5, .5, 35, cancelled))
        self.assertEqual(win.u.calls, [2, 1])
        self.assertTrue(win.interrupted)
        self.assertIsNotNone(win.last_key_up_at)

    def test_failed_first_send_does_not_send_release(self):
        win = self.instance()

        def fail(n, ptr, size):
            win.u.calls.append(n)
            return 0

        win.u.SendInput = fail
        with self.assertRaises(OSError):
            win.click_at(1, self.BOX, .5, .5, 10, lambda: False)
        # 第一次发送（移动+按下）被尝试一次；失败后不再补发抬起。
        self.assertEqual(win.u.calls, [2])
        self.assertIsNone(win.last_key_down_at)


if __name__ == "__main__":
    unittest.main()
