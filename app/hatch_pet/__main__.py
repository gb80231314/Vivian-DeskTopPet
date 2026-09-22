import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("hatch-pet")

ROOT_DIR = Path(__file__).resolve().parent.parent

def cmd_generate(args):
    from hatch_pet.pet_config import save_pet_config, validate_pet_config
    from hatch_pet.sprite_builder import SpriteSheetBuilder
    from hatch_pet.frame_generator import create_frame_image
    from hatch_pet.config import ANIMATION_STATES, GAZE_DIRECTIONS, COLS

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 50)
    logger.info("阶段 1/5: 生成 pet.json 配置")
    logger.info("=" * 50)

    config = save_pet_config(
        path=str(output_dir / "pet.json"),
        name=args.name,
        description=args.description or f"{args.name} 桌面宠物",
        author=args.author,
        version=args.version,
    )
    errors = validate_pet_config(config)
    if errors:
        for e in errors:
            logger.error(f"  ❌ {e}")
        logger.error("pet.json 配置校验失败！")
        return 1
    logger.info(f"  ✅ pet.json 生成完成: {output_dir / 'pet.json'}")

    logger.info("=" * 50)
    logger.info("阶段 2/5: 构建精灵图 (8列×11行, 1536×2288)")
    logger.info("=" * 50)

    builder = SpriteSheetBuilder()

    if args.frames_dir:
        frames_dir = Path(args.frames_dir)
        if frames_dir.exists():
            for state in ANIMATION_STATES:
                state_dir = frames_dir / state["name"]
                if state_dir.exists():
                    count = builder.set_cells_from_dir(str(state_dir), state["row"])
                    logger.info(f"  加载 '{state['label']}' ({state['name']}): {count} 帧")

    empty_cells = builder.get_empty_cells()
    if empty_cells:
        logger.info(f"  生成 {len(empty_cells)} 个占位帧...")
        for row, col in empty_cells:
            anim_name = "idle"
            for state in ANIMATION_STATES:
                if state["row"] == row:
                    anim_name = state["name"]
                    break
            frame = create_frame_image(anim_type=anim_name, frame_col=col)
            builder.set_cell(row, col, frame)

    spritesheet_path = str(output_dir / "spritesheet.webp")
    builder.build(spritesheet_path)
    logger.info(f"  ✅ 精灵图生成完成: {spritesheet_path}")

    logger.info("=" * 50)
    logger.info("阶段 3/5: 精灵图已生成，可手动校验")
    logger.info("=" * 50)
    logger.info("  手动校验: python validate_atlas.py --image %s --config %s",
                output_dir / "spritesheet.webp", output_dir / "pet.json")

    logger.info("=" * 50)
    logger.info("阶段 4/5: 打包输出")
    logger.info("=" * 50)

    package_name = args.package or f"{args.name}-hatch-pet"
    archive_path = Path(args.output).parent / package_name
    shutil.make_archive(
        str(archive_path),
        "zip",
        root_dir=str(output_dir),
    )
    logger.info(f"  ✅ 打包完成: {archive_path}.zip")

    logger.info("=" * 50)
    logger.info("阶段 5/5: 生成完成！")
    logger.info("=" * 50)
    logger.info(f"  📁 输出目录: {output_dir}")
    logger.info(f"  🖼️  精灵图: {output_dir / 'spritesheet.webp'}")
    logger.info(f"  ⚙️  配置文件: {output_dir / 'pet.json'}")
    logger.info(f"  📦 安装包: {archive_path}.zip")
    logger.info("")
    logger.info("  下一步: python -m hatch_pet desktop --spritesheet output/spritesheet.webp --config output/pet.json [--random playful]")
    logger.info("")

    return 0

def cmd_validate(args):
    import subprocess
    validate_script = ROOT_DIR / "validate_atlas.py"

    cmd = [sys.executable, str(validate_script)]
    if args.image:
        cmd.extend(["--image", args.image])
    if args.config:
        cmd.extend(["--config", args.config])
    if args.strict:
        cmd.append("--strict")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode

def cmd_build(args):
    from hatch_pet.sprite_builder import SpriteSheetBuilder
    from hatch_pet.config import ANIMATION_STATES

    output_dir = Path(args.output or "output")
    output_dir.mkdir(parents=True, exist_ok=True)

    builder = SpriteSheetBuilder()
    frames_dir = Path(args.frames_dir)

    if not frames_dir.exists():
        logger.error(f"帧目录不存在: {frames_dir}")
        return 1

    for state in ANIMATION_STATES:
        state_dir = frames_dir / state["name"]
        if state_dir.exists():
            count = builder.set_cells_from_dir(str(state_dir), state["row"])
            logger.info(f"加载 '{state['label']}' ({state['name']}): {count} 帧")
        else:
            logger.warning(f"缺少动画状态目录: {state_dir}")

    spritesheet_path = str(output_dir / "spritesheet.webp")
    builder.build(spritesheet_path)
    logger.info(f"精灵图构建完成: {spritesheet_path}")

    from hatch_pet.pet_config import save_pet_config
    save_pet_config(str(output_dir / "pet.json"), name=args.name)
    logger.info(f"配置文件生成: {output_dir / 'pet.json'}")

    return 0

def cmd_qpet(args):
    from hatch_pet.q_pet_converter import generate_q_pet_from_image, CHIBI_STYLES

    image_path = args.image
    if not Path(image_path).exists():
        logger.error(f"参考图不存在: {image_path}")
        return 1

    style = args.style
    if style not in CHIBI_STYLES:
        logger.warning(f"未知风格 '{style}'，使用 chibi_classic")
        logger.info(f"可用风格: {', '.join(CHIBI_STYLES.keys())}")
        style = "chibi_classic"

    logger.info(f"🎨 Q版风格: {CHIBI_STYLES[style]['name']}")
    logger.info(f"📷 参考图: {image_path}")
    logger.info(f"🐱 宠物名: {args.name}")

    output_dir = generate_q_pet_from_image(
        image_path=image_path,
        style=style,
        output_dir=args.output,
        pet_name=args.name,
        use_ai=args.ai,
        api_key=args.api_key,
    )

    logger.info("")
    logger.info("=" * 50)
    logger.info("Q版宠物生成完成！")
    logger.info("=" * 50)
    logger.info(f"  📁 输出目录: {output_dir}")
    logger.info(f"  🖼️  精灵图: {output_dir / 'spritesheet.webp'}")
    logger.info(f"  ⚙️  配置文件: {output_dir / 'pet.json'}")
    logger.info("")
    logger.info(f"  下一步: python -m hatch_pet desktop --spritesheet {output_dir}/spritesheet.webp --config {output_dir}/pet.json")
    logger.info("")

    return 0

def cmd_desktop(args):
    from hatch_pet.desktop_renderer import run_desktop

    logger.info("🐱 正在启动桌面宠物...")
    if args.gif:
        logger.info(f"  GIF: {args.gif}")
    else:
        logger.info(f"  精灵图: {args.spritesheet}")
        logger.info(f"  配置: {args.config}")
    logger.info(f"  缩放: {args.scale}x")
    if args.watch:
        logger.info(f"  状态监听: {args.status_path}")
        logger.info(f"  事件流:   {args.events_path}")
        logger.info(f"  自动托管: 已开启（MCP 活动自动追踪）")
    logger.info("")
    logger.info("  操作提示:")
    logger.info("    右键 → 功能菜单（跟随/活动/隐藏等）")
    logger.info("    拖拽 → 移动宠物")
    logger.info("    双击 → 隐藏到托盘")

    run_desktop(
        spritesheet=args.spritesheet,
        config=args.config,
        gif_path=args.gif,
        random_preset=args.random,
        scale=args.scale,
        enable_tray=not args.no_tray,
        enable_watcher=args.watch,
        status_path=args.status_path,
        events_path=args.events_path,
    )
    return 0

def main():
    parser = argparse.ArgumentParser(
        description="Hatch Pet - Q版卡通桌面宠物生成器 + 桌面渲染 (v2.5)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 生成精灵图
  python -m hatch_pet generate --name "MyCat" --output ./my-pet/

  # 从图片生成Q版宠物
  python -m hatch_pet qpet --image photo.jpg --name "MyPet" --style chibi_cute

  # 在桌面显示（默认行为模式）
  python -m hatch_pet desktop --spritesheet output/spritesheet.webp --config output/pet.json

  # 在桌面显示（调皮随机模式）
  python -m hatch_pet desktop --spritesheet output/spritesheet.webp --config output/pet.json --random playful

  # 在桌面显示（AI agent 状态监听）
  python -m hatch_pet desktop --spritesheet output/spritesheet.webp --config output/pet.json --watch

  # 在桌面显示（AI agent 状态监听模式）
  python -m hatch_pet desktop --spritesheet output/spritesheet.webp --config output/pet.json --watch

  # 校验精灵图
  python -m hatch_pet validate --image output/spritesheet.webp --config output/pet.json
        """,
    )
    parser.add_argument("--version", action="version", version="hatch-pet 1.0.2")

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    gen = subparsers.add_parser("generate", help="一键生成桌面宠物精灵图")
    gen.add_argument("--ref", help="参考图路径")
    gen.add_argument("--name", default="DesktopBuddy", help="宠物名称")
    gen.add_argument("--description", help="宠物描述")
    gen.add_argument("--author", default="", help="作者")
    gen.add_argument("--version", default="1.0.2", help="版本号")
    gen.add_argument("--frames-dir", help="帧图片目录（可选）")
    gen.add_argument("--output", "-o", default="output", help="输出目录")
    gen.add_argument("--package", help="打包名称（不含扩展名）")
    gen.set_defaults(func=cmd_generate)

    qpet = subparsers.add_parser("qpet", help="从用户图片生成Q版桌面宠物")
    qpet.add_argument("--image", "-i", required=True, help="参考图路径（必填）")
    qpet.add_argument("--name", default="MyPet", help="宠物名称")
    qpet.add_argument("--style", default="chibi_classic",
                      choices=["chibi_classic", "chibi_cute", "chibi_minimal",
                               "chibi_pixel", "chibi_watercolor"],
                      help="Q版风格 (默认: chibi_classic)")
    qpet.add_argument("--output", "-o", default="output", help="输出目录")
    qpet.add_argument("--ai", action="store_true", help="使用AI增强（需API密钥）")
    qpet.add_argument("--api-key", help="AI API密钥")
    qpet.set_defaults(func=cmd_qpet)

    dsk = subparsers.add_parser("desktop", help="在桌面显示宠物（tkinter 窗口）")
    dsk.add_argument("--spritesheet", default="output/spritesheet.webp", help="精灵图路径")
    dsk.add_argument("--config", default="output/pet.json", help="配置文件路径")
    dsk.add_argument("--gif", default=None, help="直接加载 GIF 动画（可替代 spritesheet/config）")
    dsk.add_argument("--random", default="playful",
                     choices=["playful", "relaxed", "curious", "active", "none"],
                     help="随机行为预设 (默认: playful, none=关闭随机)")
    dsk.add_argument("--scale", type=float, default=1.0, help="缩放比例 (默认: 1.0)")
    dsk.add_argument("--no-tray", action="store_true", help="禁用系统托盘")
    dsk.add_argument("--watch", action="store_true", help="启用 AI agent 状态监听（文件桥接模式）")
    dsk.add_argument("--status-path", default="~/.hatch-pet/status.json",
                      help="状态文件路径，多个源用逗号分隔（默认: ~/.hatch-pet/status.json）。"
                           "多源时桌宠按 STATE_PRIORITY 取最高优先级状态作为主形象。"
                           "例: ~/.hatch-pet/status-reasonix.json,~/.hatch-pet/status-workbuddy.json")
    dsk.add_argument("--events-path", default="~/.hatch-pet/events.jsonl",
                      help="事件流文件路径（默认: ~/.hatch-pet/events.jsonl）。"
                           "事件驱动触发 oneshot（greet/happy/error）和 loafing 合成。")
    dsk.set_defaults(func=cmd_desktop)

    from .status_watcher import add_status_subparser, add_event_subparser
    add_status_subparser(subparsers)
    add_event_subparser(subparsers)

    val = subparsers.add_parser("validate", help="校验精灵图")
    val.add_argument("--image", default="output/spritesheet.webp", help="精灵图路径")
    val.add_argument("--config", default="output/pet.json", help="配置文件路径")
    val.add_argument("--strict", action="store_true", help="严格模式")
    val.set_defaults(func=cmd_validate)

    bld = subparsers.add_parser("build", help="从帧目录构建精灵图")
    bld.add_argument("--frames-dir", required=True, help="帧图片目录")
    bld.add_argument("--output", "-o", default="output", help="输出目录")
    bld.add_argument("--name", default="DesktopBuddy", help="宠物名称")
    bld.set_defaults(func=cmd_build)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)

if __name__ == "__main__":
    sys.exit(main())
