import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
RES_DIR = PROJECT_ROOT / "assets"
APP_NAME = "Vivian"
BUNDLE_ID = "com.louisqi.vivian.pet"

def run(cmd, cwd=None):
    print("+", " ".join(map(str, cmd)))
    subprocess.run([str(c) for c in cmd], cwd=cwd or ROOT, check=True)

def main():

    try:
        import PyInstaller
        import PIL
    except ImportError:
        print("缺少依赖，请先执行：")
        print("  pip3 install pyinstaller pillow")
        sys.exit(1)

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
    macos_dir = app / "Contents" / "MacOS"
    for f in ("spritesheet.png", "pet.json", "vivian.png"):
        src = app / "Contents" / "Resources" / f
        if src.exists():
            shutil.copy2(src, macos_dir / f)
    print(".app 打包完成:", app)

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
