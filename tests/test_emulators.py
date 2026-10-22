# SPDX-License-Identifier: GPL-3.0-only
"""模拟器筛选、选区隔离和配置升级的回归。"""
import json
from pathlib import Path
import tempfile
import unittest
from fisher.config import CONFIG_VERSION, DEFAULTS, load_config, validate_config, select_environment
from fisher.emulators import select_windows, profile_matches
from fisher.windows import Windows


class EmulatorTests(unittest.TestCase):
    def test_wechat_process_family_accepts_game_title_without_wechat_alias(self):
        windows = [(1, "塔塔冒险队"), (2, "微信"), (3, "其他游戏"), (4, "微信图片查看器")]
        families = {1: "wechat", 4: "wechat"}
        self.assertEqual({row[0] for row in select_windows(windows, "wechat", window_families=families)}, {1, 2})
        self.assertEqual({row[0] for row in select_windows(windows, "wechat", True, families)[:2]}, {1, 2})

    def test_window_families_and_renamed_fallback(self):
        windows = [(1,"雷电模拟器"),(2,"MuMu安卓设备"),(3,"MuMu Player 12"),
                   (4,"MuMu多开器"),(5,"tt_fish · 钓鱼助手"),(6,"游戏实例A")]
        self.assertEqual(select_windows(windows,"ldplayer"),[(1,"雷电模拟器")])
        self.assertEqual({w[0] for w in select_windows(windows,"mumu")},{2,3})
        expanded = select_windows(windows,"mumu",True)
        self.assertEqual({w[0] for w in expanded},{1,2,3,6})
        self.assertEqual({w[0] for w in expanded[:2]},{2,3})
        self.assertEqual(select_windows([],"mumu"),[])

    def test_wechat_family_matches_and_excludes_sub_windows(self):
        windows = [(1, "微信"), (2, "WeChat"), (3, "微信图片查看器"), (4, "雷电模拟器"), (5, "tt_fish · 钓鱼助手")]
        self.assertEqual({w[0] for w in select_windows(windows, "wechat")}, {1, 2})
        self.assertEqual(select_windows(windows, "ldplayer"), [(4, "雷电模拟器")])
        expanded = select_windows(windows, "wechat", True)
        self.assertEqual({w[0] for w in expanded}, {1, 2, 4})
        self.assertEqual({w[0] for w in expanded[:2]}, {1, 2})

    def test_wechat_profiles_reuse_across_titles_of_same_family_and_size(self):
        p = {"title": "微信", "client_size": [400, 760], "crop": [0, 0, 400, 760], "emulator_type": "wechat"}
        self.assertTrue(profile_matches(p, "wechat", "微信", (400, 760)))
        # 微信窗口标题随版本变化；同族同尺寸同框选即视为同一窗口。
        self.assertTrue(profile_matches(p, "wechat", "微信 · 新版本标题", (400, 760)))
        self.assertFalse(profile_matches(p, "wechat", "微信", (401, 760)))
        self.assertFalse(profile_matches(p, "ldplayer", "微信", (400, 760)))
        self.assertFalse(profile_matches(p, "mumu", "微信", (400, 760)))
        bad = dict(p, crop=[0, 0, 400])
        self.assertFalse(profile_matches(bad, "wechat", "微信", (400, 760)))

    def test_profiles_never_cross_emulators_or_sizes(self):
        p={"title":"游戏实例A","client_size":[560,997],"crop":[0,0,560,997],"emulator_type":"mumu"}
        self.assertTrue(profile_matches(p,"mumu","游戏实例A",(560,997)))
        self.assertFalse(profile_matches(p,"ldplayer","游戏实例A",(560,997)))
        self.assertFalse(profile_matches(p,"mumu","游戏实例B",(560,997)))
        self.assertFalse(profile_matches(p,"mumu","游戏实例A",(336,598)))
        old=dict(p,title="MuMu安卓设备");old.pop("emulator_type")
        self.assertTrue(profile_matches(old,"mumu","MuMu安卓设备",(560,997)))
        old["title"]="游戏实例A"
        self.assertFalse(profile_matches(old,"mumu","游戏实例A",(560,997)))

    def test_foreground_accepts_child_but_not_another_instance_or_manager(self):
        class User32:
            foreground = 101
            def GetForegroundWindow(self):return self.foreground
            def GetAncestor(self, hwnd, flag):return {101:10,201:20,301:30}.get(hwnd,hwnd)
        win=Windows.__new__(Windows);win.u=User32()
        self.assertTrue(win.foreground_matches(10))
        for hwnd in (201,301,0):
            win.u.foreground=hwnd
            self.assertFalse(win.foreground_matches(10))


class UpgradeTests(unittest.TestCase):
    def test_v8_adds_jitter_without_overwriting_existing_preferences(self):
        old = dict(DEFAULTS, config_version=8, emulator_type="wechat", input_method="click",
                   click_point=[.3,.86], dry_run=False, min_action_interval_s=.7)
        old.pop("click_jitter_ratio")
        cfg = self.read(old)
        self.assertEqual(cfg["config_version"], CONFIG_VERSION)
        self.assertEqual(cfg["click_jitter_ratio"], .015)
        for key in ("click_point", "dry_run", "min_action_interval_s"):
            self.assertEqual(cfg[key], old[key])
        cfg["click_jitter_ratio"] = 0
        self.assertEqual(self.read(cfg), cfg)

    def test_invalid_jitter_settings_are_rejected(self):
        for ratio in (True, "1", -.01, .051, float("nan")):
            with self.subTest(ratio=ratio), self.assertRaises(ValueError):
                validate_config(dict(DEFAULTS, click_jitter_ratio=ratio))

    def read(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"config.json";p.write_text(json.dumps(data),encoding="utf-8")
            cfg=load_config(p)
            self.assertEqual(json.loads(p.read_text()),data)
            return cfg

    def test_defaults_and_upgrade_from_previous_defaults(self):
        self.assertTrue(DEFAULTS["continuous_fishing"])
        self.assertEqual(DEFAULTS["capture_every_n_frames"],6)
        old=dict(DEFAULTS,config_version=6,continuous_fishing=False,capture_every_n_frames=30,
                 input_latency_ms=75,unknown_timeout_s=240,toggle_hotkey="F6")
        old.pop("emulator_type")
        new=self.read(old)
        self.assertTrue(new["continuous_fishing"])
        self.assertEqual(new["capture_every_n_frames"],6)
        for key in ("input_latency_ms","unknown_timeout_s","toggle_hotkey"):
            self.assertEqual(new[key],old[key])

    def test_custom_sampling_preserved_and_mumu_profile_migrated(self):
        old=dict(DEFAULTS,config_version=6,capture_every_n_frames=12,
                 profile={"title":"MuMu安卓设备","client_size":[560,997],"crop":[0,0,560,997]})
        old.pop("emulator_type")
        new=self.read(old)
        self.assertEqual(new["capture_every_n_frames"],12)
        self.assertEqual(new["emulator_type"],"mumu")
        self.assertEqual(new["profile"],old["profile"])

    def test_new_version_preserves_unchecked_continuous_and_two_fps(self):
        cfg=dict(DEFAULTS,continuous_fishing=False,capture_every_n_frames=30,emulator_type="mumu")
        self.assertEqual(self.read(cfg),cfg)

    def test_invalid_emulator_is_rejected(self):
        for value in ("invalid",None,True):
            with self.subTest(value=value),self.assertRaises(ValueError):
                validate_config(dict(DEFAULTS,emulator_type=value))

    def test_invalid_input_method_backend_and_click_point_are_rejected(self):
        for field, value in (("input_method", "tap"), ("capture_backend", "opencv")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_config(dict(DEFAULTS, **{field: value}))
        for point in ([0.5], [0.5, 1.5], "center", [True, 0.5], [float("nan"), 0.5]):
            with self.subTest(point=point), self.assertRaises(ValueError):
                validate_config(dict(DEFAULTS, click_point=point))

    def test_v8_wechat_migrates_to_click_and_conservative_interval(self):
        old = dict(DEFAULTS, config_version=7, emulator_type="wechat")
        for key in ("input_method", "click_point", "click_hold_ms", "capture_backend"):
            old.pop(key)
        new = self.read(old)
        self.assertEqual(new["input_method"], "click")
        self.assertEqual(new["min_action_interval_s"], 0.9)

    def test_v8_ldplayer_keeps_space_and_interval(self):
        old = dict(DEFAULTS, config_version=7, emulator_type="ldplayer")
        for key in ("input_method", "click_point", "click_hold_ms", "capture_backend"):
            old.pop(key)
        new = self.read(old)
        self.assertEqual(new["input_method"], "space")
        self.assertEqual(new["min_action_interval_s"], DEFAULTS["min_action_interval_s"])

    def test_v8_profile_title_drives_wechat_migration_without_emulator_type(self):
        old = dict(DEFAULTS, config_version=7)
        old.pop("emulator_type")
        for key in ("input_method", "click_point", "click_hold_ms", "capture_backend"):
            old.pop(key)
        old["profile"] = {"title": "微信", "client_size": [400, 760], "crop": [0, 0, 400, 760]}
        new = self.read(old)
        self.assertEqual(new["input_method"], "click")
        self.assertEqual(new["emulator_type"], "wechat")

    def test_new_wechat_configuration_has_observation_click_and_interval_defaults(self):
        cfg = validate_config({"emulator_type": "wechat"})
        self.assertTrue(cfg["dry_run"])
        self.assertEqual(cfg["input_method"], "click")
        self.assertEqual(cfg["min_action_interval_s"], .9)

    def test_environment_switch_sets_wechat_defaults_and_restores_space(self):
        switched = select_environment(DEFAULTS, "wechat")
        self.assertTrue(switched["dry_run"])
        self.assertEqual(switched["input_method"], "click")
        self.assertEqual(switched["min_action_interval_s"], .9)
        self.assertEqual(DEFAULTS["min_action_interval_s"], .24)
        self.assertEqual(select_environment(switched, "mumu")["input_method"], "space")

    def test_custom_intervals_and_saved_observation_choice_are_preserved(self):
        for interval in (.3, 1.2):
            switched = select_environment(dict(DEFAULTS, min_action_interval_s=interval), "wechat")
            self.assertEqual(switched["min_action_interval_s"], interval)
        cfg = dict(DEFAULTS, emulator_type="wechat", input_method="click", dry_run=False,
                   min_action_interval_s=.2)
        self.assertEqual(self.read(cfg), cfg)

    def test_invalid_old_wechat_interval_is_reported_as_validation_error(self):
        for interval in (None, "slow", True):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                self.read(dict(DEFAULTS, config_version=7, emulator_type="wechat",
                               min_action_interval_s=interval))
