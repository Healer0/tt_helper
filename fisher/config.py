# SPDX-License-Identifier: GPL-3.0-only
"""配置校验、旧版迁移与原子保存。"""
import json
import math
import os
from pathlib import Path
from .speed import DEFAULT_SPEED
from .wechat import wechat_profile

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ["TT_FISH_DATA_DIR"]).resolve() if os.environ.get("TT_FISH_DATA_DIR") else ROOT
CONFIG_VERSION = 10
REFERENCE_FPS = 60
HOTKEYS = tuple(f"F{i}" for i in range(1, 13))
DEFAULTS = {
    "config_version": CONFIG_VERSION,
    "timing_mode": "phase", "adaptive_latency": True, "show_preview": False,
    "calibrate_speed": False, "speed_fraction_per_s": DEFAULT_SPEED, "contact_overlap_ratio": .60,
    "dry_run": False, "continuous_fishing": True,
    "capture_every_n_frames": 6,
    "click_point": [0.5, 0.5], "click_hold_ms": 30,
    "click_jitter_ratio": 0.015,
    "toggle_hotkey": "F8", "pause_hotkey": "F9", "snapshot_hotkey": "F10",
    "input_latency_ms": 40, "latency_uncertainty_ms": 12,
    "target_margin_px": 3, "min_action_interval_s": 0.9,
    "result_wait_s": 3.0, "result_retry_s": 1.0, "result_retry_jitter_ms": 40,
    "unknown_timeout_s": 60, "timing_timeout_s": 120, "wait_timeout_s": 120,
    "action_ack_timeout_s": 5, "max_casts": 20,
    "max_session_minutes": 15, "template_threshold": 0.68, "profile": None,
}


def capture_interval(cfg):
    return cfg["capture_every_n_frames"] / REFERENCE_FPS


def hotkey_vk(name):
    return 0x70 + HOTKEYS.index(name)


def validate_config(data):
    if not isinstance(data, dict):
        raise ValueError("配置文件应为JSON对象")
    # 仅迁移旧微信设置；其他目标或输入方式不再受支持。
    if data.get("emulator_type", "wechat") != "wechat":
        raise ValueError("此版本仅支持微信小游戏，请备份并移除旧运行环境配置后重新设置")
    if data.get("input_method", "click") != "click":
        raise ValueError("此版本仅支持微信鼠标点击，请移除旧输入方式配置后重新设置")
    if data.get("capture_backend", "mss") != "mss":
        raise ValueError("此版本仅支持mss截图")
    cfg = dict(DEFAULTS)
    cfg.update(data)
    # 避免与 DEFAULTS 共享列表对象；校验失败时也不污染默认值。
    if cfg["click_point"] is DEFAULTS["click_point"]:
        cfg["click_point"] = list(DEFAULTS["click_point"])
    cfg["profile"] = wechat_profile(cfg["profile"], trusted=data.get("emulator_type") == "wechat")
    for key in ("emulator_type", "input_method", "capture_backend", "key_hold_ms"):
        cfg.pop(key, None)
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
        "latency_uncertainty_ms": (0, 100),
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
    version = data.get("config_version", 0)
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("配置版本必须为整数")
    if version < 10:
        interval = data.get("min_action_interval_s", DEFAULTS["min_action_interval_s"])
        if (isinstance(interval, (int, float)) and not isinstance(interval, bool)
                and interval <= .24):
            data["min_action_interval_s"] = DEFAULTS["min_action_interval_s"]
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
