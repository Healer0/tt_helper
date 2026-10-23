# SPDX-License-Identifier: GPL-3.0-only
"""PyCharm直接运行本文件。工作目录可任意，数据路径统一相对本工程。"""
import sys

def main(show_errors=True):
    if sys.platform != "win32":
        print("实时助手需要Windows。离线检查请运行 selfcheck.py，录像分析请运行 replay.py。")
        return 1
    from fisher.windows import enable_dpi_awareness
    enable_dpi_awareness()
    import tkinter as tk
    from tkinter import ttk, messagebox
    import queue
    import mss
    from PIL import Image, ImageTk
    from fisher.config import load_config, save_config, validate_config, HOTKEYS
    from fisher.config import DATA_ROOT
    from fisher.windows import Windows
    from fisher.runtime import Runtime
    from fisher import __version__
    from fisher.project import FREE_NOTICE
    from fisher.speed import load_profile,save_profile,reference_profile
    from fisher.wechat import profile_matches

    class App:
        def __init__(self, root):
            self.root = root
            self.win = Windows()
            self.cfg = load_config()
            self.runtime = None
            self.profile = None
            self.hwnd = None
            self.options = []
            root.title(f"tt_fish · 钓鱼助手 {__version__}")
            width = min(1180, root.winfo_screenwidth() - 80)
            height = min(1180, root.winfo_screenheight() - 90)
            root.geometry(f"{width}x{height}")
            root.minsize(min(980, width), min(960, height))
            root.protocol("WM_DELETE_WINDOW", self.close)
            style = ttk.Style()
            style.configure("TLabel", font=("Microsoft YaHei UI", 10))
            style.configure("TButton", font=("Microsoft YaHei UI", 10))
            footer = ttk.Frame(root, padding=(10, 5))
            footer.pack(side="bottom", fill="x")
            ttk.Label(footer, text=FREE_NOTICE, font=("Microsoft YaHei UI", 9), foreground="#555555").pack(side="left")
            top = ttk.Frame(root, padding=10)
            top.pack(fill="x")
            ttk.Label(top, text="1. 选择微信小游戏窗口").pack(side="left")
            self.combo = ttk.Combobox(top, state="readonly", width=30)
            self.combo.pack(side="left", padx=8, fill="x", expand=True)
            ttk.Button(top, text="刷新", command=self.refresh).pack(side="right")
            self.combo.bind("<<ComboboxSelected>>", self.bind_window)
            # 顶部固定显示运行状态与暂停原因，避免提示挤出窗口底部。
            status = ttk.Frame(root, padding=(12, 0, 12, 8))
            status.pack(fill="x")
            self.control_status = tk.StringVar(value="尚未监测 · 尚未启动钓鱼")
            self.notice = tk.StringVar(value="选择窗口并框选游戏画面后，开启监测和钓鱼。")
            ttk.Label(status, textvariable=self.control_status, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
            ttk.Label(status, textvariable=self.notice, wraplength=740, foreground="#245b89").pack(anchor="w", pady=(2,0))
            self.preview_shown = tk.BooleanVar(value=self.cfg["show_preview"])
            preview_bar = ttk.Frame(status)
            preview_bar.pack(fill="x", pady=(3, 0))
            self.preview_button = ttk.Button(preview_bar, text="隐藏预览" if self.preview_shown.get() else "显示预览",
                                             command=self.toggle_preview)
            self.preview_button.pack(side="left")
            ttk.Button(preview_bar, text="图文操作手册", command=self.show_manual).pack(side="right")
            content = ttk.Frame(root)
            content.pack(fill="both", expand=True)
            body = ttk.Frame(content, padding=(10, 0, 10, 10))
            body.pack(fill="both", expand=True)
            self.preview = ttk.Label(body, text="框选后显示游戏识别预览", anchor="center")
            if self.preview_shown.get():
                self.preview.pack(side="left", fill="both", padx=(0, 12))
            panel = ttk.Frame(body)
            self.panel = panel
            panel.pack(side="left", fill="both", expand=True)
            crop_row = ttk.Frame(panel)
            crop_row.pack(fill="x", pady=(3, 2))
            ttk.Button(crop_row, text="2. 框选完整游戏画面", command=self.prepare_crop).pack(side="left", fill="x", expand=True)
            ttk.Button(crop_row, text="查看框选示例", command=self.show_crop_example).pack(side="right", padx=(8, 0))
            ttk.Label(panel, text="选中完整游戏及底栏，排除微信标题栏、工具栏和外侧黑边。", wraplength=620).pack(anchor="w", pady=2)
            self.crop_status = tk.StringVar(value="尚未框选")
            ttk.Label(panel, textvariable=self.crop_status, wraplength=620).pack(anchor="w", pady=2)
            tabs = ttk.Notebook(panel)
            tabs.pack(fill="x", pady=5)
            options = ttk.Frame(tabs, padding=8)
            settings = ttk.Frame(tabs, padding=8)
            speed_options = ttk.Frame(tabs, padding=8)
            recording = ttk.Frame(tabs, padding=8)
            settings_columns = ttk.Frame(settings)
            settings_columns.pack(fill="x")
            input_settings = ttk.Frame(settings_columns)
            input_settings.pack(side="left", fill="both", expand=True, padx=(0, 12))
            shortcut_settings = ttk.Frame(settings_columns)
            shortcut_settings.pack(side="left", fill="both", expand=True)
            tabs.add(options, text="钓鱼选项")
            tabs.add(settings, text="快捷键与延迟")
            tabs.add(speed_options, text="速度与校准")
            tabs.add(recording, text="录制")
            self.settings_widgets = []
            self.dry = tk.BooleanVar(value=self.cfg["dry_run"])
            self.continuous = tk.BooleanVar(value=self.cfg["continuous_fishing"])
            self.adaptive = tk.BooleanVar(value=self.cfg["adaptive_latency"])
            self.calibrate = tk.BooleanVar(value=False)
            try:
                speed_profile=load_profile(DATA_ROOT/"speed_profile.json",self.cfg["speed_fraction_per_s"])
            except (OSError,ValueError,TypeError):
                speed_profile=reference_profile()
            self.speed_hint=tk.StringVar(value=f'固定速度：{speed_profile["fraction_per_second"]*100:.2f}%条宽/秒')
            ttk.Label(speed_options,textvariable=self.speed_hint,wraplength=440).pack(anchor="w",pady=4)
            calibration=ttk.Checkbutton(speed_options,text="本次校准速度",variable=self.calibrate)
            calibration.pack(anchor="w",pady=4)
            self.settings_widgets.append(calibration)
            ttk.Label(speed_options,text="不勾选时使用已保存的比例速度；校准稳定后自动保存。\n比例以判定条的可见全宽为单位。",wraplength=440).pack(anchor="w",pady=4)
            restore=ttk.Button(speed_options,text="恢复参考速度",command=self.restore_speed)
            restore.pack(anchor="w",pady=4)
            self.settings_widgets.append(restore)
            for label,var,cmd in (("不停钓（忽略次数和时长上限）", self.continuous, self.update_limits),
                                  ("仅观察，不发送输入", self.dry, None)):
                widget = ttk.Checkbutton(options, text=label, variable=var, command=cmd)
                widget.pack(anchor="w", pady=3)
                self.settings_widgets.append(widget)
            ttk.Label(options, text="比例坐标相对框选画面；预览十字线和随机圆圈应全部位于按钮内。", wraplength=620,
                      foreground="#555555").pack(anchor="w", pady=(0, 4))
            point_row = ttk.Frame(options)
            point_row.pack(fill="x", pady=3)
            ttk.Label(point_row, text="点击位置 X / Y（0~1）").pack(side="left")
            self.click_x = tk.StringVar(value=str(self.cfg["click_point"][0]))
            self.click_y = tk.StringVar(value=str(self.cfg["click_point"][1]))
            self.click_entries = []
            for var, padx in ((self.click_x, (8, 0)), (self.click_y, (4, 0))):
                entry = ttk.Entry(point_row, textvariable=var, width=5)
                entry.pack(side="left", padx=padx)
                self.click_entries.append(entry)
                self.settings_widgets.append(entry)
            ttk.Button(point_row, text="画面中央", command=self.reset_click_point).pack(side="left", padx=(6, 0))
            jitter_row = ttk.Frame(options)
            jitter_row.pack(fill="x", pady=3)
            ttk.Label(jitter_row, text="随机偏移半径（短边%，0关闭）").pack(side="left")
            self.click_jitter = tk.StringVar(value=f'{self.cfg["click_jitter_ratio"]*100:g}')
            jitter_entry = ttk.Entry(jitter_row, textvariable=self.click_jitter, width=5)
            jitter_entry.pack(side="right")
            self.click_entries.append(jitter_entry)
            self.settings_widgets.append(jitter_entry)
            self.update_click_entries()
            fields = [(options, "capture_every_n_frames", "每多少帧截图一次（1～60）"),
                      (options, "max_casts", "单次最多下钩次数"),
                      (options, "max_session_minutes", "单次最长运行（分钟）"),
                      (input_settings, "input_latency_ms", "响应延迟基准（毫秒）"),
                      (input_settings, "click_hold_ms", "点击按住（毫秒）"),
                      (input_settings, "result_wait_s", "结算等待（秒）"),
                      (input_settings, "unknown_timeout_s", "未知画面等待（秒）"),
                      (input_settings, "timing_timeout_s", "黄条等待（秒）")]
            self.values = {}
            self.entries = {}
            for parent, key, label in fields:
                row = ttk.Frame(parent)
                row.pack(fill="x", pady=3)
                ttk.Label(row, text=label).pack(side="left")
                var = tk.StringVar(value=str(self.cfg[key]))
                self.values[key] = var
                entry = ttk.Entry(row, textvariable=var, width=8)
                entry.pack(side="right")
                self.entries[key] = entry
                self.settings_widgets.append(entry)
                if key == "capture_every_n_frames":
                    ttk.Label(parent, text="值越小采样越快；卡顿时可调大。",
                              wraplength=620, foreground="#555555").pack(anchor="w", pady=(0, 2))
            adaptive = ttk.Checkbutton(shortcut_settings, text="补偿本机输入耗时", variable=self.adaptive)
            adaptive.pack(anchor="w", pady=3)
            self.settings_widgets.append(adaptive)
            self.hotkey_values = {}
            for key, label in (("toggle_hotkey", "开始／暂停"), ("pause_hotkey", "紧急暂停"),
                               ("snapshot_hotkey", "保存游戏截图")):
                row = ttk.Frame(shortcut_settings)
                row.pack(fill="x", pady=3)
                ttk.Label(row, text=label).pack(side="left")
                var = tk.StringVar(value=self.cfg[key])
                self.hotkey_values[key] = var
                combo = ttk.Combobox(row, textvariable=var, values=HOTKEYS, state="readonly", width=6)
                combo.pack(side="right")
                self.settings_widgets.append(combo)
            ttk.Label(settings, text=f'结果页重试间隔：{self.cfg["result_retry_s"]:g}秒 ± {self.cfg["result_retry_jitter_ms"]:g}毫秒', wraplength=490).pack(anchor="w", pady=3)
            ttk.Label(settings, text="等待填0不限；修改设置前请停止监测。", wraplength=620).pack(anchor="w", pady=3)
            ttk.Button(recording, text="3秒后录制15秒手动操作", command=self.record).pack(fill="x", pady=5)
            ttk.Label(recording, text="先开启监测，再点击录制并切回游戏窗口。\n录制期间手动钓鱼，自动操作暂停。\n录像和时间戳保存在recordings文件夹。", wraplength=490).pack(anchor="w", pady=5)
            self.update_limits()
            action_row = ttk.Frame(panel)
            action_row.pack(fill="x", pady=(6, 4))
            self.start_button = ttk.Button(action_row, text="3. 应用设置并开启监测", command=self.start)
            self.start_button.pack(side="left", fill="x", expand=True)
            self.launch_button = ttk.Button(action_row, text="4. 3秒后启动钓鱼", command=self.launch, state="disabled")
            self.launch_button.pack(side="left", fill="x", expand=True, padx=(6, 0))
            stop_row = ttk.Frame(panel)
            stop_row.pack(fill="x", pady=4)
            ttk.Button(stop_row, text="暂停／取消启动", command=self.pause).pack(side="left", fill="x", expand=True)
            ttk.Button(stop_row, text="停止监测", command=self.stop).pack(side="left", fill="x", expand=True, padx=(6,0))
            self.hotkey_hint = tk.StringVar()
            self.update_hotkey_hint()
            ttk.Label(panel, textvariable=self.hotkey_hint, wraplength=620).pack(anchor="w", pady=3)
            ttk.Label(panel, text="失焦自动暂停；切回游戏后明确启动才恢复。", wraplength=620).pack(anchor="w", pady=2)
            self.state = tk.StringVar(value="等待设置")
            self.detail = tk.StringVar(value="输入点应同时覆盖钓鱼按钮与“开心收下”。")
            ttk.Label(panel, textvariable=self.state, wraplength=620, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", pady=(5, 2))
            ttk.Label(panel, textvariable=self.detail, wraplength=620).pack(anchor="w", pady=2)
            self.refresh()
            root.after(50, self.poll)

        def restore_speed(self):
            if self.runtime:
                return
            try:
                profile=reference_profile()
                save_profile(DATA_ROOT/"speed_profile.json",profile)
                self.speed_hint.set(f'固定速度：{profile["fraction_per_second"]*100:.2f}%条宽/秒 · 参考值')
            except OSError as exc:
                messagebox.showerror("无法保存速度",str(exc))

        def toggle_preview(self):
            shown = not self.preview_shown.get()
            self.preview_shown.set(shown)
            self.preview_button.configure(text="隐藏预览" if shown else "显示预览")
            if shown:
                self.preview.pack(side="left", fill="both", padx=(0,12), before=self.panel)
            else:
                self.preview.pack_forget()
                self.preview.configure(image="", text="预览已隐藏")
                self.preview.image = None
            self.cfg["show_preview"] = shown
            if self.runtime:
                self.runtime.command("show_preview" if shown else "hide_preview")
            try:
                save_config(self.cfg)
            except OSError as exc:
                self.notice.set(f"无法保存预览设置：{exc}")

        def show_manual(self):
            from fisher.config import ROOT
            import webbrowser
            if self.runtime:
                self.runtime.command("pause")
            try:
                candidates = (ROOT / "docs/USER_GUIDE.html", ROOT.parent / "图文操作手册.html")
                path = next((path for path in candidates if path.is_file()), None)
                if path is None:
                    raise OSError("未找到图文操作手册，请重新完整解压发布包。")
                webbrowser.open(path.resolve().as_uri())
            except (OSError, ValueError) as exc:
                messagebox.showerror("无法打开操作手册", str(exc))

        def show_crop_example(self):
            from fisher.config import ROOT
            if self.runtime:
                self.runtime.command("pause")
            try:
                with Image.open(ROOT / "docs/images/crop-example.png") as src:
                    picture = src.convert("RGB")
                picture.thumbnail((440, max(360, self.root.winfo_screenheight()-160)))
                win = tk.Toplevel(self.root)
                win.title("框选示例")
                photo = ImageTk.PhotoImage(picture)
                label = ttk.Label(win, image=photo)
                label.image = photo
                label.pack(padx=8, pady=8)
                ttk.Label(win, text="只选红框内完整游戏画面。排除外侧黑边、标题栏和工具栏，\n保留游戏内底部带按键提示的黑色栏。", wraplength=440).pack(padx=8, pady=(0, 8))
            except (OSError, ValueError) as exc:
                messagebox.showerror("无法显示示例", str(exc))

        def update_limits(self):
            disabled = self.continuous.get() or self.runtime is not None
            for key in ("max_casts", "max_session_minutes"):
                self.entries[key].configure(state="disabled" if disabled else "normal")

        def update_click_entries(self):
            state = "disabled" if self.runtime else "normal"
            for entry in self.click_entries:
                entry.configure(state=state)

        def reset_click_point(self):
            self.click_x.set("0.5")
            self.click_y.set("0.5")

        def update_hotkey_hint(self):
            self.hotkey_hint.set(f'切回游戏窗口后：{self.cfg["toggle_hotkey"]} 开始／暂停\n'
                                 f'{self.cfg["pause_hotkey"]}／Esc 紧急暂停 · {self.cfg["snapshot_hotkey"]} 保存截图')

        def lock_settings(self, locked):
            for widget in self.settings_widgets:
                widget.configure(state="disabled" if locked else ("readonly" if isinstance(widget, ttk.Combobox) else "normal"))
            self.combo.configure(state="disabled" if locked else "readonly")
            self.start_button.configure(state="disabled" if locked else "normal")
            self.update_limits()
            self.update_click_entries()

        def refresh(self):
            if self.runtime:
                messagebox.showinfo("请先停止", "更换窗口前请先停止监测。")
                return
            previous_hwnd = self.hwnd
            self.hwnd = self.profile = None
            self.crop_status.set("尚未框选")
            self.preview.configure(image="", text="框选后显示游戏识别预览")
            self.preview.image = None
            self.options = self.win.windows()
            self.combo["values"] = [f"{title}  [窗口 {hwnd}]" for hwnd,title in self.options]
            self.combo.set("")
            if self.options:
                old_title = (self.cfg.get("profile") or {}).get("title")
                index = next((i for i, (hwnd, _) in enumerate(self.options) if hwnd == previous_hwnd), None)
                if index is None:
                    index = next((i for i, (_, title) in enumerate(self.options) if title == old_title), 0)
                self.combo.current(index)
                self.bind_window()
                self.notice.set("选择微信小游戏窗口并框选完整游戏画面。")
            else:
                self.notice.set("未找到微信游戏窗口。请在微信中打开小游戏后刷新。")

        def bind_window(self, event=None):
            if self.runtime:
                messagebox.showinfo("请先停止", "更换窗口前请先停止监测。")
                return
            i = self.combo.current()
            if i < 0: return
            self.hwnd, title = self.options[i]
            self.profile = None
            old = self.cfg.get("profile")
            try:
                box = self.win.client_box(self.hwnd)
                if profile_matches(old, box[2:]):
                    self.profile = old
            except OSError:
                pass
            self.crop_status.set("已载入同窗口、同尺寸的框选；请核对预览" if self.profile else "尚未框选")

        def prepare_crop(self):
            if self.runtime:
                messagebox.showinfo("请先停止", "框选前请先停止监测。")
                return
            if not self.hwnd: return
            self.notice.set("3秒后截图，请立即将所选游戏窗口置于前台")
            self.root.iconify()
            self.root.after(3000, self.crop)

        def crop(self):
            try:
                crop_hwnd = self.hwnd
                if not self.win.foreground_matches(self.hwnd):
                    raise ValueError("所选游戏窗口不在前台，请重新框选并在3秒内切回游戏窗口")
                left, top, w, h = self.win.client_box(self.hwnd)
                with mss.mss() as sct:
                    shot = sct.grab({"left":left,"top":top,"width":w,"height":h})
                    rgb = Image.frombytes("RGB", (shot.width, shot.height), shot.rgb)
                self.root.deiconify()
                win = tk.Toplevel(self.root)
                win.title("拖框选择完整游戏画面，再点确认")
                win.transient(self.root)
                win.grab_set()
                scale = min(1, 900/w, 680/h)
                display = rgb.resize((round(w*scale),round(h*scale)))
                photo = ImageTk.PhotoImage(display)
                canvas = tk.Canvas(win, width=display.width, height=display.height, highlightthickness=0)
                canvas.pack()
                canvas.create_image(0,0,image=photo,anchor="nw")
                canvas.image = photo
                coords = []
                rectangle = [None]
                def start(event):
                    coords[:] = [event.x,event.y,event.x,event.y]
                    if rectangle[0]: canvas.delete(rectangle[0])
                    rectangle[0] = canvas.create_rectangle(*coords, outline="#ff3030", width=2)
                def drag(event):
                    if coords:
                        coords[2:] = [max(0,min(event.x,display.width)),max(0,min(event.y,display.height))]
                        canvas.coords(rectangle[0],*coords)
                canvas.bind("<Button-1>", start)
                canvas.bind("<B1-Motion>", drag)
                def confirm():
                    if len(coords) != 4: return
                    x1,x2 = sorted([coords[0],coords[2]])
                    y1,y2 = sorted([coords[1],coords[3]])
                    x,y = round(x1/scale),round(y1/scale)
                    cw,ch = min(w-x,round((x2-x1)/scale)),min(h-y,round((y2-y1)/scale))
                    if cw < 200 or ch < 350 or not .35 <= cw/ch <= .85:
                        messagebox.showerror("范围不合适", "请框选完整竖屏游戏画面，包括底部游戏栏，排除外侧黑边。", parent=win)
                        return
                    if self.hwnd != crop_hwnd:
                        messagebox.showerror("窗口已改变", "请重新框选当前窗口。", parent=win)
                        return
                    self.profile = {"title":self.win.title(crop_hwnd),"client_size":[w,h],"crop":[x,y,cw,ch],
                                    "platform":"wechat"}
                    self.cfg["profile"] = self.profile
                    save_config(self.cfg)
                    self.crop_status.set(f"已框选 {cw}×{ch}；窗口大小变化后需要重新框选")
                    win.destroy()
                ttk.Label(win, text="拖选完整游戏，排除游戏外侧黑边和工具栏；保留底部游戏栏。", wraplength=round(w*scale)).pack(pady=5)
                ttk.Button(win,text="确认选区",command=confirm).pack(pady=6)
            except Exception as exc:
                self.root.deiconify()
                messagebox.showerror("框选失败", str(exc))

        def start(self):
            if self.runtime:
                messagebox.showinfo("请先停止", "应用新设置前先点“停止监测”，然后重新开始。")
                return
            if not self.hwnd or not self.profile:
                messagebox.showinfo("先框选", "请先选择游戏窗口并框选完整游戏画面。")
                return
            try:
                cfg = dict(self.cfg)
                cfg["dry_run"] = self.dry.get()
                cfg["continuous_fishing"] = self.continuous.get()
                cfg["timing_mode"] = "phase"
                cfg["adaptive_latency"] = self.adaptive.get()
                cfg["calibrate_speed"] = self.calibrate.get()
                cfg["show_preview"] = self.preview_shown.get()
                cfg["click_point"] = [float(self.click_x.get()), float(self.click_y.get())]
                cfg["click_jitter_ratio"] = float(self.click_jitter.get()) / 100
                for key,var in self.values.items():
                    if cfg["continuous_fishing"] and key in ("max_casts", "max_session_minutes"):
                        continue
                    cfg[key] = float(var.get())
                cfg.update({key:var.get() for key,var in self.hotkey_values.items()})
                cfg = validate_config(cfg)
                self.cfg = cfg
                save_config(cfg)
                self.runtime = Runtime(self.win,self.hwnd,self.profile,cfg)
                self.runtime.thread.start()
                self.lock_settings(True)
                self.update_hotkey_hint()
                self.launch_button.configure(state="normal", text="4. 3秒后启动观察" if cfg["dry_run"] else "4. 3秒后启动钓鱼")
                self.control_status.set("仅监测 · 尚未启动钓鱼")
                self.notice.set(f'监测已开启；切回游戏窗口按{cfg["toggle_hotkey"]}，或点击第4步并切回游戏窗口。')
            except Exception as exc:
                messagebox.showerror("无法开始", str(exc))

        def stop(self):
            if self.runtime:
                self.runtime.stop.set()
                self.launch_button.configure(state="disabled")
                self.notice.set("正在停止监测并释放鼠标…")

        def launch(self):
            if self.runtime and not self.runtime.stop.is_set():
                self.runtime.command("arm")

        def pause(self):
            if self.runtime:
                self.runtime.command("pause")

        def update_control(self, data):
            if data["dry_run"]:
                mode = "只观察，不发送输入"
            else:
                mode = "自动点击"
            phase = "等待3秒启动" if data.get("pending") else ("运行中" if data["active"] else "已暂停")
            self.control_status.set(f"{mode} · {phase}")

        def record(self):
            if self.runtime:
                self.runtime.command("pause")
                target = self.runtime
                self.notice.set("请在3秒内将游戏窗口置前；随后手动钓鱼15秒")
                self.root.after(3000, lambda: target.command("record") if self.runtime is target else None)

        def poll(self):
            r = self.runtime
            if r:
                self.speed_hint.set(r.speed_status)
                if r.calibration_complete:
                    self.calibrate.set(False)
                try:
                    while True:
                        kind, data = r.messages.get_nowait()
                        if kind == "notice": self.notice.set(data)
                        elif kind == "control":
                            self.update_control(data)
                            self.notice.set(data["reason"])
                        elif kind == "frame":
                            frame,info = data
                            if self.preview_shown.get() and frame is not None:
                                photo = ImageTk.PhotoImage(Image.fromarray(frame[:,:,::-1]))
                                self.preview.configure(image=photo,text="")
                                self.preview.image = photo
                            mode = "观察" if info["dry_run"] else "自动"
                            self.update_control(info)
                            if not info["active"]:
                                self.notice.set(info["pause_reason"])
                            self.state.set(f'{info["state"]} · {mode} · '+("运行" if info["active"] else "暂停"))
                            limit = "不停钓" if info["continuous"] else "限次／限时"
                            self.detail.set(f'{info["reason"]}\n实际截图 {info["fps"]:.1f} 次/秒 · {limit}\n本次下钩 {info["casts"]} 次，结果页 {info["results"]} 次')
                        elif kind == "finished":
                            r.thread.join(timeout=.1)
                            self.runtime = None
                            self.lock_settings(False)
                            self.launch_button.configure(state="disabled")
                            self.control_status.set("监测已停止 · 不发送输入")
                            self.state.set("监测已停止")
                except queue.Empty: pass
            self.root.after(50,self.poll)

        def close(self):
            if self.runtime and self.runtime.thread.is_alive():
                self.runtime.stop.set()
                self.root.after(50,self.close)
            else:
                self.root.destroy()

    root = tk.Tk()
    try:
        App(root)
        root.mainloop()
    except Exception as exc:
        from tkinter import messagebox
        if show_errors:
            messagebox.showerror("启动失败", str(exc))
        root.destroy()
        raise
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ImportError as exc:
        print(f"当前Python解释器缺少依赖：{exc}\n请在PyCharm中选择已安装依赖的Anaconda解释器。依赖清单见requirements.txt。")
        raise
