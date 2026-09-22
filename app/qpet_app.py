import ctypes
import json
import logging
import math
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from hatch_pet import desktop_renderer as dr
from hatch_pet.desktop_renderer import DesktopPet

APP_NAME = "Vivian 桌面宠物"
APP_VERSION = "1.0.2"
APP_CREDIT = "Designed by Louis_Qi for Vivian"
RUN_VALUE = "QPetDesktopPet"
AUTORUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
PLATFORM = "macos" if IS_MACOS else ("windows" if IS_WINDOWS else "linux")

MOOD_HAPPY_BELOW = 35.0
MOOD_ANGRY_ABOVE = 70.0
MOOD_SAMPLE_S = 2.0
MOOD_HOLD_AFTER_MANUAL_S = 60.0

DEFAULT_REMINDER_S = 45
WINK_DURATION_S = 4.0

BLINK_MIN_S = 2.8
BLINK_MAX_S = 6.5
BLINK_DURATION_S = 0.38
BLINK_DOUBLE_P = 0.15

BLINK_ANIMS = {"idle", "idle-plain", "waiting", "review", "waving"}

EDGE_MODES = {"off": None, "soft": 118, "hard": 170}

HATCH_WINDOW_FACTOR = 2.0
HATCH_T_GROW = 0.55
HATCH_T_CRACK = 1.15
HATCH_T_SPLIT = 1.95
HATCH_T_POP = 2.45
HATCH_T_END = 2.85

def _setup_logger() -> logging.Logger:
    logger = logging.getLogger("qpet")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    try:
        fh = logging.FileHandler(settings_path().parent / "qpet.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(fh)
    except Exception:
        import traceback
        traceback.print_exc()
    return logger

class CpuSampler:

    def __new__(cls):
        if IS_MACOS:
            return super().__new__(_MacCpuSampler)
        if IS_WINDOWS:
            return super().__new__(_WinCpuSampler)
        return super().__new__(_StubCpuSampler)

    def usage(self) -> Optional[float]:
        return None

class _StubCpuSampler(CpuSampler):
    pass

class _MacCpuSampler(CpuSampler):

    def __init__(self):
        self._last: Optional[tuple[int, int]] = None
        self._ps = None

        try:
            self._read_ticks()
        except Exception:
            try:
                import psutil
                self._ps = psutil
                self._ps.cpu_percent(interval=None)
            except Exception:
                pass

    def _read_ticks(self) -> tuple[int, int]:
        out = subprocess.check_output(
            ["sysctl", "-n", "kern.cp_time"], text=True).split()
        u, n, s, idle, intr = (int(v) for v in out[:5])
        busy = u + n + s + intr
        return busy, busy + idle

    def usage(self) -> Optional[float]:
        try:
            if self._ps is not None:
                return max(0.0, min(100.0, self._ps.cpu_percent(interval=None)))
            cur = self._read_ticks()
            result: Optional[float] = None
            if self._last:
                busy_d = cur[0] - self._last[0]
                total_d = cur[1] - self._last[1]
                if total_d > 0:
                    result = max(0.0, min(100.0, 100.0 * busy_d / total_d))
            self._last = cur
            return result
        except Exception:
            return None

class _WinCpuSampler(CpuSampler):

    class _FT(ctypes.Structure):
        _fields_ = [("lo", ctypes.c_ulong), ("hi", ctypes.c_ulong)]

    def __init__(self):
        self._k32 = ctypes.windll.kernel32
        self._last = None

    @staticmethod
    def _u64(ft):
        return (ft.hi << 32) | ft.lo

    def usage(self) -> Optional[float]:
        idle, kernel, user = self._FT(), self._FT(), self._FT()
        if not self._k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        cur = (self._u64(idle),
               self._u64(kernel) + self._u64(user),
               time.time())
        result = None
        if self._last:
            idle_d = cur[0] - self._last[0]
            total_d = cur[1] - self._last[1]
            if total_d > 0:
                result = max(0.0, min(100.0, 100.0 * (1.0 - idle_d / total_d)))
        self._last = cur
        return result

def resource_dir() -> Path:
    if getattr(sys, "frozen", False):

        if IS_MACOS:

            return Path(sys.executable).resolve().parent.parent / "Resources"
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent / "assets"

def settings_path() -> Path:
    if IS_MACOS:
        base = Path.home() / "Library" / "Application Support" / "QPet"
    else:
        base = Path(os.environ.get("APPDATA") or Path.home()) / "QPet"
    base.mkdir(parents=True, exist_ok=True)
    return base / "settings.json"

def load_settings() -> dict:
    default = {"scale": 1.0, "behavior": "playful", "autostart": False,
               "mood_auto": True, "wink_auto": True, "edge_mode": "soft",
               "hatched": False,
               "reminder_s": DEFAULT_REMINDER_S,
               "voice_enabled": True, "voice_pack": "甜嗓默认", "voice_volume": 80}
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            default.update(json.load(f))
    except Exception:
        pass
    return default

def save_settings(s: dict):
    with open(settings_path(), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

VOICE_EVENTS = {
    "greet": "打招呼/孵化登场",
    "happy": "开心（CPU 空闲）",
    "neutral": "平静",
    "angry": "生气（CPU 高载）",
    "wink": "长时间未点击提醒",
    "failed": "失败叹气",
    "wave": "挥手",
}
VOICE_EXTS = (".mp3", ".wav", ".wma")
VOICE_README = """Vivian 桌面宠物 — 语音包说明

每个子文件夹 = 一个语音包。把音频文件放进子文件夹即可。
文件名 = 触发事件（可加编号，如 happy-1.mp3 / happy-2.mp3，播放时随机选一个）。

支持格式：mp3 / wav / wma

可用事件名：
  greet    打招呼/孵化登场
  happy    开心（CPU 空闲）
  neutral  平静
  angry    生气（CPU 高载）
  wink     长时间未点击提醒
  failed   失败叹气
  wave     挥手

示例目录结构：
  voicepacks/
    └─ 我的语音包/
       ├─ greet.mp3
       ├─ happy-1.mp3
       ├─ happy-2.mp3
       ├─ angry.mp3
       └─ wink.mp3

 Designed by Louis_Qi for Vivian
"""

def voice_pack_dirs() -> list:
    dirs = [resource_dir() / "voicepacks"]
    if IS_MACOS:
        user_dir = Path.home() / "Library" / "Application Support" / "QPet" / "voicepacks"
    else:
        base = os.environ.get("APPDATA") or str(Path.home())
        user_dir = Path(base) / "QPet" / "voicepacks"
    dirs.append(user_dir)
    return dirs

def list_voice_packs() -> list:
    packs = []
    seen = set()
    for root in voice_pack_dirs():
        if not root.is_dir():
            continue
        try:
            for d in sorted(root.iterdir()):
                if not d.is_dir() or d.name in seen:
                    continue
                if any(f.suffix.lower() in VOICE_EXTS for f in d.iterdir() if f.is_file()):
                    packs.append(d.name)
                    seen.add(d.name)
        except OSError:
            pass
    return packs

def find_voice_file(pack: str, event: str):
    if not pack:
        return None
    cands = []
    for root in voice_pack_dirs():
        d = root / pack
        if not d.is_dir():
            continue
        try:
            for f in d.iterdir():
                if (f.is_file() and f.suffix.lower() in VOICE_EXTS
                        and f.stem.lower().split("-")[0] == event.lower()):
                    cands.append(f)
        except OSError:
            pass
    return random.choice(cands) if cands else None

class VoicePlayer:

    def __init__(self, root):
        self.root = root
        self._alias = "QPetVoice"
        self._opened = False
        self._last_play = {}
        self._mac_proc = None

    def _mci(self, cmd: str) -> str:
        try:
            buf = ctypes.create_unicode_buffer(260)
            rc = ctypes.windll.winmm.mciSendStringW(cmd, buf, 260, 0)
            return buf.value if rc == 0 else ""
        except Exception:
            return ""

    def _mci_stop(self):
        if self._opened:
            self._mci(f"close {self._alias}")
            self._opened = False

    def _mci_play(self, path: Path, volume: int):
        self._mci_stop()
        p = str(path.resolve()).replace("/", "\\")
        self._mci(f'open "{p}" alias {self._alias}')
        if not self._mci(f"status {self._alias} mode"):
            self._mci(f"close {self._alias}")
            return
        self._opened = True
        self._mci(f"setaudio {self._alias} volume to {max(0, min(1000, int(volume) * 10))}")
        self._mci(f"play {self._alias}")
        self._poll_mci()

    def _poll_mci(self):
        if not self._opened:
            return
        if self._mci(f"status {self._alias} mode") == "stopped":
            self._mci_stop()
        else:
            try:
                self.root.after(500, self._poll_mci)
            except Exception:
                self._mci_stop()

    def _sub_stop(self):
        if self._mac_proc and self._mac_proc.poll() is None:
            try:
                self._mac_proc.terminate()
            except Exception:
                pass
        self._mac_proc = None

    def _sub_play(self, path: Path, volume: int):
        self._sub_stop()
        if IS_MACOS:
            cmd = ["afplay", "-v", str(max(0.0, min(1.0, volume / 100.0))), str(path)]
        else:

            player = shutil.which("mpg123")
            if not player:
                player = shutil.which("aplay")
            if not player:
                return
            cmd = [player, str(path)]
        try:
            self._mac_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.root.after(500, self._poll_sub)
        except Exception:
            self._mac_proc = None

    def _poll_sub(self):
        if self._mac_proc and self._mac_proc.poll() is None:
            try:
                self.root.after(500, self._poll_sub)
            except Exception:
                self._sub_stop()

    def stop(self):
        if IS_WINDOWS:
            self._mci_stop()
        else:
            self._sub_stop()

    def play(self, path, volume: int = 80):
        try:
            path = Path(path)
            now = time.time()
            if now - self._last_play.get(str(path), 0) < 1.5:
                return
            self._last_play[str(path)] = now
            if IS_WINDOWS:
                self._mci_play(path, volume)
            else:
                self._sub_play(path, volume)
        except Exception:
            pass

log = _setup_logger()

def _launchagent_path() -> Path:
    p = Path.home() / "Library" / "LaunchAgents"
    p.mkdir(parents=True, exist_ok=True)
    return p / "com.louisqi.vivian.pet.plist"

def _launchagent_plist(exe: str) -> str:

    exe_esc = exe.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
        "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.louisqi.vivian.pet</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe_esc}</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><false/>
</dict>
</plist>
"""

def autorun_enabled() -> bool:
    if IS_WINDOWS:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTORUN_KEY, 0, winreg.KEY_READ) as k:
                winreg.QueryValueEx(k, RUN_VALUE)
                return True
        except OSError:
            return False
    if IS_MACOS:
        return _launchagent_path().exists()
    return False

def set_autorun(enable: bool, exe_path: str = None):
    if IS_WINDOWS:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTORUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                if enable:
                    exe = exe_path or sys.executable
                    winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, f'"{exe}"')
                else:
                    try:
                        winreg.DeleteValue(k, RUN_VALUE)
                    except OSError:
                        pass
        except OSError:
            pass
    elif IS_MACOS:
        p = _launchagent_path()
        if enable:
            exe = exe_path or sys.executable
            try:
                p.write_text(_launchagent_plist(exe), encoding="utf-8")
            except OSError:
                pass
        else:
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass

class QPetApp(DesktopPet):

    _EYE_LEFT = (77, 81)
    _EYE_RIGHT = (114, 80)
    _EYE_R = 8
    _EYE_RY = 7

    def __init__(self, mood_auto: bool = True, wink_auto: bool = True,
                 edge_mode: str = "soft", spritesheet_path: str = None,
                 hatch: bool = False, reminder_s: int = DEFAULT_REMINDER_S,
                 voice_enabled: bool = True, voice_pack: str = "",
                 voice_volume: int = 80, **kwargs):
        self._spritesheet_path = spritesheet_path
        self._hatch_active = False

        self.edge_mode = edge_mode if edge_mode in EDGE_MODES else "soft"
        super().__init__(spritesheet_path=spritesheet_path, **kwargs)
        self.mood_auto = mood_auto
        self.wink_auto = wink_auto
        self.edge_mode = edge_mode if edge_mode in EDGE_MODES else "soft"
        self.reminder_s = max(5, min(600, int(reminder_s)))

        self.voice_enabled = bool(voice_enabled)
        self.voice_pack = str(voice_pack or "")
        self.voice_volume = max(0, min(100, int(voice_volume)))
        self.voice = VoicePlayer(self.root)
        self._mood = "neutral"
        self._cpu_ema = None
        self._mood_hold_until = 0.0
        self._cpu_sampler = CpuSampler()

        self._wink_active = False
        self._wink_until = 0.0
        self._last_interaction = time.time()

        self._blink_start = None
        self._blink_next = time.time() + random.uniform(2.0, 5.0)
        self._blink_photo = None

        self._gaze_base_img = None
        self._gaze_angle = 0.0
        self._gaze_skin = None
        self._sheet_img = None
        self._cell_cache = {}
        try:
            sheet = dr.Image.open(self._spritesheet_path).convert("RGBA")
            row = 9
            cell_w, cell_h = dr.CELL_WIDTH, dr.CELL_HEIGHT
            self._gaze_base_img = sheet.crop((0, row * cell_h, cell_w, row * cell_h + cell_h))
            if self.scale != 1.0:
                self._gaze_base_img = self._gaze_base_img.resize(
                    (self.win_w, self.win_h), dr.Image.LANCZOS)
        except Exception:
            pass

        self._icon_photo = None
        try:
            ico = resource_dir() / "vivian.ico"
            png = ico.with_suffix(".png")
            src = png if png.exists() else ico
            if src.exists():
                from PIL import Image as _PILImage
                from PIL.ImageTk import PhotoImage as _ImageTk
                img = _PILImage.open(src).resize((64, 64), _PILImage.LANCZOS)
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                self._icon_photo = _ImageTk(img)
                self.root.iconphoto(True, self._icon_photo)
        except Exception:
            pass
        self.root.title(APP_NAME)
        self.root.after(int(MOOD_SAMPLE_S * 1000), self._mood_tick)
        log.info("启动: mood_auto=%s wink_auto=%s edge_mode=%s scale=%s reminder=%ss voice=%s/%s",
                 mood_auto, wink_auto, self.edge_mode, self.scale,
                 self.reminder_s, self.voice_enabled, self.voice_pack)
        if hatch:
            self._hatch_begin()

    def _play_voice(self, event: str):
        try:
            if not self.voice_enabled or not self.voice_pack:
                return
            f = find_voice_file(self.voice_pack, event)
            if f:
                self.voice.play(f, self.voice_volume)
        except Exception as e:
            log.exception("语音播放失败: %s", e)

    _MOOD_ANIM = {"happy": "idle", "neutral": "idle-plain", "angry": "angry"}
    _MOOD_MSG = {
        "happy": "电脑好闲呀～开心得想捧花转圈 🌼",
        "neutral": "负载一般般，安静陪着你～",
        "angry": "CPU 快烧了！哼！气死啦！💢",
    }

    def _mood_tick(self):
        try:
            if self._hatch_active:
                return
            u = self._cpu_sampler.usage()
            if u is not None:
                self._cpu_ema = u if self._cpu_ema is None else self._cpu_ema * 0.5 + u * 0.5
                self._apply_mood()
            self._wink_check()
        except Exception as e:
            log.exception("mood tick 失败: %s", e)
        finally:
            self.root.after(int(MOOD_SAMPLE_S * 1000), self._mood_tick)

    _WINK_ANIM = "wink"
    _WINK_MSG = "都不理人家好久了…哼，偷亲你一下~ 😉"

    def _frame_to_tk(self, frame):
        from PIL import Image as PILImage
        from PIL.ImageTk import PhotoImage as _ImageTk
        threshold = EDGE_MODES.get(self.edge_mode, 118)
        r, g, b, a = frame.split()
        if threshold is None:
            composite = PILImage.merge("RGB", (r, g, b))
        else:
            mask = a.point(lambda v: 255 if v >= threshold else 0)
            magenta_bg = PILImage.new("RGB", frame.size, (255, 0, 255))
            rgb = PILImage.merge("RGB", (r, g, b))
            composite = PILImage.composite(rgb, magenta_bg, mask)
        return _ImageTk(composite)

    def _load_spritesheet(self, path):
        sheet = dr.Image.open(path).convert("RGBA")
        anim_frames = {}
        gaze_frames = {}

        sprite_cfg = self.config.get("sprite", {})
        cell_w = sprite_cfg.get("cell", {}).get("width", dr.CELL_WIDTH)
        cell_h = sprite_cfg.get("cell", {}).get("height", dr.CELL_HEIGHT)
        cols_max = sprite_cfg.get("cols", dr.COLS)

        for anim in self.config.get("animations", []):
            name = anim.get("name", "idle")
            row = anim.get("row", 0)
            count = anim.get("frameCount", 8)
            frame_list = []
            for col in range(min(count, cols_max)):
                x = col * cell_w
                y = row * cell_h
                cell = sheet.crop((x, y, x + cell_w, y + cell_h))
                if self.scale != 1.0:
                    cell = cell.resize((self.win_w, self.win_h), dr.Image.LANCZOS)
                frame_list.append(self._frame_to_tk(cell))
            anim_frames[name] = frame_list

        for gaze in self.config.get("gazes", []):
            name = gaze.get("name")
            row = gaze.get("row", 9)
            col = gaze.get("col", 0)
            x = col * cell_w
            y = row * cell_h
            cell = sheet.crop((x, y, x + cell_w, y + cell_h))
            if self.scale != 1.0:
                cell = cell.resize((self.win_w, self.win_h), dr.Image.LANCZOS)
            gaze_frames[name] = self._frame_to_tk(cell)

        return anim_frames, gaze_frames

    def _skin_color(self, img):
        px = img.load()
        s = self.scale
        lx = round(self._EYE_LEFT[0] * s)
        ly = round(self._EYE_LEFT[1] * s)
        cs = []
        for ddy in range(-10, -4):
            for ddx in range(-3, 4):
                x, y = lx + ddx, ly + ddy
                if 0 <= x < img.width and 0 <= y < img.height:
                    p = px[x, y]
                    if p[3] > 200 and p[0] > 100:
                        cs.append(p[:3])
        if not cs:
            return (255, 235, 225)
        return tuple(sum(c[i] for c in cs) // len(cs) for i in range(3))

    def _make_gaze_frame(self, angle_deg: float):
        if self._gaze_base_img is None:
            return None
        if self._gaze_skin is None:
            self._gaze_skin = self._skin_color(self._gaze_base_img)
        img = self._gaze_base_img.copy()
        s = self.scale
        R = max(2, round(self._EYE_R * s))
        RY = max(2, round(self._EYE_RY * s))
        rad = math.radians(angle_deg)

        dx, dy = math.sin(rad) * 3.0 * s, -math.cos(rad) * 3.0 * s
        for ex, ey in (self._EYE_LEFT, self._EYE_RIGHT):
            cx, cy = round(ex * s), round(ey * s)

            max_x = max(0.5, R - 4.6 - 0.6)
            max_y = max(0.5, RY - 4.6 - 0.8)
            ix = max(-max_x, min(max_x, dx))
            iy = max(-max_y, min(max_y, dy))
            tile = self._eye_tile(cx, cy, R, RY, ix, iy)
            img.alpha_composite(tile, (cx - tile.width // 2, cy - tile.height // 2))
        return img

    def _eye_tile(self, cx: int, cy: int, R: int, RY: int,
                  ix: float, iy: float):
        from PIL import ImageDraw
        ss = 4
        m = 4
        size = 2 * (R + m)
        S = ss
        c = (R + m) * S
        tile = dr.Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))
        d = ImageDraw.Draw(tile)
        skin = tuple(int(v) for v in self._gaze_skin)

        d.ellipse([(c - (R + 2.2) * S), (c - (RY + 2.2) * S),
                   (c + (R + 2.2) * S), (c + (RY + 2.2) * S)],
                  fill=skin + (255,))

        d.ellipse([(c - (R + 0.4) * S), (c - (RY + 0.4) * S),
                   (c + (R + 0.4) * S), (c + (RY + 0.4) * S)],
                  fill=(253, 246, 239, 255))

        d.arc([(c - (R + 0.4) * S), (c - (RY + 0.4) * S),
               (c + (R + 0.4) * S), (c + (RY + 0.4) * S)],
              start=192, end=348, fill=(92, 60, 50, 255),
              width=max(1, round(1.5 * S)))

        icx, icy = c + ix * S, c + iy * S
        r_i = 4.6 * S
        d.ellipse([icx - r_i, icy - r_i, icx + r_i, icy + r_i],
                  fill=(137, 98, 80, 255))
        r_m = 4.0 * S
        d.ellipse([icx - r_m, icy - r_m, icx + r_m, icy + r_m],
                  fill=(104, 69, 54, 255))
        r_p = 2.6 * S
        d.ellipse([icx - r_p, icy - r_p, icx + r_p, icy + r_p],
                  fill=(54, 34, 27, 255))
        r_h = 1.35 * S
        hx, hy = icx - 1.5 * S, icy - 1.5 * S
        d.ellipse([hx - r_h, hy - r_h, hx + r_h, hy + r_h],
                  fill=(255, 255, 255, 255))

        return tile.resize((size, size), dr.Image.LANCZOS)

    def _pil_cell(self, anim: str, idx: int):
        if self._sheet_img is None:
            try:
                self._sheet_img = dr.Image.open(self._spritesheet_path).convert("RGBA")
            except Exception:
                return None
        key = (anim, idx)
        if key not in self._cell_cache:
            row = None
            for a in self.config.get("animations", []):
                if a.get("name") == anim:
                    row = a.get("row", 0)
                    break
            if row is None:
                return None
            sprite = self.config.get("sprite", {})
            cw = sprite.get("cell", {}).get("width", dr.CELL_WIDTH)
            ch = sprite.get("cell", {}).get("height", dr.CELL_HEIGHT)
            cell = self._sheet_img.crop((idx * cw, row * ch, idx * cw + cw, row * ch + ch))
            if self.scale != 1.0:
                cell = cell.resize((self.win_w, self.win_h), dr.Image.LANCZOS)
            self._cell_cache[key] = cell
        return self._cell_cache[key]

    def _eye_pos_frame(self, anim: str, idx: int):
        track = (self.config or {}).get("eyeTracks", {}).get(anim)
        if track and idx < len(track):
            lx, ly, rx, ry = track[idx]
            return (lx, ly), (rx, ry)
        return self._EYE_LEFT, self._EYE_RIGHT

    def _apply_blink(self, img, amt: float, eye_l=None, eye_r=None):
        from PIL import ImageDraw, ImageFilter
        img = img.copy()
        s = self.scale
        skin = self._skin_color(img)
        hw = self._EYE_R * s + 1.0
        eh = self._EYE_RY * s + 1.0
        for ex, ey in (eye_l or self._EYE_LEFT, eye_r or self._EYE_RIGHT):
            cx, cy = round(ex * s), round(ey * s)
            m = 3
            size = int(2 * (hw + m)) + 2
            ss = 4
            S = ss
            c = size * S / 2.0

            mask = dr.Image.new("L", (size * S, size * S), 0)
            dm = ImageDraw.Draw(mask)
            dm.ellipse([(c - hw * S), (c - eh * S), (c + hw * S), (c + eh * S)],
                       fill=255)
            lid_y = (c - eh * S) + 2 * eh * S * amt
            bulge = eh * S * 0.35 * amt
            lid_bbox = [(c - hw * S), lid_y - 2 * bulge,
                        (c + hw * S), lid_y]

            dm.rectangle([0, lid_y, size * S, size * S], fill=0)
            dm.ellipse(lid_bbox, fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(1.5))

            tile = dr.Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))
            lid_skin = tuple(min(255, int(v) + 6) for v in skin)
            tile.paste(lid_skin + (255,), (0, 0), mask)

            if amt > 0.45:
                lash = dr.Image.new("L", (size * S, size * S), 0)
                dl = ImageDraw.Draw(lash)
                dl.arc(lid_bbox, start=20, end=160, fill=255,
                       width=max(1, round(1.4 * s * S)))
                k = min(1.0, (amt - 0.45) / 0.3)
                lash = lash.point(lambda v: int(v * k))
                tile.paste((74, 47, 43, 255), (0, 0), lash)

            tile = tile.resize((size, size), dr.Image.LANCZOS)
            img.alpha_composite(tile, (int(cx - size / 2), int(cy - size / 2)))
        return img

    def _blink_amount(self) -> float:
        if self._blink_start is None:
            return 0.0
        t = (time.time() - self._blink_start) / BLINK_DURATION_S
        if t >= 1.0:
            self._blink_start = None
            gap = 0.28 if random.random() < BLINK_DOUBLE_P else random.uniform(BLINK_MIN_S, BLINK_MAX_S)
            self._blink_next = time.time() + gap
            return 0.0
        if t < 0.4:
            k = t / 0.4
        else:
            k = 1.0 - (t - 0.4) / 0.6
        return k * k * (3 - 2 * k)

    def _render_frame(self):
        if self._hatch_active:
            self._render_hatch_frame()
            return

        super()._render_frame()

        now = time.time()

        can_blink = (not self._wink_active and not self.dragging
                     and not self.watch_mode
                     and self.current_anim in BLINK_ANIMS)
        if self._blink_start is not None and not can_blink:

            self._blink_start = None
            self._blink_next = now + random.uniform(BLINK_MIN_S, BLINK_MAX_S)
            return
        if self._blink_start is None:
            if can_blink and now >= self._blink_next:
                self._blink_start = now
            else:
                return

        amt = self._blink_amount()
        if amt <= 0.03:
            return
        pil = self._pil_cell(self.current_anim, self.current_frame)
        if pil is None:
            return
        eye_l, eye_r = self._eye_pos_frame(self.current_anim, self.current_frame)
        self._blink_photo = self._frame_to_tk(
            self._apply_blink(pil, amt, eye_l, eye_r))
        self.canvas.itemconfig(self.image_id, image=self._blink_photo)

    @staticmethod
    def _ease_out_back(x: float) -> float:
        c1, c3 = 1.70158, 2.70158
        return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2

    def _hatch_begin(self):
        from PIL import Image as PILImage, ImageDraw as PILImageDraw
        try:
            self._hatch_w = int(self.win_w * HATCH_WINDOW_FACTOR)
            self._hatch_h = int(self.win_h * HATCH_WINDOW_FACTOR)

            cx = self.root.winfo_x() + self.win_w // 2
            cy = self.root.winfo_y() + self.win_h // 2
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            x = max(0, min(cx - self._hatch_w // 2, sw - self._hatch_w))
            y = max(0, min(cy - self._hatch_h // 2, sh - self._hatch_h))
            self._hatch_x, self._hatch_y = x, y
            self.root.geometry(f"{self._hatch_w}x{self._hatch_h}+{x}+{y}")
            self.canvas.config(width=self._hatch_w, height=self._hatch_h)
            self.canvas.coords(self.image_id, self._hatch_w // 2, self._hatch_h // 2)
            self.spring_x.reset(x)
            self.spring_y.reset(y)

            size = self._egg_size = int(min(self._hatch_w, self._hatch_h) * 0.62)
            tile = PILImage.new("RGBA", (size, size), (0, 0, 0, 0))
            td = PILImageDraw.Draw(tile)
            td.rounded_rectangle([2, 2, size - 3, size - 3], radius=size // 5,
                                 fill=(252, 250, 253, 255),
                                 outline=(222, 210, 230, 255),
                                 width=max(2, size // 70))
            try:
                art = PILImage.open(resource_dir() / "vivian.png").convert("RGBA")
                tw = int(size * 0.74)
                th = int(art.height * tw / art.width)
                art = art.resize((tw, th), PILImage.LANCZOS)
                tile.alpha_composite(art, ((size - tw) // 2, (size - th) // 2))
            except Exception:
                pass
            self._egg_img = tile

            rnd = random.Random(7)
            self._crack_pts = [(0.5 + rnd.uniform(-0.07, 0.07), i / 8) for i in range(9)]
            pts = [(int(px * size), int(py * size)) for px, py in self._crack_pts]
            self._egg_left = self._egg_half(tile, pts, left=True)
            self._egg_right = self._egg_half(tile, pts, left=False)

            sheet = dr.Image.open(self._spritesheet_path).convert("RGBA")
            cw = self.config.get("sprite", {}).get("cell", {}).get("width", dr.CELL_WIDTH)
            ch = self.config.get("sprite", {}).get("cell", {}).get("height", dr.CELL_HEIGHT)
            self._hatch_char = sheet.crop((0, 0, cw, ch)).resize(
                (self._hatch_w, self._hatch_h), dr.Image.LANCZOS)

            self._hatch_t0 = time.time()
            self._hatch_active = True
            self.random_engine.enabled = False
            self._hatch_photo = None
            log.info("孵化动画开始")
        except Exception as e:
            log.exception("孵化动画准备失败: %s", e)
            self._hatch_active = False

    @staticmethod
    def _egg_half(egg, pts, left: bool):
        from PIL import Image as PILImage, ImageDraw as PILImageDraw
        size = egg.width
        poly = ([(0, 0)] + pts + [(0, size)]) if left else ([(size, 0)] + pts + [(size, size)])
        mask = PILImage.new("L", (size, size), 0)
        PILImageDraw.Draw(mask).polygon(poly, fill=255)
        half = egg.copy()
        half.putalpha(PILImage.composite(egg.getchannel("A"),
                                         PILImage.new("L", (size, size), 0), mask))
        return half

    def _paste_halves(self, img, sep: float, rot_deg: float, fade: float):
        if fade <= 0:
            return
        HW, HH = self._hatch_w, self._hatch_h
        cx = HW // 2
        es = self._egg_size
        for half, sign in ((self._egg_left, -1), (self._egg_right, 1)):
            h = half.rotate(sign * rot_deg, resample=dr.Image.BICUBIC, expand=True)
            if fade < 1.0:
                h.putalpha(h.getchannel("A").point(lambda v: int(v * fade)))
            img.paste(h, (int(cx + sign * sep - h.width / 2),
                          int(HH - es / 2 - h.height / 2)), h)

    def _paste_char(self, img, scale: float):
        HW, HH = self._hatch_w, self._hatch_h
        w, h = max(1, int(HW * scale)), max(1, int(HH * scale))
        char = self._hatch_char.resize((w, h), dr.Image.LANCZOS)
        img.paste(char, (HW // 2 - w // 2, HH - h), char)

    def _hatch_resize(self, w: int, h: int):
        cx = self._hatch_x + self._hatch_w // 2
        cy = self._hatch_y + self._hatch_h // 2
        self.root.geometry(f"{w}x{h}+{cx - w // 2}+{cy - h // 2}")
        self.canvas.config(width=w, height=h)
        self.canvas.coords(self.image_id, w // 2, h // 2)

    def _render_hatch_frame(self):
        from PIL import Image as PILImage, ImageDraw as PILImageDraw
        t = time.time() - self._hatch_t0
        HW, HH = self._hatch_w, self._hatch_h
        cx = HW // 2
        img = PILImage.new("RGBA", (HW, HH), (0, 0, 0, 0))
        d = PILImageDraw.Draw(img)

        if t < HATCH_T_CRACK:

            if t < HATCH_T_GROW:
                k = self._ease_out_back(max(0.0, t / HATCH_T_GROW))
                es = max(8, int(self._egg_size * (0.30 + 0.70 * k)))
            else:
                es = self._egg_size
            shake = 0.0
            if t > HATCH_T_GROW:
                shake = math.sin((t - HATCH_T_GROW) * 36) * (t - HATCH_T_GROW) * 14
            egg = self._egg_img.resize((es, es), PILImage.LANCZOS)
            ex, ey = int(cx - es / 2 + shake), HH - es
            img.paste(egg, (ex, ey), egg)
            if t > HATCH_T_GROW * 0.8:
                g = min(1.0, (t - HATCH_T_GROW * 0.8) / (HATCH_T_CRACK - HATCH_T_GROW * 0.8))
                n = max(2, int(1 + g * (len(self._crack_pts) - 1)))
                pts = [(ex + int(px * es), ey + int(py * es))
                       for px, py in self._crack_pts[:n]]
                d.line(pts, fill=(122, 92, 76, 235), width=max(2, es // 42), joint="curve")
        elif t < HATCH_T_SPLIT:

            k = (t - HATCH_T_CRACK) / (HATCH_T_SPLIT - HATCH_T_CRACK)
            self._paste_halves(img, k * HW * 0.16, k * 20, 1.0)
            self._paste_char(img, 0.32 + 0.43 * k)
        elif t < HATCH_T_POP:

            k = (t - HATCH_T_SPLIT) / (HATCH_T_POP - HATCH_T_SPLIT)
            self._paste_halves(img, HW * 0.16 + 300 * k * k, 20 + 55 * k,
                               max(0.0, 1.0 - k * 1.5))
            pop = self._ease_out_back(min(1.0, k * 1.35))
            self._paste_char(img, 0.75 + 0.25 * pop)
            for i in range(10):
                a = math.radians(i * 36 + 18)
                dist = HH * 0.18 + HH * 0.38 * k
                sx = cx + math.cos(a) * dist * 0.8
                sy = HH * 0.45 + math.sin(a) * dist * 0.6
                col = [(255, 214, 120), (255, 150, 190), (255, 255, 255)][i % 3]
                r = max(2, int(HH * 0.018 * (1 - k)))
                d.line([(sx - r, sy), (sx + r, sy)], fill=col, width=2)
                d.line([(sx, sy - r), (sx, sy + r)], fill=col, width=2)
        elif t < HATCH_T_END:

            k = (t - HATCH_T_POP) / (HATCH_T_END - HATCH_T_POP)
            k = k * k * (3 - 2 * k)
            w = int(HW + (self.win_w - HW) * k)
            h = int(HH + (self.win_h - HH) * k)
            self._hatch_resize(w, h)
            img = PILImage.new("RGBA", (w, h), (0, 0, 0, 0))
            char = self._hatch_char.resize((w, h), dr.Image.LANCZOS)
            img.paste(char, (0, 0), char)
        else:
            self._hatch_finish()
            return

        self._hatch_photo = self._frame_to_tk(img)
        self.canvas.itemconfig(self.image_id, image=self._hatch_photo)

    def _hatch_finish(self):
        self._hatch_active = False
        w, h = self.win_w, self.win_h
        cx = self._hatch_x + self._hatch_w // 2
        cy = self._hatch_y + self._hatch_h // 2
        x, y = cx - w // 2, cy - h // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.canvas.config(width=w, height=h)
        self.canvas.coords(self.image_id, w // 2, h // 2)
        self.spring_x.reset(x)
        self.spring_y.reset(y)
        try:
            self.random_engine.current_x = x
            self.random_engine.current_y = y
        except Exception:
            pass
        if load_settings().get("behavior", "playful") != "off":
            self.random_engine.enabled = True
        self._skip_wave_voice = True
        self._switch_anim("waving", force=True)
        self._show_bubble("我出来啦～以后请多关照！🌼", "greet")
        self._play_voice("greet")
        log.info("孵化动画结束")

        self._egg_img = self._egg_left = self._egg_right = None
        self._hatch_char = None

    def _update_watch(self):
        mx = self.root.winfo_pointerx()
        my = self.root.winfo_pointery()
        cx = self.root.winfo_x() + self.win_w // 2
        cy = self.root.winfo_y() + self.win_h // 2

        angle = math.degrees(math.atan2(mx - cx, cy - my))
        if angle < 0:
            angle += 360

        best_gaze, best_angle, best_diff = None, 0.0, 999
        for gaze in self.config.get("gazes", []):
            g_angle = gaze.get("angle", 0)
            diff = abs(angle - g_angle)
            if diff > 180:
                diff = 360 - diff
            if diff < best_diff:
                best_diff = diff
                best_gaze = gaze.get("name")
                best_angle = g_angle

        if best_gaze and best_gaze != self.current_gaze:
            self.current_gaze = best_gaze
            self._gaze_angle = best_angle

            pil_img = self._make_gaze_frame(best_angle)
            if pil_img is not None:
                self.gaze_frames[best_gaze] = self._frame_to_tk(pil_img)

    def _quit(self):
        try:
            self.voice.stop()
        except Exception:
            pass
        super()._quit()

    def _mark_interaction(self):
        self._last_interaction = time.time()

    def _switch_anim(self, name: str, force: bool = False):
        was = self.current_anim
        super()._switch_anim(name, force)
        if self._hatch_active or name == was:
            return
        if name == "failed" and name in self.frames:

            self._play_voice("failed")
            self._show_bubble("唉……先叹口气……", "loafing")
        elif name == "waving" and force and name in self.frames:

            if getattr(self, "_skip_wave_voice", False):
                self._skip_wave_voice = False
            else:
                self._play_voice("wave")

    def _on_drag_start(self, event):
        if self._hatch_active:
            return
        self._mark_interaction()
        super()._on_drag_start(event)

    def _on_drag_end(self, event):
        if self._hatch_active:
            return
        super()._on_drag_end(event)

    def _wink_check(self):
        now = time.time()

        if self._wink_active:
            if now >= self._wink_until:
                self._wink_active = False
                self._last_interaction = now
                anim = self._MOOD_ANIM.get(self._mood, "idle")
                if anim in self.frames:
                    self._switch_anim(anim, force=True)
                log.info("wink 结束 -> %s", anim)
            return
        if not self.wink_auto or self.dragging:
            return
        if self.mood_auto and time.time() < self._mood_hold_until:
            return
        if now - self._last_interaction < self.reminder_s:
            return

        if self.current_anim not in self._MOOD_ANIM.values():
            return
        if "wink" not in self.frames:
            return
        self._wink_active = True
        self._wink_until = now + WINK_DURATION_S
        self._switch_anim(self._WINK_ANIM, force=True)
        self._show_bubble(self._WINK_MSG, self._WINK_ANIM)
        self._play_voice("wink")
        log.info("wink 触发（无点击 %.0fs）", now - self._last_interaction)

    def _mood_of(self, cpu: float) -> str:
        if cpu < MOOD_HAPPY_BELOW:
            return "happy"
        if cpu > MOOD_ANGRY_ABOVE:
            return "angry"
        return "neutral"

    def _apply_mood(self):
        if not self.mood_auto or self.dragging or self._wink_active:
            return
        if time.time() < self._mood_hold_until:
            return
        mood = self._mood_of(self._cpu_ema)
        if mood != self._mood:
            old = self._mood
            self._mood = mood
            anim = self._MOOD_ANIM[mood]
            if anim in self.frames:
                self._switch_anim(anim, force=True)
            self._show_bubble(self._MOOD_MSG[mood], anim)
            self._play_voice(mood)
            log.info("情绪: %s -> %s (CPU %.0f%%)", old, mood, self._cpu_ema)

    def _show_left_menu(self, event):
        self._mark_interaction()
        self._mood_hold_until = time.time() + MOOD_HOLD_AFTER_MANUAL_S
        super()._show_left_menu(event)

    def _on_right_click(self, event):
        if self._hatch_active:
            return
        self._mark_interaction()
        tk = dr.tk
        if getattr(self, "_radial_win", None) and self._radial_win.winfo_exists():
            self._close_radial()
            return

        items = [{"icon": "🎯", "label": "跟随", "act": self._toggle_follow}]
        if not self.config.get("gifMode"):
            items.append({"icon": "👀", "label": "观察", "act": self._toggle_watch})
        items += [
            {"icon": "🎲", "label": "活动", "act": self._cycle_behavior},
            {"icon": "⚙️", "label": "设置", "act": self._open_settings},
            {"icon": "🌙", "label": "隐藏", "act": self._hide_to_tray},
            {"icon": "🚪", "label": "退出", "act": self._quit},
        ]
        n = len(items)
        radius = 70
        btn_r = 22
        start_a, end_a = 180, 360
        cx = self.win_w // 2
        cy = -radius // 2

        win_size = (radius + btn_r) * 2 + 10
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="magenta")
        try:
            win.attributes("-transparentcolor", "magenta")
        except tk.TclError:
            pass
        px = self.root.winfo_x()
        py = self.root.winfo_y()
        win_x = px + cx - win_size // 2
        win_y = py - radius - btn_r - 5
        win.geometry(f"{win_size}x{win_size}+{win_x}+{win_y}")

        cv = tk.Canvas(win, width=win_size, height=win_size,
                       bg="magenta", highlightthickness=0)
        cv.pack()

        local_cx = win_size // 2
        local_cy = win_size - btn_r - 5

        for i, it in enumerate(items):
            a = math.radians(start_a + (end_a - start_a) * (i / (n - 1) if n > 1 else 0.5))
            bx = local_cx + radius * math.cos(a)
            by = local_cy + radius * math.sin(a)
            cv.create_oval(bx - btn_r, by - btn_r, bx + btn_r, by + btn_r,
                           fill="#FFFFFF", outline="#888888", width=2,
                           tags=f"btn{i}")
            cv.create_text(bx, by - 4, text=it["icon"], font=("Segoe UI Emoji", 14),
                           tags=f"btn{i}")
            cv.create_text(bx, by + btn_r - 6, text=it["label"],
                           font=("Microsoft YaHei", 8), fill="#444444",
                           tags=f"btn{i}")
            cv.tag_bind(f"btn{i}", "<Button-1>",
                        lambda e, act=it["act"]: self._radial_click(act))

        self._radial_win = win
        self._radial_canvas = cv
        cv.bind("<Button-1>", lambda e: self._close_radial() if not self._radial_hit_btn(e) else None)
        win.bind("<Escape>", lambda e: self._close_radial())
        win.bind("<FocusOut>", lambda e: self._close_radial())
        win.focus_set()

    def _open_settings(self):
        tk = dr.tk
        self._close_radial()
        st = load_settings()

        win = tk.Toplevel(self.root)
        win.title(f"{APP_NAME} - 设置")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win.configure(bg="#F5F5F7")
        win.grab_set()

        pad = {"padx": 14, "pady": 6}

        tk.Label(win, text="⚙️ 宠物设置", font=("Microsoft YaHei", 14, "bold"),
                 bg="#F5F5F7", fg="#333333").grid(row=0, column=0, columnspan=2,
                                                  pady=(14, 6))

        tk.Label(win, text="显示缩放（重启后生效）", bg="#F5F5F7",
                 fg="#333333", font=("Microsoft YaHei", 10)).grid(
            row=1, column=0, sticky="w", **pad)
        scale_var = tk.StringVar(value=f"{st['scale']:.2f}")
        tk.Spinbox(win, from_=0.5, to=2.0, increment=0.25, width=6,
                   textvariable=scale_var, font=("Consolas", 10)).grid(
            row=1, column=1, sticky="e", **pad)

        tk.Label(win, text="行为模式", bg="#F5F5F7", fg="#333333",
                 font=("Microsoft YaHei", 10)).grid(row=2, column=0, sticky="w", **pad)
        preset_names = {"playful": "调皮", "relaxed": "悠闲",
                        "curious": "好奇", "active": "活跃", "off": "关闭"}
        behavior_var = tk.StringVar(value=preset_names.get(st["behavior"], "调皮"))
        ttk_cb = None
        try:
            from tkinter import ttk
            ttk_cb = ttk.Combobox(win, textvariable=behavior_var, state="readonly",
                                  values=list(preset_names.values()), width=8)
            ttk_cb.grid(row=2, column=1, sticky="e", **pad)
        except Exception:
            tk.Entry(win, textvariable=behavior_var, width=10).grid(
                row=2, column=1, sticky="e", **pad)

        follow_var = tk.BooleanVar(value=self.follow_mode and not self.watch_mode)
        watch_var = tk.BooleanVar(value=self.watch_mode)

        def _on_follow_toggle(*_):
            if follow_var.get():
                watch_var.set(False)

        def _on_watch_toggle(*_):
            if watch_var.get():
                follow_var.set(False)

        follow_var.trace_add("write", _on_follow_toggle)
        watch_var.trace_add("write", _on_watch_toggle)
        tk.Checkbutton(win, text="跟随鼠标模式（与观察模式二选一）", variable=follow_var,
                       bg="#F5F5F7", fg="#333333",
                       font=("Microsoft YaHei", 10)).grid(
            row=3, column=0, columnspan=2, sticky="w", **pad)
        tk.Checkbutton(win, text="观察模式（眼睛看鼠标，与跟随二选一）", variable=watch_var,
                       bg="#F5F5F7", fg="#333333",
                       font=("Microsoft YaHei", 10)).grid(
            row=4, column=0, columnspan=2, sticky="w", **pad)

        auto_var = tk.BooleanVar(value=autorun_enabled())
        tk.Checkbutton(win, text="开机自动启动", variable=auto_var,
                       bg="#F5F5F7", fg="#333333",
                       font=("Microsoft YaHei", 10)).grid(
            row=5, column=0, columnspan=2, sticky="w", **pad)

        mood_var = tk.BooleanVar(value=getattr(self, "mood_auto", True))
        tk.Checkbutton(win, text="情绪随电脑负载变化（低载开心捧花 / 高载生气）",
                       variable=mood_var, bg="#F5F5F7", fg="#333333",
                       font=("Microsoft YaHei", 10)).grid(
            row=6, column=0, columnspan=2, sticky="w", **pad)

        wink_var = tk.BooleanVar(value=getattr(self, "wink_auto", True))
        tk.Checkbutton(win, text="长时间未点击时眨眼提醒（头部放大 wink）",
                       variable=wink_var, bg="#F5F5F7", fg="#333333",
                       font=("Microsoft YaHei", 10)).grid(
            row=7, column=0, columnspan=2, sticky="w", **pad)
        tk.Label(win, text="提醒时间（秒，5~600）", bg="#F5F5F7",
                 fg="#333333", font=("Microsoft YaHei", 10)).grid(
            row=8, column=0, sticky="w", **pad)
        try:
            cur_reminder = int(getattr(self, "reminder_s", DEFAULT_REMINDER_S))
        except Exception:
            cur_reminder = DEFAULT_REMINDER_S
        reminder_var = tk.StringVar(value=str(cur_reminder))
        tk.Spinbox(win, from_=5, to=600, increment=5, width=6,
                   textvariable=reminder_var, font=("Consolas", 10)).grid(
            row=8, column=1, sticky="e", **pad)

        tk.Label(win, text="边缘处理（重启后生效）", bg="#F5F5F7",
                 fg="#333333", font=("Microsoft YaHei", 10)).grid(
            row=9, column=0, sticky="w", **pad)
        edge_names = {"soft": "软边（自然贴合）", "hard": "硬边（锐利无紫边）",
                      "off": "关闭（保留紫边）"}
        edge_var = tk.StringVar(value=edge_names.get(
            getattr(self, "edge_mode", "soft"), "软边（自然贴合）"))
        try:
            from tkinter import ttk as _ttk
            _ttk.Combobox(win, textvariable=edge_var, state="readonly",
                          values=list(edge_names.values()), width=18).grid(
                row=9, column=1, sticky="e", **pad)
        except Exception:
            tk.Entry(win, textvariable=edge_var, width=20).grid(
                row=9, column=1, sticky="e", **pad)

        voice_var = tk.BooleanVar(value=getattr(self, "voice_enabled", True))
        tk.Checkbutton(win, text="启用语音包（动画/情绪变化时播放语音）",
                       variable=voice_var, bg="#F5F5F7", fg="#333333",
                       font=("Microsoft YaHei", 10)).grid(
            row=10, column=0, columnspan=2, sticky="w", **pad)

        packs = list_voice_packs()
        NO_PACK = "（不使用）"
        cur_pack = getattr(self, "voice_pack", "")
        pack_names = [NO_PACK] + packs
        if cur_pack and cur_pack not in packs:
            pack_names.append(cur_pack)
        tk.Label(win, text="语音包", bg="#F5F5F7", fg="#333333",
                 font=("Microsoft YaHei", 10)).grid(
            row=11, column=0, sticky="w", **pad)
        pack_var = tk.StringVar(value=cur_pack if cur_pack in packs else NO_PACK)
        try:
            from tkinter import ttk as _ttk2
            _ttk2.Combobox(win, textvariable=pack_var, state="readonly",
                           values=pack_names, width=14).grid(
                row=11, column=1, sticky="e", **pad)
        except Exception:
            tk.Entry(win, textvariable=pack_var, width=16).grid(
                row=11, column=1, sticky="e", **pad)

        tk.Label(win, text="语音音量", bg="#F5F5F7", fg="#333333",
                 font=("Microsoft YaHei", 10)).grid(
            row=12, column=0, sticky="w", **pad)
        vol_var = tk.StringVar(value=str(int(getattr(self, "voice_volume", 80))))
        tk.Spinbox(win, from_=0, to=100, increment=10, width=6,
                   textvariable=vol_var, font=("Consolas", 10)).grid(
            row=12, column=1, sticky="e", **pad)

        def _on_preview_voice():
            pack = pack_var.get()
            if pack == NO_PACK:
                pack = ""
            f = find_voice_file(pack, "greet")
            if f:
                try:
                    self.voice.play(f, int(vol_var.get()))
                except Exception:
                    pass
            else:
                from tkinter import messagebox
                messagebox.showinfo(APP_NAME, "该语音包里没有 greet 语音文件哦～\n"
                                              "可点击\"打开语音包目录\"查看说明。",
                                    parent=win)

        def _on_open_voice_dir():
            try:
                import os as _os
                root_dir = voice_pack_dirs()[1]
                demo = root_dir / "我的语音包"
                demo.mkdir(parents=True, exist_ok=True)
                readme = root_dir / "README.txt"
                if not readme.exists():
                    readme.write_text(VOICE_README, encoding="utf-8")
                _os.startfile(str(root_dir))
            except Exception as e:
                from tkinter import messagebox
                messagebox.showerror(APP_NAME, f"打开目录失败：{e}", parent=win)

        voice_btns = tk.Frame(win, bg="#F5F5F7")
        voice_btns.grid(row=13, column=0, columnspan=2, sticky="w", **pad)
        tk.Button(voice_btns, text="🔊 试听", font=("Microsoft YaHei", 9),
                  command=_on_preview_voice).pack(side="left", padx=(0, 8))
        tk.Button(voice_btns, text="📂 打开语音包目录（可自制语音包）",
                  font=("Microsoft YaHei", 9),
                  command=_on_open_voice_dir).pack(side="left")

        replay_var = tk.BooleanVar(value=not st.get("hatched", False))
        tk.Checkbutton(win, text="下次启动时播放破壳孵化动画（首次启动已自动播放）",
                       variable=replay_var, bg="#F5F5F7", fg="#333333",
                       font=("Microsoft YaHei", 10)).grid(
            row=14, column=0, columnspan=2, sticky="w", **pad)

        tk.Button(win, text="ℹ️ 关于", font=("Microsoft YaHei", 9),
                  command=lambda: self._show_about(win)).grid(
            row=15, column=0, columnspan=2, pady=(6, 0))

        def on_save():
            try:
                new_scale = max(0.5, min(2.0, float(scale_var.get())))
            except ValueError:
                new_scale = 1.0
            try:
                new_reminder = max(5, min(600, int(reminder_var.get())))
            except ValueError:
                new_reminder = cur_reminder
            try:
                new_vol = max(0, min(100, int(vol_var.get())))
            except ValueError:
                new_vol = 80
            inv = {v: k for k, v in preset_names.items()}
            new_behavior = inv.get(behavior_var.get(), "playful")

            new_follow = bool(follow_var.get())
            new_watch = bool(watch_var.get())
            if new_follow and new_watch:
                new_follow = False
            self.follow_mode = new_follow
            self.watch_mode = new_watch
            if not self.watch_mode:
                self.current_gaze = None
            if new_behavior == "off":
                self.random_engine.enabled = False
            else:
                self.random_engine.enabled = True
                self.random_engine.set_preset(new_behavior)

            self.mood_auto = bool(mood_var.get())
            if not self.mood_auto:
                self._mood = "neutral"
                if "idle" in self.frames:
                    self._switch_anim("idle", force=True)
                log.info("情绪联动关闭")

            self.wink_auto = bool(wink_var.get())
            self.reminder_s = new_reminder

            self.voice_enabled = bool(voice_var.get())
            new_pack = pack_var.get()
            self.voice_pack = "" if new_pack == NO_PACK else new_pack
            self.voice_volume = new_vol
            if not self.voice_enabled:
                self.voice.stop()

            try:
                set_autorun(bool(auto_var.get()))
            except Exception as e:
                from tkinter import messagebox
                messagebox.showerror(APP_NAME, f"设置开机启动失败：{e}", parent=win)

            old_scale = st["scale"]
            inv_edge = {v: k for k, v in edge_names.items()}
            new_edge = inv_edge.get(edge_var.get(), "soft")
            merged = load_settings()
            merged.update({"scale": new_scale, "behavior": new_behavior,
                           "autostart": bool(auto_var.get()),
                           "mood_auto": self.mood_auto,
                           "wink_auto": self.wink_auto,
                           "edge_mode": new_edge,
                           "hatched": not bool(replay_var.get()),
                           "reminder_s": new_reminder,
                           "voice_enabled": self.voice_enabled,
                           "voice_pack": self.voice_pack,
                           "voice_volume": new_vol})
            save_settings(merged)
            win.destroy()

            need_restart = abs(new_scale - old_scale) > 1e-6 or new_edge != self.edge_mode
            if need_restart:
                from tkinter import messagebox
                msg = []
                if abs(new_scale - old_scale) > 1e-6:
                    msg.append("缩放")
                if new_edge != self.edge_mode:
                    msg.append("边缘处理")
                if messagebox.askyesno(
                        APP_NAME,
                        f"{'、'.join(msg)}已修改，需要重启宠物才能生效。\n现在重启吗？"):
                    restart()

        def on_cancel():
            win.destroy()

        btn_frame = tk.Frame(win, bg="#F5F5F7")
        btn_frame.grid(row=16, column=0, columnspan=2, pady=(10, 14))
        tk.Button(btn_frame, text="保存", width=8, command=on_save).pack(
            side="left", padx=6)
        tk.Button(btn_frame, text="取消", width=8, command=on_cancel).pack(
            side="left", padx=6)

    def _show_about(self, parent=None):
        from tkinter import messagebox
        messagebox.showinfo(
            f"关于 {APP_NAME}",
            f"{APP_NAME}  v{APP_VERSION}\n\n{APP_CREDIT}\n\n"
            f"一朵会看你的心情、会自然眨眼、会举臂打招呼的小裙裙 🌸\n"
            f"电脑负载低时捧花开心，负载高时抱臂生气，失败时叹口气。\n"
            f"支持自定义语音包（设置 → 打开语音包目录）。\n"
            f"提醒时间可在设置中自定义哦～",
            parent=parent)

def restart():
    python = sys.executable
    os.execv(python, [f'"{python}"'] + sys.argv[1:])

def main():
    st = load_settings()
    hatch = not st.get("hatched", False)

    if st.get("autostart") and getattr(sys, "frozen", False):
        try:
            set_autorun(True)
        except Exception:
            pass

    res = resource_dir()
    pet = QPetApp(
        spritesheet_path=str(res / "spritesheet.png"),
        config_path=str(res / "pet.json"),
        random_preset=st.get("behavior", "playful") if st.get("behavior") != "off" else "playful",
        scale=float(st.get("scale", 1.0)),
        mood_auto=bool(st.get("mood_auto", True)),
        wink_auto=bool(st.get("wink_auto", True)),
        edge_mode=str(st.get("edge_mode", "soft")),
        hatch=hatch,
        reminder_s=int(st.get("reminder_s", DEFAULT_REMINDER_S)),
        voice_enabled=bool(st.get("voice_enabled", True)),
        voice_pack=str(st.get("voice_pack", "")),
        voice_volume=int(st.get("voice_volume", 80)),
    )
    if hatch:

        st["hatched"] = True
        save_settings(st)
    if st.get("behavior") == "off":
        pet.random_engine.enabled = False
    pet.run()

if __name__ == "__main__":
    main()
