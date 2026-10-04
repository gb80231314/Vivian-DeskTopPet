# Vivian 桌面宠物 🌸

> **Version 1.0.9** | **Designed by Louis_Qi for Vivian**

一只会看你心情的 Q 版桌面宠物。会自然地随机眨眼，电脑空闲时捧着白雏菊开心微笑，CPU 忙疯时
抱臂生气，长时间不理她还会朝你叹气；自定义语音包让她开口说话，说出"Hi, Vivian"能唤醒她，
接入大模型 API 后还能多轮聊天；电脑放音乐时她会跟着节奏即兴起舞——六组舞步随机切换。

**多平台**：同一份代码可在 Windows 与 macOS 上运行。Windows 直接下载安装包；macOS 在 Mac
上一键构建 `.app` 与 `.dmg`。

**开源地址**：

- GitHub：<https://github.com/gb80231314/Vivian-DeskTopPet>
- Gitee：<https://gitee.com/Louis-QI/Vivian-DeskTopPet>

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 🥚 **首次启动孵化** | 首次启动图标放大、裂开，人物从蛋壳中间蹦出打招呼（可在设置中重播） |
| 🌼 **捧花待机** | 双手捧白色雏菊花束，轻微呼吸起伏 |
| 👁️ **自然眨眼** | 待机时随机间隔 2.8~6.5 秒自然眨眼（偶尔双眨），**眼睑贴合真实眼位**（眼睛逐帧跟踪）；观察模式下自动停用 |
| 😊 **CPU 情绪联动** | 负载 < 35% 开心捧花 / 35~70% 平静 / > 70% 生气抱臂跺脚 |
| 😉 **wink 俏皮眨眼** | 长时间无点击自动触发（提醒时间可在设置中自定义，5~600 秒，默认 45 秒），头部放大 → 眨眼比 V → 回弹复原 |
| 👀 **观察模式** | 原画风格眼睛实时跟随鼠标方向（16 方向，棕色虹膜+睫毛线） |
| 🎯 **跟随鼠标** | 宠物自动跟随鼠标移动（**与观察模式二选一**） |
| 👋 **举臂挥手** | 右臂高举过头挥动打招呼（肩关节圆盖衔接，自然） |
| 😮‍💨 **失败叹气** | 吸气上挺 → 呼气下沉 + 卡通叹气云飘散 + "唉……先叹口气……" |
| 🎵 **语音包** | 按事件自动播放语音（打招呼/开心/生气/wink/失败/挥手），内置"甜嗓默认"包，支持自定义语音包与音量调节 |
| 🎙️ **语音交互** | 唤醒词 **"Hi, Vivian"** 语音唤醒（本地引擎：噪声抑制 + 音节节奏匹配，托盘可一键声学校准，校准后只听你的 "Hi, Vivian"）；唤醒后随机应答（气泡+语音）；自动检测麦克风（开机未就绪自动重试），无麦克风优雅降级；设置中可接入 OpenAI 兼容模型 API 实现语音对话（选填：多轮上下文、转写/对话模型分离、一键测试连接） |
| 💃 **音乐跳舞** | 电脑播放音乐时自动跟着节奏跳舞：**6 组舞步随机抽取**（摇摆 / 弹跳 / 扭动 / 旋转 / 跳跃 / 挥手），每 4~8 拍随机换一支、循环播放不卡顿；跳舞时鼠标悬停在她身上会暂停，移开后继续（设置中开启）。音乐检测常驻一个系统声音监听通道（约 +5~15MB 内存、CPU 极低），设置中有占用提醒，仅 Windows |
| 💬 **气泡自适应** | Apple 通知卡片风格气泡（圆角卡片 + 主题色 + 柔和投影），自动避开屏幕边缘与任务栏，宠物在四角时自动调整方向，永不裁切 |
| ⏱️ **自定义提醒时间** | wink 提醒触发时间 5~600 秒可调 |
| 🎲 **行为模式** | 调皮 / 悠闲 / 好奇 / 活跃 / 关闭，随机切换动作 |
| 🏃 **12+4 种动画** | 12 组手绘动画（待机 / 跑动 / 挥手 / 跳跃 / 工作 / 审阅 / 生气 / 眨眼…每动画 16 帧丝滑过渡）+ 启动时程序化合成的 4 组高帧率舞蹈动画（各 24 帧、12~14fps） |
| 🎨 **软边贴合** | 水彩软边无描边风格，可与桌面背景自然融合（可在设置中调整） |
| 🧚 **更换形象向导** | 分步教学 + 自动换装：选一张角色图、挑一种 Q 版风格（实时预览），后台自动生成 12 组 × 16 帧全套动画（弹窗进度条），完成后**无需重启立即换装**；一键恢复默认 |
| ⚙️ **完整设置面板** | 右键宠物 → ⚙️ 设置（黑绿黄蓝像素风 UI，赛博朋克 × 可爱，各分区带像素 logo） |
| 🚀 **开机自启** | 设置面板一键开关（Windows 注册表 / macOS LaunchAgent） |
| 🌙 **托盘常驻** | 关闭窗口不退出，托盘图标可再召唤 |
| 🖥️ **跨平台** | 同一份代码，Windows / macOS 行为一致 |

---

## 📥 安装

### Windows

**方式一：安装版（推荐）**
1. 双击 `release/QPet-Setup.exe`
2. 按提示安装（可选：桌面快捷方式 / 开机自启）
3. 安装完成自动启动

**方式二：绿色版**
1. 解压 `release/Vivian-Pet-Portable-Windows.zip` 到任意目录
2. 双击 `QPet.exe` 运行

### macOS

⚠️ PyInstaller 不能交叉编译——必须在 Mac 上构建。

最快路径（二选一）：
1. Windows 上先 `python scripts/build_source_dmg.py` 生成源码 DMG
   （`release/Vivian-Pet-Source-V1.0.5.dmg`），拷到 Mac 挂载；
   或直接把项目目录（含 `app/`、`scripts/`、`assets/`）拷到 Mac
2. 在 Mac 上执行：
   ```bash
   cd scripts
   python3 build_mac.py
   ```
3. 产出 `scripts/dist/Vivian.app` 与 `scripts/dist/Vivian-Pet-macOS.dmg`

详见 [`docs/MAC_BUILD.md`](docs/MAC_BUILD.md)。

---

## 🎮 使用

- **左键短按**：弹出动画选择菜单（含程序化合成的舞蹈动作：摇摆 / 弹跳 / 扭动 / 旋转）
- **左键拖拽**：移动宠物位置
- **右键**：扇形菜单（跟随 / 观察 / 活动 / 设置 / 隐藏 / 退出）——Apple 风格磨砂圆钮 + SF 风格单色线性图标，悬停系统蓝高亮；Windows 上经 UpdateLayeredWindow 呈现逐像素透明，macOS 上经原生透明 NSWindow，两平台观感一致
- **右键 → ⚙️ 设置**：缩放 / 行为模式 / 跟随 / 观察（二选一）/ 开机启动 / 情绪联动 / wink / 提醒时间 / 音乐跳舞 / 语音包 / 边缘处理 / 关于（毛玻璃 UI）

### 自定义语音包

1. 打开设置 → 语音包 → 📂 打开语音包目录
   - Windows：`%APPDATA%/QPet/voicepacks/`
   - macOS：`~/Library/Application Support/QPet/voicepacks/`
2. 新建文件夹作为包名，放入对应事件的音频文件（mp3/wav）：

```
voicepacks/
└── 我的语音包/
    ├── greet.mp3      # 打招呼（孵化完成/启动）
    ├── happy.mp3      # 开心（CPU 负载低）
    ├── neutral.mp3    # 平静
    ├── angry.mp3      # 生气（CPU 负载高）
    ├── wink.mp3       # wink 提醒
    ├── failed.mp3     # 失败叹气
    └── wave.mp3       # 挥手
```

3. 设置中切换到你的语音包即可（同事件可放多个文件随机播放，如 `wink-1.mp3`、`wink-2.mp3`）

---

## 📁 项目结构

```
.
├── app/                       # 应用源码
│   ├── qpet_app.py            # 应用入口（设置面板/情绪联动/wink/音乐跳舞/毛玻璃 UI）
│   ├── voice_interact.py      # 语音交互（唤醒引擎/多轮对话/模型 API 客户端）
│   └── hatch_pet/             # 核心渲染引擎模块
│       ├── desktop_renderer.py  # 渲染管线（Canvas 60FPS / 气泡 / 托盘）
│       ├── music_dance.py       # 音乐检测（ctypes WASAPI 回环 + 节拍判定）
│       ├── appearance_wizard.py # 更换形象向导（分步教学/生成进度/自动换装）
│       ├── pixel_ui.py          # 像素风 UI 素材（四色 logo/赛博像素壁纸）
│       ├── glass_ui.py          # 毛玻璃/窗口动画助手
│       └── …                    # 动画引擎 / 随机行为 / 状态监听等
├── assets/                    # 运行时资源
│   ├── spritesheet.png        # 精灵图（3072×2912）
│   ├── spritesheet.webp       # 精灵图（webp 压缩版）
│   ├── pet.json               # 动画配置 + 眼睛跟踪数据
│   ├── vivian.png / vivian.ico  # 图标
│   └── voicepacks/            # 内置语音包
│       └── 甜嗓默认/
├── scripts/                   # 构建脚本
│   ├── build_pet_v7.py        # 精灵图生成脚本（含眼睛逐帧跟踪）
│   ├── build-windows.bat      # Windows 一键打包（exe/绿色版/安装包）
│   ├── build_mac.py           # macOS 一键打包
│   ├── build_source_dmg.py    # Windows 上生成 macOS 源码 DMG
│   ├── qpet_setup.iss         # Inno Setup 安装脚本
│   └── raw_assets/            # 原始素材（AI 生成的角色参考图等）
├── docs/                      # 文档
│   ├── BUILD.md               # 构建总览
│   ├── MAC_BUILD.md           # macOS 构建详细说明
│   ├── 换形象指南.md           # ★ 换 Q 版角色的完整流程
│   └── GITHUB_PUSH.md / GITEE_PUSH.md
├── tools/InnoSetup/           # Inno Setup 编译器（Windows 打包用）
├── release/                   # 打包产物（git-ignored）
│   ├── QPet-Setup.exe
│   ├── Vivian-Pet-Portable-Windows.zip
│   └── Vivian-Pet-Source-V1.0.5.dmg
├── README.md                  # 本文件
├── CHANGELOG.md               # 更新日志
└── INSTALL.md                 # 安装说明
```

---

## 🏗️ 技术架构

### 整体分层

```
┌──────────────────────────────────────────────────────────────────┐
│                        用户交互层                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐    │
│  │   主窗口     │  │   设置面板   │  │   系统托盘 / 菜单    │    │
│  │ (topmost +   │  │  (缩放/音量/ │  │ (退出/唤出/设置)      │    │
│  │  click-thru) │  │   语音包)    │  │                      │    │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘    │
│         └─────────────────┼──────────────────────┘                │
├─────────────────────────┼────────────────────────────────────────┤
│                         │      行为引擎层                          │
│   ┌─────────────┐  ┌────┴──────┐  ┌─────────────────────────┐    │
│   │  情绪联动    │  │  动画调度  │  │  触发器 / 提醒            │    │
│   │  (CPU/Mood) │  │  FSM/队列 │  │  (wink/random/event/beat) │    │
│   └─────────────┘  └────────────┘  └─────────────────────────┘    │
├──────────────────────────────────────────────────────────────────┤
│                          渲染管线层                                │
│   ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐     │
│   │  精灵图帧     │  │  眼睛跟踪    │  │  眨眼合成 / 特效     │     │
│   │ (12×16 帧)   │─▶│ (模板匹配)   │─▶│ (抗锯齿/眼睑/云)      │     │
│   └──────────────┘  └──────────────┘  └────────────────────┘     │
│                          │ tkinter Canvas 60 FPS                  │
├──────────────────────────────────────────────────────────────────┤
│                        平台抽象层 (cross-platform)                 │
│   ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐     │
│   │  VoicePlayer │  │  autorun_*   │  │  resource_dir/      │     │
│   │ MCI/afplay/  │  │ 注册表/plist │  │  settings_path()    │     │
│   │ mpg123       │  │              │  │                      │     │
│   └──────────────┘  └──────────────┘  └────────────────────┘     │
├──────────────────────────────────────────────────────────────────┤
│                          资产 & 数据层                             │
│   assets/                                                      │
│   ├─ spritesheet.png  (3072×2912  192 帧)                       │
│   ├─ pet.json   (动画表 + eyeTracks + spriteVersionNumber)      │
│   ├─ vivian.ico/PNG (图标 / 托盘图)                              │
│   └─ voicepacks/    (按事件 mp3/wav，7 事件 6 种情绪)             │
└──────────────────────────────────────────────────────────────────┘
```

### 各层职责

| 层 | 模块 | 职责 |
|----|------|------|
| 用户交互 | `app/qpet_app.py` + `app/hatch_pet/desktop_renderer.py` | 渲染、点击、拖拽、菜单事件、设置面板 |
| 行为引擎 | `qpet_app.py` 内的 CPU 情绪 / FSM / 随机触发器 | 决定何时切哪个动画、播哪个语音、跳哪支舞 |
| 渲染管线 | `qpet_app.py` 内的 `_apply_blink / _make_gaze_frame / _dance_transform` | 帧合成、抗锯齿、眼睑贴合、舞蹈帧变换、去紫边 |
| 平台抽象 | `qpet_app.py` 顶部 `IS_WINDOWS/IS_MACOS` + `VoicePlayer` / `autorun_*` | 把 OS 差异收敛在一处，Mac 用户无需懂注册表 |
| 资产层 | `assets/` + `scripts/build_pet_v7.py` | 离线生成的精灵图 + 配置 JSON + 资源包 |

### 关键技术点

**1. 精灵图 + 眼睛逐帧跟踪**
- 单张 3072×2912 PNG 容纳 12 动画 × 16 帧 = 192 帧（192×208 / 帧），编译时一次加载 O(1) 帧访问
- `scripts/build_pet_v7.py` 对每个动画帧做**模板匹配**（左右眼锚点 (77,81) / (114,80)）→ 写入 `pet.json.animations[].eyeTracks[frame] = {left:{x,y}, right:{x,y}}`
- 运行时按帧查表 → 眨眼眼睑、视线跟随的虹膜位移都跟着真实眼位走，不会因呼吸位移 dx/dy 错位

**2. 眼睛分层超采样渲染**
- 渲染眼位用 PIL 4× 超采样（皮肤底 → 暖白眼白 (253,246,239) → 上睫毛棕弧线 → 棕虹膜三层色 (137,98,80) / (104,69,54) / (54,34,27) + 左上白高光），LANCZOS 缩回实现抗锯齿
- 虹膜位移钳制：`max_dx = R - 4.6 - 0.6`（不超出眼白边界）
- 睫毛线弧度 `arc(192°~348°, eyeR*1.04, eyeR*0.55)`，闭合过半时按 amt 线性显隐

**3. 举臂挥手的肩关节衔接**
- 离线切下右臂（肤色分割 + 连通域 + 空洞就近填补），得到 arm-sprite + 肩关节 (pvx,pvy)
- 运行时按 0→132° 缓出举起 → ±15° 挥动两拍 → 缓入收回
- 在 arm-sprite 上画「臂根圆盖」（6.5×5.0 软边椭圆），随旋转一起摆；body 层同时叠「躯干肩头盖」（8.0×7.0 软边椭圆）遮住切边楔形缺口 → 视觉上「手臂从肩后伸出」无硬边

**4. 眨眼过冲与眼睑交集掩码**
- 非对称 smoothstep：闭眼 40% 时长 + 睁眼 60% 时长，整体 0.38s
- 眼睑绘制用「交集」掩码：先画眼形椭圆（fill 255）→ rectangle 擦除 lid_y 以下 → 补回下凸弧形椭圆，再 GaussianBlur(1.5) 羽化；避免并集 bug（眼睑盖满整只眼）
- 睫毛线随 amt 渐显，闭合 ≥0.45 时深棕弧线浮出

**5. CPU 情绪联动 + 行为模式引擎**
- CPU 采样零第三方依赖：Windows `GetSystemTimes`（ctypes）/ macOS `sysctl kern.cp_time` 差分（psutil 可选回退），每 5s 采样 → <35% happy、35~70% neutral、>70% angry
- 行为模式（调皮 / 悠闲 / 好奇 / 活跃 / 关闭）决定随机触发的频率、触发动画池、挥手机率
- wink 提醒：`_wink_check` 跟踪 `last_click_ts`，超过 `reminder_s`（可设置 5~600s）触发头部放大 → wink 动画 → 回调；同文件 1.5s 防抖

**6. 语音包多后端**
- 播放抽象在 `VoicePlayer`：Windows MCI (`mciSendStringW`) / macOS `afplay` / Linux `mpg123`，统一 `play(path, volume)` / `stop()` 接口
- 文件搜索 = 内置 `assets/voicepacks/` + 用户目录（`%APPDATA%/QPet/voicepacks` 或 `~/Library/Application Support/QPet/voicepacks`）
- 事件：`greet/happy/neutral/angry/wink/failed/wave`，同事件多文件随机抽

**7. 全帧去紫边**
- 所有显示帧（精灵图动画帧、gaze 帧、眨眼帧、叹气帧）统一过 `_frame_to_tk(img)`，alpha < 118 → 全透、118~170 → 软边、>170 → 实色；避免 RGBA 半透与品红画布混色形成紫边

**8. 跨平台构建链**
- 构建脚本统一读 `scripts/raw_assets/` + 角色参考图 → `build_pet_v7.py` 生成 `assets/spritesheet.png` + `assets/pet.json`（含 `eyeTracks`）
- Windows：`scripts/build-windows.bat` 一键完成 PyInstaller onedir 打包 → 资源拷贝 → 绿色版 zip → Inno Setup `qpet_setup.iss` 编译 `release/QPet-Setup.exe`
- macOS：`scripts/build_mac.py` → PyInstaller `--target-arch=universal2` → Apple 拖拽美化 dmg
- 跨平台分发：Windows 上 `python scripts/build_source_dmg.py` 生成 `Vivian-Pet-Source-V1.0.5.dmg`（ISO 9660 + Joliet + Rock Ridge + UDF），Mac 端 `hdiutil mount` 挂载后按卷内 MAC-README 三步出包

**9. 音乐跳舞：WASAPI 回环 + 节拍编排 + 程序化舞蹈合成**
- 采集：ctypes 直连 WASAPI 回环（`IMMDeviceEnumerator` → `IAudioClient` 带 `AUDCLNT_STREAMFLAGS_LOOPBACK` → `IAudioCaptureClient` 轮询），系统内置 COM 接口、零第三方依赖——sounddevice 已发布版本（≤0.5.6）的 `WasapiSettings` 均不支持 `loopback` 参数，故不依赖它
- 检测：8s 窗口最小值作自适应能底（真静音远低于音乐谷值，且不会被音乐自身抬升），快能量持续超阈值 1s 判定「在放音乐」、安静 2.5s 判定结束；瞬时能量/快能量 >1.3 且高于能底 2.5 倍判为节拍（最小间隔 0.32s）
- 编排：动作池 6 组（摇摆/弹跳/扭动/旋转/跳跃/挥手），起舞与每次换步都随机抽取、每 4~8 拍一换；动画循环播放、不逐拍重启动画保证流畅；跳舞期间鼠标悬停暂停 / 移开继续（200ms 防抖），并与情绪联动、wink、随机行为互斥
- 合成：启动时用 PIL 从现有素材变换出 4 组 24 帧舞蹈动画（旋转/缩放/位移 + squash & stretch，BICUBIC/LANCZOS 重采样），注册进动画表与左键菜单，失败自动回退到原生动作

**10. 设置面板像素 UI（黑绿黄蓝 · 赛博朋克 × 可爱）+ 打包健壮性**
- 程序化像素素材（`hatch_pet/pixel_ui.py`）：手绘像素矩阵 logo（Vivian 像素脸、调节滑杆、爱心、音符、麦克风、星星，NEAREST 放大保持硬边）+ 赛博像素壁纸（暗色渐变、网格点、星星闪光、霓虹天际线、像素月亮爱心）
- 像素卡片：2px 霓虹边框（绿/黄/蓝按分区）+ 深色卡片 + 终端风输入框（暗底荧光绿文字）
- 设置窗口可自由调整大小：卡片与按钮按窗口宽度自适应重排、壁纸按固定种子随窗口重新生成（硬边不糊）、自动记住上次尺寸；窗口淡入+上滑入场、淡出关闭
- Tk 图像防 GC：canvas/label 的 PhotoImage 引用挂实例属性，并在窗口映射后再创建（withdraw 状态下创建会得到空白图像）
- 打包版无控制台（`console=False`）时 `sys.stdout/stderr` 为 `None`，任何日志 formatter 调 `isatty()` 都会静默崩溃——启动入口对冻结模式做了防御，避免「双击没反应」类问题

---

## 🔄 换形象

**最简单的方式**：右键宠物 → ⚙️ 设置 → 其他 → 🧚 **更换形象向导**。
跟着指导选一张角色图、挑一种 Q 版风格，向导自动生成全套动画
（弹窗进度条展示进度），完成后**自动换装、无需重启**，并可一键恢复默认。

想深度定制（手绘逐帧精灵图、校准眼位、换语音包/图标）？看 [`docs/换形象指南.md`](docs/换形象指南.md)：
- 精灵图规格（192×208 / 12 动画 × 16 帧）
- 眼睛锚点校准方法
- 语音包替换规范
- 应用图标替换
- 重新打包验证清单

---

## 🛠️ 从源码构建

详见 [`docs/BUILD.md`](docs/BUILD.md)。

**Windows**：
```cmd
scripts\build-windows.bat
```

**macOS**：
```bash
cd scripts && python3 build_mac.py
```

---

## 📜 版权与署名

**Designed by Louis_Qi for Vivian**

形象与程序仅供个人使用，请勿用于商业用途。