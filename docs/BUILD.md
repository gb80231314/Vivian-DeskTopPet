# 构建指南

从源码构建 Vivian 桌面宠物（Windows 安装包 / 绿色版 / macOS 安装包）。

> **Designed by Louis_Qi for Vivian**

## 环境要求

- Python 3.10+（推荐 3.12 或 3.14）
- 依赖：`pyinstaller`、`pillow`
- Windows 打包需：[Inno Setup 6](https://jrsoftware.org/isinfo.php)（本仓库未包含，请安装到 `tools/InnoSetup/` 或修改 `build-windows.bat` 中的 `ISCC` 路径）
- macOS 打包需：在 Mac 上 + `create-dmg`（可选）

```bash
pip install pyinstaller pillow
```

## 项目结构

```
.
├── app/                       # 应用源码
│   ├── qpet_app.py            # 应用入口
│   └── hatch_pet/             # 核心渲染引擎模块
├── assets/                    # 运行时资源
│   ├── spritesheet.png        # 精灵图（3072×2912，14 行 × 16 帧）
│   ├── spritesheet.webp       # 精灵图（webp 压缩版）
│   ├── pet.json               # 动画配置 + 眼睛跟踪数据
│   ├── vivian.png / vivian.ico  # 图标
│   └── voicepacks/            # 内置语音包
│       └── 甜嗓默认/
├── scripts/                   # 构建脚本
│   ├── build_pet_v7.py        # 精灵图生成脚本（含眼睛逐帧跟踪）
│   ├── build-windows.bat      # Windows 一键打包脚本
│   ├── build_mac.py           # macOS 一键打包脚本（必须在 Mac 上跑）
│   ├── qpet_setup.iss         # Inno Setup 安装脚本
│   └── raw_assets/            # 原始素材（AI 生成的角色参考图、媒体源）
├── docs/                      # 文档
│   ├── BUILD.md               # 本文件
│   ├── MAC_BUILD.md           # macOS 构建详细说明
│   ├── 换形象指南.md           # ★ 换 Q 版角色的完整流程
│   └── GITHUB_PUSH.md / GITEE_PUSH.md
├── tools/InnoSetup/           # Inno Setup 编译器
├── release/                   # 打包产物（git-ignored）
│   ├── QPet-Setup.exe
│   ├── Vivian-Pet-Portable-Windows.zip
│   └── Vivian-Pet.dmg
└── README.md / CHANGELOG.md / INSTALL.md
```

## Windows 构建

### 一键打包

```cmd
scripts\build-windows.bat
```

脚本自动完成：

1. 清理 `scripts\dist\build`
2. PyInstaller 打包 exe（python314 优先，回退系统 Python）
3. 复制资源（spritesheet.png/pet.json/icons/voicepacks）到 `scripts\dist\QPet\`
4. 生成绿色版 zip → `release\Vivian-Pet-Portable-Windows.zip`
5. 编译 Inno Setup 安装包 → `release\QPet-Setup.exe`

最终产物：

| 产物           | 路径                                          | 大小   |
|----------------|-----------------------------------------------|--------|
| 绿色版 zip     | `release\Vivian-Pet-Portable-Windows.zip`     | ~36 MB |
| Windows 安装包 | `release\QPet-Setup.exe`                      | ~27 MB |

**Inno Setup 配置：**
- 默认装到 `%LOCALAPPDATA%\QPet`（无需管理员）
- 可选：桌面快捷方式 / 开机自启 / 装完运行
- 自带卸载器
- 升级安装时自动删除旧桌面快捷方式并重建（修复图标缓存）

### 手工打包（分步）

如果需要更细的控制：

```cmd
cd scripts
rmdir /s /q dist build
python -m PyInstaller --noconfirm --clean --windowed --name QPet --icon ..\assets\vivian.ico ..\app\qpet_app.py
copy ..\assets\spritesheet.png ..\assets\pet.json ..\assets\vivian.ico ..\assets\vivian.png dist\QPet\
xcopy /E /I ..\assets\voicepacks dist\QPet\voicepacks\

cd dist
python -c "import shutil; shutil.make_archive('Vivian-Pet-Portable-Windows', 'zip', '.', 'QPet')"
move Vivian-Pet-Portable-Windows.zip ..\..\release\

..\tools\InnoSetup\ISCC.exe ..\scripts\qpet_setup.iss
```

### 重新生成精灵图（可选）

修改 `scripts/raw_assets/` 下的素材后：

```bash
cd scripts
python build_pet_v7.py
```

会重新生成 `assets/spritesheet.png`、`spritesheet.webp`、`pet.json`（含眼睛逐帧跟踪）。

## macOS 构建

> ⚠️ **必须在 macOS 上执行**——PyInstaller 不能交叉编译。详见 `docs/MAC_BUILD.md`。

```bash
brew install python@3.12 create-dmg   # 可选 create-dmg
pip3 install pyinstaller pillow
cd scripts && python3 build_mac.py
```

产出：
- `scripts/dist/Vivian.app`
- `scripts/dist/Vivian-Pet-macOS.dmg`

## 常见问题

### Q：exe 启动后没有窗口？
查看 `%APPDATA%\QPet\qpet.log` 排查。

### Q：重新打包后 exe 还是旧的？
杀软会拦截 dist 目录删除。先 `rmdir /s /q dist build` 再打包；或用 `scripts\build-windows.bat` 自动清理。

### Q：升级安装后桌面快捷方式图标还是旧的？
新版安装包已自动删除并重建快捷方式。仍异常时运行 `scripts\refresh_icon_cache.bat`。

### Q：精灵图结构变了怎么适配？
`pet.json` 的 `sprite` 字段支持自定义 `cols`/`rows`/`cell`，`_load_spritesheet` 会自动读取。

### Q：怎么换形象？
看 [`docs/换形象指南.md`](换形象指南.md)。

---

Designed by Louis_Qi for Vivian.