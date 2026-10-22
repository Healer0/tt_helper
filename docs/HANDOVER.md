# tt_fish 微信小程序适配 —— 交接文档

> 状态:微信小程序(PC 版微信)适配**代码已落地、单测已过**,实机验证(PoC 门禁)**未执行**——本环境为 Linux,PoC 需在 Windows + 微信上手动完成。
> 基线提交:`6fa940b`(HEAD);以下改动为未提交的工作区内容。设计来源:`~/.claude/plans/clever-meandering-parrot.md`(已批准的实施计划)。
> 最后更新:2026-10-22

---

## 一、背景与目标

原项目是 Windows 安卓模拟器(雷电/MuMu)钓鱼小游戏的自动按键机器人:截屏 → 图像识别游戏阶段 → 黄条时序预测 → 注入空格。本次目标:让同一款游戏以**微信小程序**跑在 **PC 版微信**里时也能自动操作。

结论:算法层(`vision/phase/speed/contact/controller/scheduling`)与平台无关**全部复用**;平台层(截屏窗口、输入注入、GUI 筛选)改造完成。核心差异:小程序按触控设计,输入从"空格键"改为"鼠标点击注入"。

**三个杀手级未知项必须在 Windows 实机 PoC 验证后才能宣称可用**:① 小程序是否有独立可捕获 HWND;② mss 截屏是否黑屏(WebGL 硬件加速);③ 点击注入是否被小程序识别为触摸。

---

## 二、当前实现状况(已完成)

### 改动文件清单

| 文件 | 改动 | 关键位置 |
|---|---|---|
| `fisher/windows.py` | 新增纯函数 `click_point`(归一化坐标→屏幕像素)、`absolute_mouse_coords`(0-65535 映射,越屏拒绝);`Windows.virtual_screen()`;`Windows.click_at(hwnd, box, x_norm, y_norm, hold_ms, cancelled, guard)`——完全镜像 `tap_space` 守卫顺序,新增手动鼠标按键检测(VK_LBUTTON/RBUTTON/MBUTTON),按下确已发出才补发抬起 | :45、:55、:124、:173 |
| `fisher/emulators.py` | `wechat` 窗口族(别名 微信/WeChat);`MANAGERS` 排除"图片查看器/视频号";`profile_matches` 对 wechat 放宽为"同族+同尺寸+同框选"(标题随版本变化) | :4-6、:44 |
| `fisher/config.py` | `CONFIG_VERSION=8`;新字段 `input_method`(space/click)、`click_point`(默认 [0.5,0.5])、`click_hold_ms`(默认 30)、`capture_backend`(mss/dxcam,dxcam 为预留);v7→v8 迁移:wechat 族自动 `input_method=click` 且 `min_action_interval_s` 默认提升至 0.9(仅当未手动调高时) | :12、:21、:51、:120 |
| `fisher/runtime.py` | `Runtime.__init__` 读取新字段 + `action_word` 文案;`dispatch()` 按 `input_method` 分支 `click_at`/`tap_space`(**其余调度、guard 双检、延迟学习零改动**);文案"模拟器/按空格"按输入方式切换;click 模式预览叠加黄色十字线;`capture_backend != "mss"` 时明确报错 | :32、:361、:461 |
| `main.py` | 下拉框自动含"微信小游戏"(EMULATORS 驱动);选项页新增输入方式单选、点击位置 X/Y、"画面中央"按钮、click_hold_ms;选微信自动勾选"仅观察"+点击模式;wechat 强制 `input_method=click`;状态栏文案输入方式感知 | `change_emulator`、`start`、`update_control` |
| `tests/test_click.py`(新) | 14 个用例:坐标映射边界/越界拒绝、守卫语义(无焦点/取消/guard/修饰键/手动鼠标)、发送序列 [2,1]、失败不补发抬起、hold 期间取消标记 interrupted | — |
| `tests/test_emulators.py` | +7 用例:wechat 族筛选与排除、profile 放宽、v8 迁移(wechat→click+0.9、ldplayer→space 不变、按 profile 标题推断)、非法字段校验 | — |
| `tests/test_phase.py` | `SimulatedRuntime` 支持 `click=True`;新增点击模式全 Runtime 仿真用例(与空格模式调度/命中一致) | — |
| `fisher/packaging.py` | `PUBLIC_FILES` 加入 `tests/test_click.py`(tools/poc 与本文档**不进**发布包) | — |
| `config.example.json` | 同步 4 个新字段(与 DEFAULTS 键集一致,发布校验依赖) | — |
| `.gitignore`/`.gitattributes`(新) | **原仓库缺失**(发布清单却强制要求)。现排除 `config.json`、`logs/`、`speed_profile.json`、`snapshots/`、`recordings/`、`trial_*`、`data/`、`dist/`、`.venv*`、`__pycache__` 等本机数据 | — |
| `README.md` | 新增"微信小游戏(实验性)"章节:用法、与模拟器差异、PoC 脚本说明、**账号风控声明**;配置表新增 4 个字段;迁移说明更新至 v8 | — |
| `tools/poc/`(新) | 4 个只读诊断脚本,详见第三节 | — |

### 设计要点(接手者须知)

1. **控制器只输出抽象"action",不感知输入方式**。`input_method` 的分支只存在于 `dispatch()` 一处(`runtime.py:461`)——这是刻意保持的单点,后续加新输入方式(如 ADB)照此扩展。
2. **`click_at` 是 fire-and-forget**:不维护 `owns_space`、不调 `release()`;down/up 同一调用内完成,`hold_ms` 只作按下到抬起间隔;`last_key_down_at/up_at` 语义复用,`trial_capture` 与延迟学习无需改动。
3. **wechat 安全默认**:选微信自动勾选"仅观察"、点击间隔 0.9s、保留失焦暂停/手动输入检测暂停——对应微信反自动化风控风险。
4. **`capture_backend: dxcam` 是预留字段**:配置校验已放行,`Runtime.run` 会明确报错"待 PoC 验证后接入",不会静默走错路径。

---

## 三、验证状态

### 测试(本环境:Linux + `.venv-ttfish/`,numpy 2.5.4 / opencv 5.0.0)

- `python selfcheck.py`:**190 个测试**,本次改动**零新增失败**;新增/扩展的 28 个用例全部通过。
- 迁移冒烟已验证:仓库真实 v2 config → v8 `input_method=space`(模拟器用户无感);v7 wechat 配置 → `click` + 0.9s。

### 既有失败(与本次改动无关,已在干净 HEAD 逐一比对确认)

| 失败 | 原因 |
|---|---|
| `test_trial` ×2、`test_diagnostics` ×3、`test_arrival` ×1、`test_followup` ×1(共 7) | TrialRecorder ZIP 导出在本机 Python 3.13 下失败(`last_bundle=None`),疑似 zipfile/线程时序环境问题 |
| `test_release` ×1、`test_windows_package` ×1 | 仓库缺 `.github/workflows/windows-portable.yml`、`.github/ISSUE_TEMPLATE/bug_report.md`(PUBLIC_FILES 白名单要求) |

---

## 四、下一步:Windows 实机 PoC 门禁(未执行,最高优先级)

环境:Windows + 微信 PC 版 + 小游戏;依赖 `pip install -r requirements.txt`。四个脚本均只读诊断、不进发布包,**必须按序执行**:

| # | 命令 | 判定标准(通过) | 失败 fallback |
|---|---|---|---|
| 0.1 | `python tools/poc/poc_windows.py` | 存在 client 区=游戏画面的独立 HWND(**结果 A**) | 结果 B(无独立 HWND)→ 跑 0.2;仍不行 → **必须**实现 `game_rect` 偏移(见五.1),否则方案不成立 |
| 0.2 | `python tools/poc/poc_launch.py [--args "--disable-gpu"]` | 沉浸式参数能弹出无边框小游戏窗口 | 全部参数无效 → 回到 `game_rect` 方案 |
| 0.3 | `python tools/poc/poc_capture.py` | 各阶段帧标准差>0、中位耗时<60ms、画面在动 | 微信关闭"使用硬件加速"重测 → 仍黑屏 → 接入 dxcam/WGC(见五.2) |
| 0.4 | `python tools/poc/poc_click.py` | 点击下钩按钮触发阶段变化;记录响应延迟 | 修 0-65535 映射/DPI → 试更长 hold(60ms)→ PostMessage 兜底 |
| 0.5 | `python replay.py --input <0.3截图> --crop 0 0 W H` | 各阶段识别置信度 ≥0.72 | 重采模板(见五.3) |
| 0.6 | 实机跑 3~5 轮并勾选"本次校准速度" | 校准收敛(≥18 有效样本) | 调 `input_latency_ms`/采样间隔 |

**门禁规则:0.3–0.6 任何一项失败,暂缓对外宣称可用,先补对应 fallback。** 0.1/0.2 的结果 A/B 决定五.1 是否要做。

---

## 五、按 PoC 结果分流的后续完善步骤

### 5.1 PoC 结果 B:`game_rect` 偏移支持(方案已预留,未实现)

小游戏嵌在微信主窗口/无边框窗口内、无独立 HWND 时:

1. `fisher/config.py`:profile 增加 `game_rect`(`[x,y,w,h]`,相对窗口 client 区)与校验。
2. `fisher/runtime.py:capture_box()`(:78):对外仍返回屏幕坐标 `win_left + game_rect.x + crop.x`,尺寸校验改为"client 尺寸 + game_rect 尺寸"。
3. `main.py` 框选流程(`crop`):先在窗口截图内框一次 game_rect,再在小图内二次框选 crop;`profile` 保存两者。
4. 测试:`tests/test_phase.py` 的 SimulatedRuntime 无需动;新增 `capture_box` 的 game_rect 用例。

### 5.2 截屏黑屏 → dxcam / WGC 后端

1. 先试微信关闭硬件加速(或 `poc_launch.py --args "--disable-gpu"`),注意 30fps 上限会改变速度标定,需重跑 0.6。
2. 仍失败:引入 dxcam(Desktop Duplication)或 Windows Graphics Capture,只允许在 `capture_backend` 层引入:
   - `fisher/runtime.py:run()` 的 mss 上下文改为按 `capture_backend` 选择后端;不同后端的 box 语义(整屏抓取+numpy 切片 vs 直接 grab)要统一。
   - `packaging/windows-runtime.lock.json` 加锁新依赖,走 `docs/WINDOWS.md` 的哈希流程;便携包验证跑 `build_windows.py`。
   - 移除 `runtime.py` 里现存的 dxcam 报错守卫。

### 5.3 模板/ROI 重标定(PoC 0.5 置信度不足时)

1. 用现有素材流程重采 `assets/templates/` 的 9 个模板(小程序画面),保持 `templates.py` 的 `TEMPLATE_DEFINITIONS` 尺寸一致。
2. 不建议双模板并存(每帧 matchTemplate 翻倍);若必须并存:`Detector.__init__` 加 `asset_dir` 参数,`runtime.run()` 按 `emulator_type` 选目录,同步 `packaging.py`。
3. `normalize()` 非保形拉伸差异约 2~3% 通常可容忍;ROI 像素约束(`2<=w<=22` 等)用 `replay.py` 实测复核。**改 normalize(letterbox/center-crop)是最后手段**——会破坏全局 336×598 坐标约定,需同步 `tests/fixtures.py` 与所有 ROI 常量。

### 5.4 前台判定失效(按 0.1 实测)

小游戏若在 `WeChatAppEx` 子进程独立顶层窗口:`windows.py:foreground_matches`(:121)改为双方 `GetAncestor(GA_ROOT)` 比较,并补 `tests/test_emulators.py` 用例。

### 5.5 实机回归(全部 PoC 通过后)

1. `dry_run=True` 观察:预览 state/fps 稳定跟随;十字线落在可点击区。
2. 小流量:关"仅观察",`max_casts=2`、`max_session_minutes=2`,验证 IDLE→CAST→WAIT→BITE→HOOK 闭环与 `action_ack_timeout_s`。
3. 黄条:勾选校准跑 3~5 轮,验证 HIT 命中与校准收敛。
4. 故障注入:运行中手动点鼠标/按修饰键 → 暂停;切窗口 → 失焦暂停;改窗口尺寸 → 报错重框选。

---

## 六、遗留风险与未决事项

1. **账号风控(最高风险)**:微信侧反自动化可能限流/封号。代码层默认已收敛(仅观察默认、0.9s 间隔),但 README 与界面声明不能替代用户自行确认平台规则。**不建议**后续引入内存读取/AES 注入等更高风险方案。
2. **git 历史隐私泄露(未处理)**:`config.json`(作者框选坐标)与 `logs/session_20261021_161203_733593.jsonl` 仍留在提交 `976aec5` 的历史中。若仓库公开,需 `git filter-repo` 清理历史并强制推送,仅删文件无效。
3. **发布链路缺文件(既有问题)**:`.github/workflows/windows-portable.yml`、`.github/ISSUE_TEMPLATE/bug_report.md` 缺失,`build_release.py`/`build_windows.py` 与 `test_release` 当前会失败。
4. **7 个 TrialRecorder 导出测试失败(既有,环境相关)**:在 Python 3.13 下 ZIP 导出失败,需排查 `fisher/trial_capture.py` 的 `_export` 线程(建议优先在 Windows/官方锁定版 Python 3.12.15 复测,再决定是否修代码)。
5. **`capture_backend: dxcam` 为预留**:校验放行但运行时明确报错,不会静默错误。
6. **既有技术债(与本次无关,可选)**:`contact`/`center` 计时策略不可达但代码保留;`purple.png` 模板死资源;ROI 硬编码散布;正式构建无运行日志;录制崩溃一致性(见初次分析报告)。

---

## 七、关键文件索引

| 文件 | 接手要点 |
|---|---|
| `fisher/windows.py` | 点击注入全部逻辑(`click_point` :45、`click_at` :173);新增输入方式照此扩展 |
| `fisher/runtime.py` | 输入分支唯一改动点 `dispatch` :461;`capture_box` :78 是 game_rect 改造点 |
| `fisher/config.py` | v8 字段 :21、校验 :51、迁移 :120;新增字段须同步 `config.example.json` 与 DEFAULTS |
| `fisher/emulators.py` | wechat 族 :4-6;标题别名集中在此维护(微信更新改标题只动这里) |
| `main.py` | 选微信自动安全默认(`change_emulator`);wechat 强制 click(`start`) |
| `tests/test_click.py` | 新输入方式的守卫测试模板 |
| `tools/poc/` | 实机验证脚本,不进发布包;结论回填后按五分流 |
| `docs/HANDOVER.md` | 本文档 |

## 八、提交建议

工作区改动建议分批提交(遵循项目 conventional commits 风格):

1. `feat: 微信小游戏鼠标点击输入与窗口支持` — windows.py / emulators.py / config.py / runtime.py / main.py / config.example.json / tests / README.md
2. `chore: 补充 .gitignore 与 .gitattributes,排除本机运行数据` — .gitignore / .gitattributes(注意:已提交的 config.json 与 logs 需另行从历史清理)
3. `chore: 新增微信小游戏 PoC 诊断脚本` — tools/poc/

提交前:在 Windows 上跑一遍 PoC 门禁(第四节),把 0.1~0.6 结论填入本文件"验证状态"。
