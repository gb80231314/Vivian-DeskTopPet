"""Vivian-Pet macOS 打包脚本：Vivian.app + DMG。

流程：准备资源 → PyInstaller → 回写 Info.plist（版本号/最低系统版本）
→ ad-hoc 签名 → 打 DMG。

V1.0.8 修复（详见 docs/Vivian-Pet-macOS-V1.0.7-测试报告.md）：
- BUG-02 签名失效：此前 PyInstaller 完成后往 Contents/MacOS 又复制了
  一份资源（冻结态 resource_dir() 实际指向 Contents/Resources，
  该复制既冗余又破坏签名），已删除；签名步骤收进本脚本并自校验。
- BUG-03 版本号 0.0.0：打包后用 PlistBuddy 回写 CFBundleShortVersionString /
  CFBundleVersion（读自 app/qpet_app.py 的 APP_VERSION，不硬编码）。
- BUG-04：补 LSMinimumSystemVersion=11.0（python.org universal2
  Python 3.12 的系统下限）。
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
RES_DIR = PROJECT_ROOT / "assets"
APP_NAME = "Vivian"
BUNDLE_ID = "com.louisqi.vivian.pet"
LS_MIN_SYS = "11.0"
PLIST_BUDDY = "/usr/libexec/PlistBuddy"


def app_version() -> str:
    """从 app/qpet_app.py 读取 APP_VERSION（避免多处硬编码不同步）。"""
    src = (PROJECT_ROOT / "app" / "qpet_app.py").read_text(encoding="utf-8")
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', src)
    if not m:
        print("无法从 app/qpet_app.py 解析 APP_VERSION")
        sys.exit(1)
    return m.group(1)


def run(cmd, cwd=None):
    print("+", " ".join(map(str, cmd)))
    subprocess.run([str(c) for c in cmd], cwd=cwd or ROOT, check=True)


def plist_set(plist: Path, key: str, value: str):
    """PlistBuddy 写值：键存在则 Set，不存在则 Add。"""
    probe = subprocess.run([PLIST_BUDDY, "-c", "Print :" + key, str(plist)],
                           capture_output=True)
    op = "Set" if probe.returncode == 0 else "Add"
    run([PLIST_BUDDY, "-c", f"{op} :{key} string {value}", str(plist)])


def main():
    try:
        import PyInstaller  # noqa
        import PIL  # noqa
    except ImportError:
        print("缺少依赖，请先执行：")
        print("  pip3 install pyinstaller pillow")
        sys.exit(1)

    version = app_version()
    print(f"打包版本: {version}")

    staging = ROOT / "mac_resources"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    for f in ("spritesheet.png", "pet.json", "vivian.png"):
        src = RES_DIR / f
        if not src.exists():
            print(f"缺少资源文件: {src}")
            sys.exit(1)
        shutil.copy2(src, staging / f)

    if (RES_DIR / "voicepacks").exists():
        shutil.copytree(RES_DIR / "voicepacks", staging / "voicepacks")
    print("资源已准备:", staging)

    entry = PROJECT_ROOT / "app" / "qpet_app.py"
    if not entry.exists():
        print(f"缺少入口文件: {entry}")
        sys.exit(1)
    run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--windowed",
        "--name", APP_NAME,
        "--osx-bundle-identifier", BUNDLE_ID,
        "--paths", str(PROJECT_ROOT / "app"),
        "--add-data", f"{staging / 'spritesheet.png'}:.",
        "--add-data", f"{staging / 'pet.json'}:.",
        "--add-data", f"{staging / 'vivian.png'}:.",
        "--add-data", f"{staging / 'voicepacks'}:voicepacks",
        "--icon", str(staging / "vivian.png"),
        str(entry),
    ])

    app = ROOT / "dist" / f"{APP_NAME}.app"
    if not app.exists():
        print(f"打包失败，未找到 {app}")
        sys.exit(1)

    # --- Info.plist：版本号 + 最低系统版本 ---
    plist = app / "Contents" / "Info.plist"
    plist_set(plist, "CFBundleShortVersionString", version)
    plist_set(plist, "CFBundleVersion", version)
    plist_set(plist, "LSMinimumSystemVersion", LS_MIN_SYS)

    # --- ad-hoc 签名（在所有文件改动之后，保证签名有效）---
    run(["codesign", "--force", "--deep", "-s", "-", str(app)])
    run(["codesign", "--verify", "--deep", "--strict", str(app)])
    print("签名校验通过")

    dmg_target = ROOT / "dist" / "Vivian-Pet-macOS.dmg"
    if dmg_target.exists():
        dmg_target.unlink()
    have_create_dmg = shutil.which("create-dmg") is not None
    if have_create_dmg:
        run([
            "create-dmg",
            "--volname", "Vivian Desktop Pet",
            "--window-size", "620", "400",
            "--icon-size", "128",
            "--icon", f"{APP_NAME}.app", "155", "185",
            "--app-drop-link", "465", "185",
            str(dmg_target), str(app),
        ])
    else:
        run(["hdiutil", "create", "-volname", "Vivian Desktop Pet",
             "-srcfolder", str(app), "-ov", "-format", "UDZO",
             str(dmg_target)])
        print("提示：安装 create-dmg（brew install create-dmg）可生成更美观的安装界面")

    print()
    print("=" * 50)
    print("打包完成:")
    print(f"  .app  → {app}")
    print(f"  .dmg  → {dmg_target}")
    print(f"署名: Designed by Louis_Qi for Vivian")
    print("=" * 50)


if __name__ == "__main__":
    main()
