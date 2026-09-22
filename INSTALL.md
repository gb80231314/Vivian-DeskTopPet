# 安装指南

> **Designed by Louis_Qi for Vivian**

## Windows 安装

### 安装版（推荐）

1. 双击 **`QPet-Setup.exe`**（约 19.7MB）
2. 按提示点击"下一步"
3. 附加任务页可勾选：
   - ☐ 创建桌面快捷方式
   - ☐ 开机自动启动（写注册表，可随时在设置中关闭）
   - ☐ 安装完成立即运行
4. 默认安装到 `%LOCALAPPDATA%\QPet`，无需管理员权限

### 绿色版（免安装）

1. 解压 **`Vivian-Pet-Portable-Windows.zip`**（约 24MB）到任意目录
2. 双击其中的 **`QPet.exe`** 运行
3. 卸载 = 删除该目录

### 图标显示异常？

Windows 图标缓存可能残留旧图标，双击 `qpet-app/refresh_icon_cache.bat` 强制刷新：
（脚本会重启资源管理器，任务栏会闪一下，属正常现象）

## macOS 安装

1. 把项目目录（`qpet-app/` + `my-qpet/`）拷到 Mac
2. 终端执行 `python3 build_mac.py`（依赖见 BUILD.md）
3. 打开产出的 `Vivian-Pet-macOS.dmg`，把 Vivian 拖进 Applications

首次打开提示"无法验证开发者"：
右键 Vivian.app → 打开 → 再点"打开"

## 首次启动

安装完成后 Vivian 会自动出现在桌面（默认位于屏幕右下）。

### 让她开机自动启动（两种方式）

**方式 A：安装时勾选**
在安装程序的附加任务页勾选"开机自动启动"

**方式 B：设置面板开启**
右键宠物 → ⚙️ 设置 → 勾选"开机自动启动" → 保存（即时生效，无需重启）

## 使用速查

| 动作 | 效果 |
|------|------|
| 左键短按 | 弹出动画选择菜单 |
| 左键拖拽 | 移动宠物 |
| 右键 | 扇形菜单（跟随/观察/活动/设置/隐藏/退出） |
| 双击 | 隐藏到托盘 |
| 45 秒不点击 | 自动触发 wink（头部放大眨眼比 V） |
| CPU 负载 > 70% | 自动切换生气状态 |
| CPU 负载 < 35% | 自动切换开心捧花 |

## 卸载

### Windows 安装版
- 开始菜单 → Vivian 桌面宠物 → 卸载
- 或：Windows 设置 → 应用 → 找到 Vivian 桌面宠物 → 卸载

卸载会清理：
- 程序文件（`%LOCALAPPDATA%\QPet`）
- 开始菜单/桌面快捷方式
- 开机自启注册表项

保留（可手动删）：
- 用户设置 `%APPDATA%\QPet\settings.json`
- 运行日志 `%APPDATA%\QPet\qpet.log`

### Windows 绿色版
直接删除解压目录。

### macOS
把 Applications 里的 Vivian 拖到废纸篓。
