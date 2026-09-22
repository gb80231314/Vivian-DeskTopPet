# macOS 构建指南

> 把 Vivian 桌面宠物打包成 macOS 原生应用（.app）和安装包（.dmg）。

---

## ⚠️ 重要前提

**必须在 macOS 上执行**——PyInstaller 是平台绑定的，Windows 上无法交叉编译出 Mac 能跑的应用。

本项目代码已做平台适配（见 `app/qpet_app.py` 的 `IS_WINDOWS`/`IS_MACOS` 分支），所以同一份代码
直接 `python3 build_mac.py` 就能在 macOS 上产出可运行的 .app。

---

## 1. 环境准备

### 1.1 系统要求

- macOS 12 (Monterey) 或更新
- Xcode Command Line Tools：`xcode-select --install`
- Python 3.10+（推荐 Homebrew 安装：`brew install python@3.12`）
- tkinter（macOS 自带 Python 可能不带 tkinter，需要从 python.org 下载或用 Homebrew）：
  ```bash
  brew install python-tk@3.12
  ```

### 1.2 依赖

```bash
pip3 install pyinstaller pillow
```

> pystray / rumps 等托盘库**不需要**。本应用在 macOS 上不使用原生托盘（窗口本身就是无边框顶层
> 窗口，符合 macOS 桌面宠物体验）。

---

## 2. 准备资源

确保以下文件齐全（都在仓库内）：

```
assets/
├── spritesheet.png
├── spritesheet.webp
├── pet.json
├── vivian.png         # 会被自动转 .icns
└── voicepacks/
    └── 甜嗓默认/
        ├── greet.mp3
        ├── happy.mp3
        ...
```

如资源缺失，脚本会报错并退出。

---

## 3. 一键打包

```bash
cd scripts
python3 build_mac.py
```

脚本会自动完成：

1. **资源 staging**：把 `assets/` 下的 spritesheet.png/pet.json/vivian.png 拷贝到 `scripts/mac_resources/`
2. **PyInstaller**：调用 `pyinstaller --windowed` 产出 `scripts/dist/Vivian.app`
3. **资源位置修正**：把资源从 `Contents/Resources/` 复制到 `Contents/MacOS/`（与
   `app/qpet_app.py.resource_dir()` 的查找路径对齐）
4. **dmg 生成**：
   - 若系统装了 `create-dmg`（`brew install create-dmg`）→ 生成带"拖进 Applications"界面的美观 dmg
   - 否则用 `hdiutil` 生成基础 dmg

最终产物：

```
scripts/dist/Vivian.app                       # 可双击运行的应用
scripts/dist/Vivian-Pet-macOS.dmg             # 分发安装包
```

---

## 4. 测试 .app

```bash
open scripts/dist/Vivian.app
```

首次启动可能被 Gatekeeper 拦截：

```
"Vivian.app" cannot be opened because the developer cannot be verified.
```

解决：右键 → 打开 → 打开（仅首次需要）。或到「系统设置 → 隐私与安全性 → 仍要打开」。

---

## 5. 手动调整（可选）

### 5.1 自定义图标

把 PNG 替换到 `assets/vivian.png`（建议 1024×1024 方形），重新跑 `python3 build_mac.py`。PyInstaller
自动转 icns。

### 5.2 替换 Application Name / Bundle ID

修改 `scripts/build_mac.py`：

```python
APP_NAME = "Vivian"               # 显示名
BUNDLE_ID = "com.louisqi.vivian.pet"  # 全局唯一标识
```

### 5.3 改安装位置

Mac 应用安装不需要写 LaunchAgent 路径，应用拖到 `/Applications/` 就完事。LaunchAgent 是给
「开机自启」功能用的，由应用本身在 `~/Library/LaunchAgents/com.louisqi.vivian.pet.plist` 写。

---

## 6. 代码签名 & 公证（可选，发布到 Mac App Store 必须）

开发者账号 + 证书：

```bash
# 签名
codesign --deep --force --options runtime \
         --sign "Developer ID Application: Your Name (TEAMID)" \
         scripts/dist/Vivian.app

# 公证（需要 notarytool，Xcode 13+ 自带）
xcrun notarytool submit scripts/dist/Vivian-Pet-macOS.dmg \
         --apple-id "you@example.com" \
         --team-id "TEAMID" \
         --password "app-specific-password" \
         --wait

# 钉扎公证票据到 dmg
xcrun stapler staple scripts/dist/Vivian-Pet-macOS.dmg
```

> 没做签名的 dmg 在 macOS 10.15+ 默认会被 Gatekeeper 拦截。

---

## 7. 跨平台 dmg 分发（开发者给 Mac 用户）

**如果你（开发者）在 Windows 上工作**：仍然可以生成一个**分发用 dmg 容器**给 Mac 用户下载——
它里面不是 .app，而是 README + 构建脚本 + 源码 + Windows 安装包（作为参考样本）。Mac 用户
下载后按本指南在 Mac 上一键构建。

详见仓库根目录的 `release/Vivian-Pet.dmg`（如已生成）。

---

## 8. 常见问题

### Q: PyInstaller 打包后 .app 双击闪退
A: 打开 `Console.app` 看崩溃日志。常见原因：
- tkinter 没装：`brew install python-tk@3.12` 后用 Homebrew 的 Python 而不是系统 Python
- 路径问题：`app/qpet_app.py` 的 `resource_dir()` 在打包后找 `Contents/Resources/`；build_mac.py
  会自动把资源拷到 `Contents/MacOS/`（备用位置）

### Q: 语音不响
A: `afplay` 命令行测试：
```bash
afplay assets/voicepacks/甜嗓默认/greet.mp3
```
若命令行 OK 但应用内不响，把音量调到 0 重启应用测试。

### Q: 开机自启不生效
A: 检查 LaunchAgent：
```bash
ls -la ~/Library/LaunchAgents/com.louisqi.vivian.pet.plist
launchctl list | grep vivian
launchctl load -w ~/Library/LaunchAgents/com.louisqi.vivian.pet.plist
```

### Q: 资源找不到
A: 看 `~/Library/Application Support/QPet/` 或应用内 console 日志（macOS 控制台应用）。

---

## 9. 与 Windows 版本的差异

| 功能           | Windows                  | macOS                                  |
|----------------|--------------------------|----------------------------------------|
| 打包格式       | exe + Inno Setup installer | .app + .dmg                            |
| 语音播放       | winmm MCI                | afplay (subprocess)                    |
| 开机自启       | 注册表 HKCU\\...\\Run    | LaunchAgent plist                      |
| 资源目录       | exe 同目录                | .app/Contents/MacOS/ 或 Resources/     |
| 用户配置目录   | %APPDATA%/QPet/          | ~/Library/Application Support/QPet/   |
| 日志目录       | 同上                     | 同上                                   |
| 精灵图规格     | 192×208 / 16 帧×12 动画  | 同上                                   |

行为、动画、设置面板**完全一致**。

---

Designed by Louis_Qi for Vivian.