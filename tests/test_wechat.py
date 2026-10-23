# SPDX-License-Identifier: GPL-3.0-only
"""微信唯一入口、进程归属、选区和配置迁移回归。"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fisher.config import CONFIG_VERSION, DEFAULTS, load_config, save_config, validate_config
from fisher.wechat import select_windows, profile_matches
from fisher.windows import Windows


class WechatWindowTests(unittest.TestCase):
    def test_only_wechat_processes_are_selectable_even_with_misleading_titles(self):
        windows = [(1, "塔塔冒险队"), (2, "微信"), (3, "微信游戏"),
                   (4, "微信图片查看器"), (5, "MuMu Player"), (6, "视频号")]
        processes = {1: "WeChatAppEx.exe", 2: "Weixin.exe", 3: "chrome.exe",
                     4: "WeChat.exe", 5: "MuMu.exe", 6: "WeChat.exe"}
        self.assertEqual({x[0] for x in select_windows(windows, processes)}, {1, 2})
        self.assertEqual(select_windows(windows, {}), [])

    def test_foreground_requires_both_same_root_and_wechat_process(self):
        class User32:
            foreground = 101
            def GetForegroundWindow(self): return self.foreground
            def GetAncestor(self, hwnd, flag): return {101: 10, 201: 20}.get(hwnd, hwnd)
        win = Windows.__new__(Windows)
        win.u = User32()
        win.process_name = lambda hwnd: "WeChatAppEx.exe"
        self.assertTrue(win.foreground_matches(10))
        win.u.foreground = 201
        self.assertFalse(win.foreground_matches(10))
        win.u.foreground = 101
        win.process_name = lambda hwnd: "other.exe"
        self.assertFalse(win.foreground_matches(10))

    def test_profile_reuse_is_limited_to_wechat_and_same_client_size(self):
        p = dict(platform="wechat", title="塔塔冒险队", client_size=[400, 760], crop=[0, 30, 400, 730])
        self.assertTrue(profile_matches(p, (400, 760)))
        self.assertFalse(profile_matches(p, (401, 760)))
        self.assertFalse(profile_matches(dict(p, platform="other"), (400, 760)))
        for crop in ([0, 0, 500, 760], [-1, 0, 400, 760], [0, 0, True, 760], [0, 0, 1]):
            self.assertFalse(profile_matches(dict(p, crop=crop), (400, 760)))
        self.assertFalse(profile_matches(None, (400, 760)))


class WechatConfigTests(unittest.TestCase):
    def read(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            result = load_config(path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), data)
            return result

    def test_new_defaults_allow_clicks_but_startup_is_explicit(self):
        cfg = validate_config({})
        self.assertEqual(cfg, DEFAULTS)
        self.assertEqual(cfg["config_version"], 10)
        self.assertFalse(cfg["dry_run"])
        self.assertEqual(cfg["min_action_interval_s"], .9)
        for key in ("emulator_type", "input_method", "key_hold_ms", "capture_backend"):
            self.assertNotIn(key, cfg)
        self.assertFalse(hasattr(Windows, "tap_space"))

    def test_v9_wechat_settings_keep_preferences_and_drop_old_selectors(self):
        old = dict(DEFAULTS, config_version=9, emulator_type="wechat", input_method="click",
                   capture_backend="mss", key_hold_ms=35, dry_run=False,
                   click_point=[.3, .86], click_jitter_ratio=0, min_action_interval_s=1.1,
                   profile=dict(emulator_type="wechat", title="塔塔冒险队",
                                client_size=[400, 760], crop=[0, 30, 400, 730]))
        cfg = self.read(old)
        self.assertEqual(cfg["config_version"], CONFIG_VERSION)
        for key in ("dry_run", "click_point", "click_jitter_ratio", "min_action_interval_s"):
            self.assertEqual(cfg[key], old[key])
        self.assertEqual(set(cfg), set(DEFAULTS))
        self.assertEqual(cfg["profile"]["platform"], "wechat")
        self.assertNotIn("emulator_type", cfg["profile"])

    def test_old_wechat_default_interval_is_raised_but_current_custom_value_is_kept(self):
        for version in (7, 8, 9):
            cfg = self.read(dict(config_version=version, emulator_type="wechat", min_action_interval_s=.24))
            self.assertEqual(cfg["min_action_interval_s"], .9)
        self.assertEqual(self.read(dict(DEFAULTS, min_action_interval_s=.2))["min_action_interval_s"], .2)

    def test_other_environments_and_inputs_are_rejected(self):
        for key, values in (("emulator_type", ("ldplayer", "mumu", "other", None, [])),
                            ("input_method", ("space", "tap", None)),
                            ("capture_backend", ("dxcam", "other", None))):
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.read({key: value})

    def test_unknown_or_other_profile_is_discarded(self):
        p = dict(title="其他游戏", client_size=[400, 760], crop=[0, 0, 400, 760])
        self.assertIsNone(self.read(dict(profile=p))["profile"])
        self.assertIsNone(self.read(dict(profile=dict(p, emulator_type="mumu")))["profile"])

    def test_old_wechat_profile_is_retained_when_root_marks_wechat(self):
        p = dict(title="塔塔冒险队", client_size=[400, 760], crop=[0, 0, 400, 760])
        cfg = self.read(dict(emulator_type="wechat", profile=p))
        self.assertTrue(profile_matches(cfg["profile"], (400, 760)))

    def test_missing_jitter_is_defaulted_without_overwriting_saved_zero(self):
        self.assertEqual(self.read(dict(config_version=8, emulator_type="wechat"))["click_jitter_ratio"], .015)
        self.assertEqual(self.read(dict(DEFAULTS, click_jitter_ratio=0))["click_jitter_ratio"], 0)

    def test_click_coordinates_and_jitter_validate(self):
        for point in (None, [0], [True, .5], [-.1, .5], [float("nan"), .5]):
            with self.subTest(point=point), self.assertRaises(ValueError):
                validate_config(dict(click_point=point))
        for ratio in (True, "1", -.01, .051, float("nan")):
            with self.subTest(ratio=ratio), self.assertRaises(ValueError):
                validate_config(dict(click_jitter_ratio=ratio))

    def test_save_preserves_settings_and_clears_one_time_calibration(self):
        cfg = dict(DEFAULTS, dry_run=False, calibrate_speed=True, click_jitter_ratio=0)
        with tempfile.TemporaryDirectory() as tmp, patch("fisher.config.DATA_ROOT", Path(tmp)):
            save_config(cfg)
            saved = load_config(Path(tmp) / "config.json")
        self.assertFalse(saved["calibrate_speed"])
        self.assertFalse(saved["dry_run"])
        self.assertEqual(saved["click_jitter_ratio"], 0)
        self.assertTrue(cfg["calibrate_speed"])


if __name__ == "__main__":
    unittest.main()
