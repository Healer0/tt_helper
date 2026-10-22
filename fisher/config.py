# SPDX-License-Identifier: GPL-3.0-only
"""配置校验、旧版迁移与原子保存。"""
import json
import math
import os
from pathlib import Path
from .speed import DEFAULT_SPEED
from .emulators import EMULATORS, title_family

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ["TT_FISH_DATA_DIR"]).resolve() if os.environ.get("TT_FISH_DATA_DIR") else ROOT
CONFIG_VERSION = 9
REFERENCE_FPS = 60
HOTKEYS = tuple(f"F{i}" for i in range(1, 13))
DEFAULTS = {
    "config_version": CONFIG_VERSION,
    "timing_mode": "phase", "adaptive_latency": True, "show_preview": False,
    "calibrate_speed": False, "speed_fraction_per_s": DEFAULT_SPEED, "contact_overlap_ratio": .60,
    "dry_run": False, "continuous_fishing": True,
    "capture_every_n_frames": 6, "emulator_type": "ldplayer",
    "input_method": "space", "click_point": [0.5, 0.5], "click_hold_ms": 30,
    "click_jitter_ratio": 0.015,
    "capture_backend": "mss",
    "toggle_hotkey": "F8", "pause_hotkey": "F9", "snapshot_hotkey": "F10",
    "input_latency_ms": 40, "latency_uncertainty_ms": 12, "key_hold_ms": 35,
    "target_margin_px": 3, "min_action_interval_s": 0.24,
    "result_wait_s": 3.0, "result_retry_s": 1.0, "result_retry_jitter_ms": 40,
    "unknown_timeout_s": 60, "timing_timeout_s": 120, "wait_timeout_s": 120,
    "action_ack_timeout_s": 5, "max_casts": 20,
    "max_session_minutes": 15, "template_threshold": 0.68, "profile": None,
}
WECHAT_ACTION_INTERVAL_S = 0.9


def select_environment(cfg, emulator_type):
    """用户切换环境时应用输入预设；高于旧默认值的自定义间隔保留。"""
    if emulator_type not in EMULATORS:
        raise ValueError("请选择" + "、".join(EMULATORS.values()))
    updated = dict(cfg, emulator_type=emulator_type,
                   input_method="click" if emulator_type == "wechat" else "space")
    if emulator_type == "wechat":
        updated["dry_run"] = True
        interval = updated.get("min_action_interval_s", DEFAULTS["min_action_interval_s"])
        if isinstance(interval, (int, float)) and not isinstance(interval, bool) and interval <= DEFAULTS["min_action_interval_s"]:
            updated["min_action_interval_s"] = WECHAT_ACTION_INTERVAL_S
    return updated


def capture_interval(cfg):
    return cfg["capture_every_n_frames"] / REFERENCE_FPS


def hotkey_vk(name):
    return 0x70 + HOTKEYS.index(name)


def validate_config(data):
    if not isinstance(data, dict):
        raise ValueError("配置文件应为JSON对象")
    cfg = dict(DEFAULTS)
    if data.get("emulator_type") == "wechat":
        # 仅补齐缺失值，重开时不覆盖用户已保存的观察/输入/间隔选择。
        cfg.update(input_method="click", dry_run=True,
                   min_action_interval_s=WECHAT_ACTION_INTERVAL_S)
    cfg.update(data)
    # 避免与 DEFAULTS 共享列表对象；校验失败时也不污染默认值。
    if cfg["click_point"] is DEFAULTS["click_point"]:
        cfg["click_point"] = list(DEFAULTS["click_point"])
    if not isinstance(cfg["emulator_type"], str) or cfg["emulator_type"] not in EMULATORS:
        raise ValueError("请选择" + "、".join(EMULATORS.values()))
    if cfg["input_method"] not in ("space", "click"):
        raise ValueError("输入方式应为 space（空格）或 click（鼠标点击）")
    if cfg["capture_backend"] not in ("mss", "dxcam"):
        raise ValueError("截图后端应为 mss 或 dxcam")
    point = cfg["click_point"]
    if (not isinstance(point, list) or len(point) != 2 or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                not math.isfinite(v) or not 0 <= v <= 1 for v in point)):
        raise ValueError(f"点击位置应为 0～1 的二维坐标，实际为 {point!r}")
    cfg["click_point"] = [float(v) for v in point]
    for key in ("dry_run", "continuous_fishing", "adaptive_latency", "show_preview", "calibrate_speed"):
        if not isinstance(cfg[key], bool):
            raise ValueError(f"{key} 必须为 true 或 false")
    if cfg["timing_mode"] not in ("phase", "contact", "center"):
        raise ValueError("黄条策略无效")
    limits = {
        "capture_every_n_frames": (1, 60), "input_latency_ms": (0, 250),
        "latency_uncertainty_ms": (0, 100), "key_hold_ms": (10, 150),
        "click_hold_ms": (10, 150),
        "click_jitter_ratio": (0, 0.05),
        "target_margin_px": (0, 20), "min_action_interval_s": (0.15, 5),
        "result_wait_s": (1, 30), "result_retry_s": (0.5, 15),
        "result_retry_jitter_ms": (0, 100), "unknown_timeout_s": (0, 3600),
        "timing_timeout_s": (0, 3600),
        "wait_timeout_s": (10, 600), "action_ack_timeout_s": (2, 20),
        "max_casts": (1, 10000), "max_session_minutes": (1, 1440),
        "template_threshold": (0.5, 0.99),
        "speed_fraction_per_s": (.1, 5), "contact_overlap_ratio": (.05, 1),
    }
    for key, (lo, hi) in limits.items():
        x = cfg[key]
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not lo <= x <= hi:
            raise ValueError(f"配置 {key} 应为 {lo}～{hi} 的有限数值，实际为 {x!r}")
    for key in ("max_casts", "capture_every_n_frames"):
        if int(cfg[key]) != cfg[key]:
            raise ValueError(f"配置 {key} 必须为整数")
        cfg[key] = int(cfg[key])
    for key in ("toggle_hotkey", "pause_hotkey", "snapshot_hotkey"):
        value = cfg[key]
        if not isinstance(value, str) or value.strip().upper() not in HOTKEYS:
            raise ValueError(f"配置 {key} 应为 F1～F12 中的一个键")
        cfg[key] = value.strip().upper()
    if len({cfg[k] for k in ("toggle_hotkey", "pause_hotkey", "snapshot_hotkey")}) != 3:
        raise ValueError("开始／暂停、紧急暂停、保存截图的快捷键不能重复")
    cfg["config_version"] = CONFIG_VERSION
    cfg.pop("capture_fps", None)
    cfg.pop("result_max_presses", None)
    return cfg


def load_config(path=None):
    path = Path(path) if path else DATA_ROOT / "config.json"
    data = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError("配置文件应为JSON对象")
    if data.get("config_version",0) in (0,1,2,3,4) and data.get("unknown_timeout_s")==12:
        data["unknown_timeout_s"]=DEFAULTS["unknown_timeout_s"]
    if data.get("config_version",0) in (0,1,2,3,4,5):
        data["timing_mode"]="phase"
    if "config_version" not in data:
        # 旧版保留框选及输入参数，截图与结果页采用新版默认节奏。
        for key in ("result_wait_s", "result_retry_s", "result_retry_jitter_ms", "capture_every_n_frames"):
            data[key] = DEFAULTS[key]
    if data.get("config_version", 0) in (0, 1, 2, 3, 4, 5, 6):
        data["continuous_fishing"] = True
        if data.get("capture_every_n_frames", 30) == 30:
            data["capture_every_n_frames"] = DEFAULTS["capture_every_n_frames"]
        old_profile = data.get("profile")
        if "emulator_type" not in data and isinstance(old_profile, dict):
            data["emulator_type"] = title_family(old_profile.get("title", "")) or "ldplayer"
    if data.get("config_version", 0) <= 7:
        # v8 引入输入方式：微信小游戏默认鼠标点击，其余保持空格。
        wechat = data.get("emulator_type") == "wechat" or title_family(
            (data.get("profile") or {}).get("title", "")) == "wechat"
        if "emulator_type" not in data and wechat:
            data["emulator_type"] = "wechat"
        data.setdefault("input_method", "click" if wechat else "space")
        # 微信窗口点击节奏更保守：仅在未手动调高间隔时提升默认值。
        interval = data.get("min_action_interval_s", DEFAULTS["min_action_interval_s"])
        if (wechat and isinstance(interval, (int, float)) and not isinstance(interval, bool)
                and interval <= DEFAULTS["min_action_interval_s"]):
            data["min_action_interval_s"] = WECHAT_ACTION_INTERVAL_S
    return validate_config(data)


def save_config(cfg):
    cfg = validate_config(cfg)
    # 校准请求只作用于当前监测，不在下次打开程序时自动重新校准。
    cfg["calibrate_speed"] = False
    path = DATA_ROOT / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
