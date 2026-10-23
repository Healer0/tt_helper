# SPDX-License-Identifier: GPL-3.0-only
"""微信进程窗口筛选和游戏选区校验。"""

WECHAT_PROCESSES = {"wechat.exe", "weixin.exe", "wechatappex.exe", "weixinappex.exe"}
EXCLUDED_TITLES = ("图片查看器", "视频号")


def is_wechat_process(name):
    return str(name).casefold() in WECHAT_PROCESSES


def is_wechat_title(title):
    """仅用于识别旧微信配置；实时窗口归属必须通过进程确认。"""
    return any(alias in str(title).casefold() for alias in ("微信", "wechat", "weixin"))


def select_windows(windows, process_names):
    return sorted(
        ((hwnd, title) for hwnd, title in windows
         if is_wechat_process(process_names.get(hwnd, ""))
         and not any(part in title for part in EXCLUDED_TITLES)),
        key=lambda row: (row[1].casefold(), row[0]),
    )


def wechat_profile(profile, trusted=False):
    if not isinstance(profile, dict):
        return None
    platform = profile.get("platform", profile.get("emulator_type"))
    if platform not in (None, "wechat"):
        return None
    if not (trusted or platform == "wechat" or is_wechat_title(profile.get("title", ""))):
        return None
    size, crop = profile.get("client_size"), profile.get("crop")
    if (not isinstance(size, list) or len(size) != 2
            or not isinstance(crop, list) or len(crop) != 4
            or any(isinstance(v, bool) or not isinstance(v, int) for v in size + crop)):
        return None
    w, h = size
    x, y, cw, ch = crop
    if min(w, h, cw, ch) <= 0 or min(x, y) < 0 or x + cw > w or y + ch > h:
        return None
    return dict(platform="wechat", title=str(profile.get("title", "")),
                client_size=list(size), crop=list(crop))


def profile_matches(profile, client_size):
    return wechat_profile(profile) is not None and profile["client_size"] == list(client_size)
