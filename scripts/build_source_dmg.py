# -*- coding: utf-8 -*-
"""build_source_dmg.py — 在 Windows 上生成 macOS 源码 DMG

PyInstaller 不能交叉编译：真正的 Vivian.app 只能在 Mac 上构建
（scripts/build_mac.py）。本脚本用 pycdlib 把完整源码 + 构建脚本 +
构建指南打成一个可在 macOS 挂载的 DMG（ISO 9660 + Joliet + Rock
Ridge，尽量加 UDF），Mac 端 `hdiutil mount` 后按 MAC-README.txt
三步出包。

用法（项目根目录执行）：
    python scripts/build_source_dmg.py
产物：release/Vivian-Pet-Source-V<版本>.dmg
"""
import io
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / "release"

INCLUDE_ROOT = ["README.md", "CHANGELOG.md", "INSTALL.md", ".gitignore"]
INCLUDE_DIRS = {
    "app": {".py"},
    "assets": {".png", ".webp", ".json", ".ico", ".mp3", ".wav", ".txt"},
    "scripts": {".py", ".bat", ".spec", ".iss"},
    "docs": {".md"},
}
EXCLUDE_PARTS = {"__pycache__", "dist", "build", "mac_resources",
                 "raw_assets", ".venv", "node_modules"}

MAC_README = """Vivian 桌面宠物 v{ver} — macOS 源码包
Designed by Louis_Qi for Vivian

本 DMG 包含完整源码。PyInstaller 不能交叉编译，请在 Mac 上按下面
三步构建出 Vivian.app 与安装镜像：

  1. 把整个卷拷贝到 Mac 任意目录（如 ~/Vivian）
  2. 安装依赖（需 Python 3.10+，带 tkinter）：
       pip3 install pyinstaller pillow pystray sounddevice
  3. 构建：
       cd scripts && python3 build_mac.py

  产物：scripts/dist/Vivian.app（可拖入"应用程序"）
        scripts/dist/Vivian-Pet-macOS.dmg（安装镜像）

更多说明见卷内 docs/MAC_BUILD.md；换角色见 docs/换形象指南.md。
开源地址：https://github.com/gb80231314/Vivian-DeskTopPet
"""


def version() -> str:
    text = (ROOT / "app" / "hatch_pet" / "__init__.py").read_text("utf-8")
    m = re.search(r'__version__\s*=\s*"([\d.]+)"', text)
    return m.group(1) if m else "1.0.5"


def collect_files():
    """返回 [(绝对路径 or None, dmg 内相对 POSIX 路径), ...]；None=内存内容"""
    items = []
    for name in INCLUDE_ROOT:
        p = ROOT / name
        if p.is_file():
            items.append((p, name))
    for d, exts in INCLUDE_DIRS.items():
        base = ROOT / d
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if x not in EXCLUDE_PARTS]
            for fn in filenames:
                if Path(fn).suffix.lower() not in exts:
                    continue
                full = Path(dirpath) / fn
                items.append((full, full.relative_to(ROOT).as_posix()))
    items.append((None, "MAC-README.txt"))
    return items


def joliet_safe(name: str) -> str:
    """Joliet 名字上限 64 个 UCS-2 码元（中文按 2 字节计）；超限时截断
    加哈希后缀。Rock Ridge 命名空间仍保留真实文件名，macOS 显示 RR 名。"""
    import hashlib
    if len(name.encode("utf-16-be")) <= 63 * 2:
        return name
    stem, dot, ext = name.rpartition(".")
    h = hashlib.md5(name.encode("utf-8")).hexdigest()[:6]
    short = (stem[:10] + "-" + h) if stem else name[:12]
    return short + ((dot + ext) if dot and 0 < len(ext) < 12 else "")


def jp_safe(rel: str) -> str:
    return "/" + "/".join(joliet_safe(x) for x in rel.split("/"))


def main():
    try:
        import pycdlib
    except ImportError:
        print("缺少依赖：pip install pycdlib")
        return 1

    ver = version()
    items = collect_files()
    print("收集到 %d 个文件" % len(items))

    iso = pycdlib.PyCdlib()
    use_udf = True
    try:
        iso.new(interchange_level=3, vol_ident="VIVIAN_PET",
                joliet=3, rock_ridge="1.09", udf="2.60")
    except Exception as e:
        print("UDF 不可用(%s)，退回 Joliet+RockRidge" % e)
        use_udf = False
        iso.new(interchange_level=3, vol_ident="VIVIAN_PET",
                joliet=3, rock_ridge="1.09")

    # 目录逐级建立：ISO9660 命名空间用 ASCII 序号名（父路径必须是
    # 已存在的 ISO 目录），真实名字写进 Joliet / RockRidge / UDF
    dirs = set()
    for _, rel in items:
        parts = rel.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))

    seq = [0]

    def _seq(kind):
        # ISO9660：目录标识不带版本号，文件名带 ";1"
        seq[0] += 1
        return "%06d%s" % (seq[0], ";1" if kind == "F" else "")

    dir_iso = {"": ""}
    for d in sorted(dirs, key=len):
        parent = d.rsplit("/", 1)[0] if "/" in d else ""
        parent_iso = dir_iso.get(parent, "")
        iso_path = "%s/%s" % (parent_iso, _seq("D"))
        jp = jp_safe(d)
        iso.add_directory(iso_path=iso_path,
                          rr_name=Path(d).name,
                          joliet_path=jp,
                          udf_path=jp if use_udf else None)
        dir_iso[d] = iso_path

    for src, rel in items:
        reldir = rel.rsplit("/", 1)[0] if "/" in rel else ""
        jp = jp_safe(rel)
        if src is None:  # MAC-README.txt
            iso.add_fp(io.BytesIO(MAC_README.format(ver=ver).encode("utf-8")),
                       len(MAC_README.format(ver=ver).encode("utf-8")),
                       iso_path="%s/%s" % (dir_iso.get(reldir, ""), _seq("F")),
                       rr_name=Path(rel).name, joliet_path=jp,
                       udf_path=jp if use_udf else None)
            continue
        iso.add_file(str(src),
                     iso_path="%s/%s" % (dir_iso.get(reldir, ""), _seq("F")),
                     rr_name=Path(rel).name, joliet_path=jp,
                     udf_path=jp if use_udf else None)

    RELEASE.mkdir(exist_ok=True)
    out_path = RELEASE / ("Vivian-Pet-Source-V%s.dmg" % ver)
    if out_path.exists():
        out_path.unlink()
    iso.write(str(out_path))

    # —— 校验：重新打开，走 Joliet 命名空间数文件并抽查中文文件名 ——
    try:
        chk = pycdlib.PyCdlib()
        chk.open(str(out_path))
        names = []

        def _walk(path):
            try:
                entries = chk.listdir(joliet_path=path)
            except Exception:
                return
            for e in entries:
                if isinstance(e, tuple):
                    name, is_dir = e[0], bool(e[-1])
                else:
                    name, is_dir = e, False
                if not name or name in (".", ".."):
                    continue
                sub = path.rstrip("/") + "/" + name
                if is_dir:
                    _walk(sub)
                else:
                    names.append(sub)

        _walk("/")
        print("校验: Joliet 命名空间 %d 个文件" % len(names))
        sample = [n for n in names if "换形象" in n or "甜嗓" in n]
        print("中文路径抽查:", sample[:3] if sample else "（无）")
    except Exception as e:
        print("校验失败（文件仍已生成）:", e)

    print("DMG 生成: %s (%.1f MB)" % (out_path, out_path.stat().st_size / 1048576))
    return 0


if __name__ == "__main__":
    sys.exit(main())
