import ctypes
import json
import logging
import math
import os
import random
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from hatch_pet import desktop_renderer as dr
from hatch_pet import glass_ui
from hatch_pet import music_dance
from hatch_pet import pixel_ui
from hatch_pet.desktop_renderer import DesktopPet

import voice_interact as vi

APP_NAME = "Vivian 桌面宠物"
APP_VERSION = "1.0.9"
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
        if _MacCpuSampler._sysctl_ok is not False:
            try:
                ticks = self._read_ticks_sysctl()
                _MacCpuSampler._sysctl_ok = True
                return ticks
            except Exception:
                _MacCpuSampler._sysctl_ok = False
        return self._read_ticks_mach()

    _sysctl_ok: Optional[bool] = None

    @staticmethod
    def _read_ticks_sysctl() -> tuple[int, int]:
        # 旧版 macOS 才有 kern.cp_time；新版（Sequoia 等）已移除该 OID。
        out = subprocess.check_output(
            ["sysctl", "-n", "kern.cp_time"],
            stderr=subprocess.DEVNULL, text=True).split()
        u, n, s, idle, intr = (int(v) for v in out[:5])
        busy = u + n + s + intr
        return busy, busy + idle

    @staticmethod
    def _read_ticks_mach() -> tuple[int, int]:
        # Mach host_processor_info：psutil 同款实现，全 macOS 版本可用。
        import ctypes
        import ctypes.util
        libc = ctypes.CDLL(ctypes.util.find_library("c"))
        libc.mach_host_self.restype = ctypes.c_uint
        libc.mach_task_self.restype = ctypes.c_uint
        libc.host_processor_info.restype = ctypes.c_int
        libc.host_processor_info.argtypes = [
            ctypes.c_uint, ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_uint)),
            ctypes.POINTER(ctypes.c_uint),
        ]
        libc.vm_deallocate.restype = ctypes.c_int
        libc.vm_deallocate.argtypes = [
            ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
        ]

        PROCESSOR_CPU_LOAD_INFO = 2
        count = ctypes.c_uint(0)
        info = ctypes.POINTER(ctypes.c_uint)()
        info_cnt = ctypes.c_uint(0)
        kr = libc.host_processor_info(
            libc.mach_host_self(), PROCESSOR_CPU_LOAD_INFO,
            ctypes.byref(count), ctypes.byref(info), ctypes.byref(info_cnt))
        if kr != 0:
            raise OSError("host_processor_info kern_return=%d" % kr)
        try:
            # 每核 4 个 natural_t：user, system, idle, nice
            busy = total = 0
            stride = 4
            for i in range(count.value):
                base = i * stride
                user = info[base]
                system = info[base + 1]
                idle = info[base + 2]
                nice = info[base + 3]
                busy += user + system + nice
                total += user + system + idle + nice
            if total <= 0:
                raise OSError("host_processor_info 返回空数据")
            return busy, total
        finally:
            libc.vm_deallocate(
                libc.mach_task_self(), ctypes.cast(info, ctypes.c_uint).value,
                count.value * stride * ctypes.sizeof(ctypes.c_uint))

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
               "voice_enabled": True, "voice_pack": "甜嗓默认", "voice_volume": 80,
               "music_dance": {"enabled": False}}
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
                 voice_volume: int = 80, voice_cfg: dict = None,
                 music_cfg: dict = None, **kwargs):
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

        self.voice_cfg = dict(voice_cfg or {})
        self.voice_service = None
        self._cal_hint_shown = False
        self._install_callback_hook()
        if self.voice_cfg.get("enabled", True):
            self.root.after(800, self._start_voice_service)
        self._mood = "neutral"
        self._cpu_ema = None
        self._mood_hold_until = 0.0
        self._cpu_sampler = CpuSampler()

        self._wink_active = False
        self._wink_until = 0.0
        self._last_interaction = time.time()

        # —— 音乐跳舞（默认关闭，设置面板开启；检测需常驻回环音频流）——
        self._dance_cfg = dict(music_cfg or {})
        self.music_detector = None
        self._dance_active = False
        self._dance_paused = False
        self._beat_count = 0
        self._dance_switch_after = 4
        self._pending_resume = None
        self.canvas.bind("<Enter>", self._on_pet_hover_enter)
        self.canvas.bind("<Leave>", self._on_pet_hover_leave)
        if self._dance_cfg.get("enabled", False):
            self.root.after(2000, self._start_music_dance)

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

        # 合成舞蹈动画（依赖 _pil_cell/_frame_to_tk，需在 _sheet_img 初始化后）
        self._synthesize_dance_anims()

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

    def _install_callback_hook(self):
        def _cb(exc, val, tb):
            try:
                import traceback
                log.error("Tk 回调异常:\n%s",
                          "".join(traceback.format_exception(exc, val, tb)))
            except Exception:
                pass
        try:
            self.root.report_callback_exception = _cb
        except Exception:
            pass

    def _play_voice(self, event: str):
        try:
            if not self.voice_enabled or not self.voice_pack:
                return
            f = find_voice_file(self.voice_pack, event)
            if f:
                self.voice.play(f, self.voice_volume)
        except Exception as e:
            log.exception("语音播放失败: %s", e)

    def _start_voice_service(self):
        if getattr(self, "_closing", False):
            return
        try:
            api = vi.ModelAPIClient(
                endpoint=str(self.voice_cfg.get("api_endpoint", "") or ""),
                api_key=str(self.voice_cfg.get("api_key", "") or ""),
                model=str(self.voice_cfg.get("api_model", "") or ""),
                stt_model=str(self.voice_cfg.get("api_stt_model", "") or ""))
            svc = vi.VoiceService(
                post_fn=self._post_to_main,
                on_wake=self._on_voice_wake,
                on_reply=self._on_voice_reply,
                api=api,
                cooldown_s=float(self.voice_cfg.get("cooldown_sec", 10)),
                log_fn=lambda m: log.info("[voice] %s", m),
                on_status=self._on_voice_status,
                on_cal=self._on_voice_cal)
            self.voice_service = svc
            if svc.start():
                log.info("语音服务启动中（后台检测麦克风，engine=%s）", svc.engine_name)
            else:
                log.info("语音交互未启动")
        except Exception as e:
            log.exception("语音交互初始化失败: %s", e)

    def _on_voice_status(self, stage, msg):
        if getattr(self, "_closing", False):
            return
        if stage == "fail":
            log.info("语音交互不可用: %s", msg)
            self._show_bubble("麦克风不可用：%s（可稍后托盘-重新检测麦克风）" % msg, "")

    def _on_voice_cal(self, ev):
        if getattr(self, "_closing", False):
            return
        kind = ev[0]
        if kind == "ask":
            self._show_bubble("🎙️ 请对着麦克风说「Hi, Vivian」（第 %d/%d 遍）"
                              % (ev[1], ev[2]), "")
        elif kind == "fail":
            self._show_bubble("校准失败：%s" % ev[1], "")
        elif kind == "done":
            self._show_bubble("校准完成！以后我只听「Hi, Vivian」啦 🌸", "waving")
            self._play_voice("happy")

    def _voice_running(self) -> bool:
        svc = getattr(self, "voice_service", None)
        return bool(svc and svc.running)

    def _on_voice_wake(self):
        if getattr(self, "_closing", False):
            return
        msg = vi.pick_response()
        log.info("语音唤醒 -> %s", msg)
        self._mark_interaction()
        if "waving" in self.frames:
            self._skip_wave_voice = True
            self._switch_anim("waving", force=True)
        self._show_bubble(msg, "waving")
        self._play_voice(random.choice(["greet", "happy", "wave"]))
        svc = getattr(self, "voice_service", None)
        if svc is not None and svc.engine_name == "vivian-rhythm" \
                and not self._cal_hint_shown:
            self._cal_hint_shown = True
            self.root.after(4200, lambda: self._show_bubble(
                "小提示：托盘右键 → 校准唤醒词，我就能只听「Hi, Vivian」啦", ""))

    def _on_voice_reply(self, text):
        if getattr(self, "_closing", False):
            return
        log.info("语音对话回复: %s", text)
        self._mark_interaction()
        self._show_bubble(text, "")
        self._play_voice(random.choice(["happy", "wave", "neutral"]))

    def _extra_tray_items(self):
        try:
            import pystray
            return [
                pystray.MenuItem("语音交互", self._toggle_voice_tray,
                                 checked=lambda item: self._voice_running()),
                pystray.MenuItem("校准唤醒词（Hi, Vivian）", self._calibrate_tray),
                pystray.MenuItem("重新检测麦克风", self._recheck_mic_tray),
            ]
        except Exception:
            return []

    def _calibrate_tray(self, icon=None, item=None):
        self._post_to_main(self._do_calibrate)

    def _do_calibrate(self):
        if getattr(self, "_closing", False):
            return
        svc = getattr(self, "voice_service", None)
        if svc is None or not svc.running:
            if svc is None:
                self._start_voice_service()
                svc = self.voice_service
            if svc is None or not svc.running:
                self._show_bubble("麦克风不可用，无法校准", "")
                return
        if not svc.calibratable:
            self._show_bubble("当前使用唤醒词模型（openWakeWord），无需校准", "")
            return
        if not svc.calibrate(3):
            self._show_bubble("无法进入校准，请稍后再试", "")

    def _toggle_voice_tray(self, icon=None, item=None):
        self._post_to_main(self._do_toggle_voice)

    def _do_toggle_voice(self):
        st = load_settings()
        vc = dict(st.get("voice_interact", {}))
        if self._voice_running():
            self.voice_service.stop()
            vc["enabled"] = False
            self._show_bubble("耳朵闭上啦～想我时再叫我哦", "")
            log.info("语音交互已关闭")
        else:
            self.voice_cfg = vc
            if self.voice_service is None or not self.voice_service.running:
                self._start_voice_service()
            if self._voice_running():
                vc["enabled"] = True
                self._show_bubble("耳朵打开啦～听到你说「Hi, Vivian」我就应答！", "")
            else:
                vc["enabled"] = False
                self._show_bubble("语音服务启动失败（检查系统麦克风/隐私设置）", "")
        st["voice_interact"] = vc
        save_settings(st)

    def _recheck_mic_tray(self, icon=None, item=None):
        self._post_to_main(self._do_recheck_mic)

    def _do_recheck_mic(self):
        ok, name = vi.detect_microphone()
        if ok and vi.probe_capture():
            self._show_bubble(f"麦克风正常：{name}", "")
        else:
            self._show_bubble(f"麦克风不可用：{name}", "")

    # ---------- 音乐跳舞 ----------
    # 动作池：4 组程序化合成动画 + 原生跳跃/挥手；起舞与每次换步随机抽取
    _DANCE_ANIMS = ("dance-sway", "dance-bounce", "dance-twist",
                    "dance-spin", "jumping", "waving")
    _DANCE_SOURCES = {"dance-sway": "idle", "dance-bounce": "idle-plain",
                      "dance-twist": "waving", "dance-spin": "running-right"}
    _DANCE_FPS = {"dance-sway": 12, "dance-bounce": 12,
                  "dance-twist": 12, "dance-spin": 14}
    _DANCE_LABELS = {"dance-sway": "摇摆", "dance-bounce": "弹跳",
                     "dance-twist": "扭动", "dance-spin": "旋转"}
    _DANCE_START_MSG = "🎵 有音乐！一起跳舞吧～"

    def _synthesize_dance_anims(self):
        """程序化合成舞蹈动画：24 帧/组、12~14fps，流畅循环；
        并入动作池与左键动画菜单（可手动触发）。失败则只保留原生动作。"""
        added = []
        for name, source in self._DANCE_SOURCES.items():
            try:
                if source not in self.frames:
                    continue
                pil_frames = self._make_dance_frames(name, source, 24)
                if not pil_frames:
                    continue
                self.frames[name] = [self._frame_to_tk(f) for f in pil_frames]
                self.config.setdefault("animations", []).append({
                    "name": name, "row": -1, "frameCount": len(pil_frames),
                    "fps": self._DANCE_FPS.get(name, 12),
                    "label": self._DANCE_LABELS.get(name, name)})
                added.append(name)
            except Exception as e:
                log.exception("合成跳舞动画失败 %s: %s", name, e)
        if added:
            log.info("跳舞动画已合成: %s", ", ".join(added))

    def _make_dance_frames(self, kind, source, count):
        frames = []
        src_len = max(1, len(self.frames.get(source, [])))
        for i in range(count):
            cell = self._pil_cell(source, i % src_len)
            if cell is None:
                return []
            frames.append(self._dance_transform(kind, cell.copy(), i, count))
        return frames

    def _dance_transform(self, kind, img, i, n):
        W, H = img.size
        canvas = dr.Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if kind == "dance-sway":
            # 摇摆：绕脚部 ±8° 摆动 + 轻微起伏
            ang = 8.0 * math.sin(2 * math.pi * i / n)
            dy = int(3 * math.sin(4 * math.pi * i / n))
            rot = self._scale_img(
                img.rotate(ang, resample=dr.Image.BICUBIC, expand=True), 0.96)
            canvas.alpha_composite(rot, ((W - rot.width) // 2,
                                         H - rot.height + dy))
        elif kind == "dance-bounce":
            # 弹跳：每循环 2 次跳跃，落地压扁 / 腾空拉长（squash & stretch）
            k = abs(math.sin(math.pi * i / 12))
            dy = int(H * 0.10 * k)
            sx = 1.0 + 0.05 * (1 - k) - 0.02 * k
            sy = 1.0 - 0.06 * (1 - k) + 0.04 * k
            img = self._scale_img(img, sx, sy)
            canvas.alpha_composite(img, ((W - img.width) // 2,
                                         H - img.height - dy))
        elif kind == "dance-twist":
            # 扭动：双倍频 ±10° 扭转 + 左右顶胯位移
            ph = 4 * math.pi * i / n
            ang = 10.0 * math.sin(ph)
            dx = int(W * 0.03 * math.sin(ph + math.pi / 2))
            rot = self._scale_img(
                img.rotate(ang, resample=dr.Image.BICUBIC, expand=True), 0.94)
            canvas.alpha_composite(rot, ((W - rot.width) // 2 + dx,
                                         H - rot.height))
        else:  # dance-spin
            # 旋转：每循环一整圈，绕身体中心
            rot = self._scale_img(
                img.rotate(360.0 * i / n, resample=dr.Image.BICUBIC,
                           expand=True), 0.78)
            canvas.alpha_composite(rot, ((W - rot.width) // 2,
                                         (H - rot.height) // 2))
        return canvas

    @staticmethod
    def _scale_img(img, kx, ky=None):
        ky = ky if ky is not None else kx
        return img.resize((max(1, int(img.width * kx)),
                           max(1, int(img.height * ky))), dr.Image.LANCZOS)
    _DANCE_HOVER_MSG = "音乐不停，跳舞不停！把鼠标移开我就继续跳～"

    def _start_music_dance(self, notify_fail: bool = False):
        """开启系统音乐监听（常驻回环音频流，设置面板可关闭）"""
        if self.music_detector is not None or self._closing:
            return
        ok, why = music_dance.MusicDetector.supported()
        if not ok:
            self._dance_cfg["enabled"] = False
            log.info("音乐跳舞不可用: %s", why)
            if notify_fail:
                self._show_bubble("音乐跳舞开不了啦：%s" % why, "")
            return
        det = music_dance.MusicDetector(
            on_beat=lambda: self._post_to_main(self._on_music_beat),
            on_music=lambda: self._post_to_main(self._on_music_start),
            on_quiet=lambda: self._post_to_main(self._on_music_stop),
            log_fn=lambda m: log.info("%s", m))
        if not det.start():
            self.music_detector = None
            if notify_fail:
                self._show_bubble("音乐监听启动失败：%s" % det.last_error, "")
            return
        self.music_detector = det

    def _stop_music_dance(self):
        det = self.music_detector
        self.music_detector = None
        if det is not None:
            det.stop()
        self._cancel_dance_resume()
        if self._dance_active:
            self._dance_active = False
            self._dance_paused = False
            if load_settings().get("behavior", "playful") != "off":
                self.random_engine.enabled = True
            anim = self._MOOD_ANIM.get(self._mood, "idle")
            if anim in self.frames:
                self._switch_anim(anim, force=True)
        log.info("音乐跳舞已关闭")

    def _on_music_start(self):
        if self._closing or self._dance_active or self._hatch_active:
            return
        self._dance_active = True
        self._dance_paused = False
        self._beat_count = 0
        self._dance_switch_after = random.randint(4, 8)
        self.random_engine.enabled = False
        self._dance_step()
        self._show_bubble(self._DANCE_START_MSG, "")
        self._play_voice("happy")
        log.info("音乐跳舞开始")

    def _on_music_beat(self):
        if not self._dance_active or self._dance_paused or self.dragging:
            return
        if getattr(self, "_radial_panel", None) and self._radial_panel.alive():
            return
        if getattr(self, "_left_menu_panel", None) and self._left_menu_panel.alive():
            return
        self._beat_count += 1
        if self._beat_count >= self._dance_switch_after:
            self._dance_step()

    def _dance_step(self):
        """随机切换到动作池里的另一个舞蹈动作（每次随机，跳过当前动作）"""
        pool = [a for a in self._DANCE_ANIMS
                if a in self.frames and a != self.current_anim]
        if not pool:
            return
        anim = random.choice(pool)
        self._beat_count = 0
        self._dance_switch_after = random.randint(4, 8)
        if anim == "waving":
            self._skip_wave_voice = True
        self._switch_anim(anim, force=True)
        log.info("舞蹈换步 -> %s（%d 拍后换）", anim, self._dance_switch_after)

    def _on_music_stop(self):
        if not self._dance_active:
            return
        self._cancel_dance_resume()
        self._dance_active = False
        self._dance_paused = False
        if load_settings().get("behavior", "playful") != "off":
            self.random_engine.enabled = True
        anim = self._MOOD_ANIM.get(self._mood, "idle")
        if anim in self.frames:
            self._switch_anim(anim, force=True)
        self._show_bubble("音乐结束啦～休息一下 🌼", "")
        log.info("音乐跳舞结束")

    def _on_pet_hover_enter(self, event=None):
        self._cancel_dance_resume()
        if self._dance_active and not self._dance_paused and not self.dragging:
            self._dance_paused = True
            anim = "waiting" if "waiting" in self.frames else "idle"
            if anim in self.frames:
                self._switch_anim(anim, force=True)
            log.info("跳舞暂停（鼠标悬停在宠物上）")

    def _on_pet_hover_leave(self, event=None):
        if self._dance_active and self._dance_paused and not self.dragging:
            # 短防抖：跳舞动画帧变化时指针可能瞬间落在透明区域
            self._pending_resume = self.root.after(200, self._resume_dance)

    def _resume_dance(self):
        self._pending_resume = None
        if self._closing or not self._dance_active or not self._dance_paused:
            return
        self._dance_paused = False
        self._dance_step()
        log.info("跳舞继续（鼠标已移开）")

    def _cancel_dance_resume(self):
        if self._pending_resume is not None:
            try:
                self.root.after_cancel(self._pending_resume)
            except Exception:
                pass
            self._pending_resume = None


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
        if dr.PLATFORM != "windows":
            # macOS/Linux：真 alpha 交给渲染层合成。去紫边阈值化是
            # Windows -transparentcolor 色键方案的伴生步骤（半透明紫边
            # 会被键成洋红光晕），真 alpha 下反而会毁掉软边。
            if frame.mode != "RGBA":
                frame = frame.convert("RGBA")
            return dr.macos_overlay.make_source_photo(
                frame, keep_source=dr.IS_MACOS)
        threshold = EDGE_MODES.get(self.edge_mode, 118)
        r, g, b, a = frame.split()
        if threshold is None:
            composite = PILImage.merge("RGB", (r, g, b))
        else:
            mask = a.point(lambda v: 255 if v >= threshold else 0)
            magenta_bg = PILImage.new("RGB", frame.size, (255, 0, 255))
            rgb = PILImage.merge("RGB", (r, g, b))
            composite = PILImage.composite(rgb, magenta_bg, mask)
        return dr.macos_overlay.make_source_photo(composite, keep_source=False)

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
            svc = getattr(self, "voice_service", None)
            if svc is not None:
                svc.stop()
        except Exception:
            pass
        try:
            det = getattr(self, "music_detector", None)
            if det is not None:
                det.stop(join_s=1.0)
        except Exception:
            pass
        try:
            self.voice.stop()
        except Exception:
            pass
        super()._quit()

    # ---------- 形象更换 ----------
    def _apply_appearance(self, sheet_path, config_path):
        """热重载新形象：换精灵图与动画配置，无需重启。

        若正在跳舞则先停下，重载完成后恢复跳舞。"""
        was_dancing = self._dance_active
        if was_dancing:
            self._cancel_dance_resume()
            self._dance_active = False
            self._dance_paused = False

        self.config = self._load_config(config_path)
        self.frames, self.gaze_frames = self._load_spritesheet(sheet_path)
        self._sheet_img = None
        self._cell_cache.clear()
        self._gaze_skin = None
        try:
            sheet = dr.Image.open(sheet_path).convert("RGBA")
            cell = self.config.get("sprite", {}).get("cell", {})
            cw = cell.get("width", dr.CELL_WIDTH)
            ch = cell.get("height", dr.CELL_HEIGHT)
            self._gaze_base_img = sheet.crop((0, 9 * ch, cw, 9 * ch + ch))
            if self.scale != 1.0:
                self._gaze_base_img = self._gaze_base_img.resize(
                    (self.win_w, self.win_h), dr.Image.LANCZOS)
        except Exception:
            self._gaze_base_img = None

        self.current_anim = "idle"
        self.current_frame = 0
        self.anim_counter = 0
        self._synthesize_dance_anims()
        self._switch_anim("idle", force=True)
        if was_dancing:
            self._on_music_start()
        log.info("形象已切换: %s", sheet_path)

    def _post_to_main(self, fn):
        """线程安全地把 fn 投递到主线程执行（供后台线程/向导使用）。"""
        try:
            self.root.after_idle(fn)
        except RuntimeError:
            pass  # 主循环已退出

    def _open_appearance_wizard(self):
        try:
            from hatch_pet.appearance_wizard import AppearanceWizard
            AppearanceWizard(self)
        except Exception as e:
            log.exception("打开更换形象向导失败: %s", e)
            self._show_bubble("向导开不了啦：%s" % str(e)[:60], "")

    def _restore_default_appearance(self):
        import shutil
        try:
            from hatch_pet.appearance_wizard import appearance_dir
            shutil.rmtree(appearance_dir(), ignore_errors=True)
        except Exception:
            pass
        res = resource_dir()
        self._apply_appearance(str(res / "spritesheet.png"),
                               str(res / "pet.json"))
        self._show_bubble("换回默认形象啦～ 🌼", "greet")

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
        if not self.wink_auto or self.dragging or self._dance_active:
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
        if self._dance_active or not self.mood_auto or self.dragging \
                or self._wink_active:
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

    def _on_menu_open(self):
        # 右键菜单打开视为一次交互（暂停 wink / 情绪联动片刻）
        self._mark_interaction()
        self._mood_hold_until = time.time() + MOOD_HOLD_AFTER_MANUAL_S

    def _on_right_click(self, event):
        if self._hatch_active:
            return
        super()._on_right_click(event)

    def _menu_items(self):
        """在基础扇形菜单上插入「设置」项（Apple 风格图标 key）。"""
        items = super()._menu_items()
        return items[:3] + [("settings", "设置", self._open_settings)] + items[3:]

    def _open_settings(self):
        tk = dr.tk
        self._close_radial()
        st = load_settings()

        win = tk.Toplevel(self.root)
        win.title(f"{APP_NAME} - 设置")
        win.attributes("-topmost", True)
        win.withdraw()

        BG = pixel_ui.BLACK_BG
        CARD = pixel_ui.BLACK_CARD
        BORDER = pixel_ui.BLACK_LINE
        ACCENT = pixel_ui.GREEN
        GREEN = pixel_ui.GREEN
        YELLOW = pixel_ui.YELLOW
        BLUE = pixel_ui.BLUE
        TEXT = pixel_ui.TEXT
        SUB = pixel_ui.SUB
        MINT = pixel_ui.MINT
        F = ("Microsoft YaHei", 10)
        FS = ("Microsoft YaHei", 9)

        try:
            from tkinter import ttk as _ttk
            _stl = _ttk.Style(win)
            _stl.theme_use("clam")
            _stl.configure("TCombobox", fieldbackground="#0B1016",
                           background="#111820", foreground=MINT,
                           arrowcolor=GREEN, bordercolor=BLACK_LINE,
                           lightcolor="#0B1016", darkcolor="#0B1016")
            _stl.map("TCombobox",
                     fieldbackground=[("readonly", "#0B1016")],
                     foreground=[("readonly", MINT)])
            _stl.configure("Vertical.TScrollbar", background="#111820",
                           troughcolor=BG, arrowcolor=GREEN,
                           bordercolor=BG, lightcolor="#111820",
                           darkcolor="#111820")
        except Exception:
            pass

        CW = 460                      # 画布（内容区）宽度
        SBW = 18                      # 滚动条宽度
        FTR_H = 52                    # 底部按钮条高度（始终可见）

        footer = tk.Frame(win, bg="#0F1724", highlightbackground=BORDER,
                          highlightthickness=1)
        footer.pack(side="bottom", fill="x")

        canvas = tk.Canvas(win, bg=BG, highlightthickness=0, width=CW)
        vsb = tk.Scrollbar(win, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # —— 像素风布局：主标题带像素 logo，卡片霓虹边框 + 分区 logo ——
        self._pixel_logos = []        # PhotoImage 引用挂实例，防 GC 变空白
        self._pixel_cb_vars = {}      # 勾选框文字 -> BooleanVar（测试/状态读取）
        _logo_jobs = []               # (logo标签, 图标名) —— 映射后安装
        _title_id = canvas.create_text(CW // 2, 38, text="⚙ 设 置",
                                       font=("Microsoft YaHei", 17, "bold"),
                                       fill=pixel_ui.GREEN)
        _sub_id = canvas.create_text(CW // 2, 66, text="点击 ❕ 查看对应项的说明",
                                     font=FS, fill=YELLOW)

        _cards = []                   # [(window_item, widget), ...]

        def _relayout(_e=None):
            cw = max(CW, canvas.winfo_width())
            y = 92
            for item, wdg in _cards:
                canvas.coords(item, 16, y)
                canvas.itemconfig(item, width=cw - 32)
                y += max(1, wdg.winfo_reqheight()) + 12
            y += 16
            canvas.coords(_title_id, cw // 2, 38)
            canvas.coords(_sub_id, cw // 2, 66)
            canvas.configure(scrollregion=(0, 0, cw, y))

        def _add_card(wdg):
            item = canvas.create_window((16, 0), anchor="nw", window=wdg,
                                        width=CW - 32)
            _cards.append((item, wdg))
            wdg.bind("<Configure>", _relayout)
            return wdg

        def _add_btn(wdg, side):
            wdg.pack(side=side, pady=8, padx=12 if side == "left" else 0)
            return wdg

        def _on_wheel(e):
            try:
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            except Exception:
                pass

        win.bind_all("<MouseWheel>", _on_wheel, add="+")

        def _unbind_wheel():
            try:
                win.unbind_all("<MouseWheel>")
            except Exception:
                pass

        def _close_hint(top):
            try:
                top.destroy()
            except Exception:
                pass

        def _hint_popup(anchor, text):
            top = tk.Toplevel(win)
            top.overrideredirect(True)
            top.attributes("-topmost", True)
            frm = tk.Frame(top, bg="#111820", highlightbackground=YELLOW,
                           highlightthickness=2)
            frm.pack(fill="both", expand=True)
            tk.Label(frm, text="❕ 提示", bg="#111820", fg=YELLOW,
                     font=("Microsoft YaHei", 10, "bold")).pack(
                anchor="w", padx=12, pady=(8, 2))
            tk.Label(frm, text=text, bg="#111820", fg="#C9D6E3",
                     font=FS, wraplength=300, justify="left").pack(
                anchor="w", padx=12, pady=(0, 10))
            try:
                anchor.update_idletasks()
                top.update_idletasks()
                ax, ay = anchor.winfo_rootx(), anchor.winfo_rooty()
                ah = anchor.winfo_height()
                tw, th = top.winfo_reqwidth(), top.winfo_reqheight()
                sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
                x = min(max(8, ax - tw // 2), max(8, sw - tw - 8))
                y = ay + ah + 6
                if y + th > sh - 8:
                    y = max(8, ay - th - 6)
                top.geometry(f"+{x}+{y}")
            except Exception:
                pass
            top.bind("<Button-1>", lambda e: _close_hint(top))
            top.after(8000, lambda: _close_hint(top))

        def _badge(parent, tip):
            lbl = tk.Label(parent, text="❕", bg=CARD, fg=YELLOW,
                           font=("Segoe UI Symbol", 12, "bold"), cursor="hand2")
            lbl.bind("<Enter>", lambda e: lbl.config(fg="#FFE94A"))
            lbl.bind("<Leave>", lambda e: lbl.config(fg=YELLOW))
            lbl.bind("<Button-1>", lambda e: _hint_popup(lbl, tip))
            return lbl

        def _card(title, icon_key, accent):
            """像素风卡片：2px 霓虹边框 + 像素 logo 标题"""
            outer = tk.Frame(canvas, bg=CARD, highlightbackground=accent,
                             highlightthickness=2)
            head = tk.Frame(outer, bg=CARD)
            head.pack(anchor="w", padx=12, pady=(10, 2))
            logo_lbl = tk.Label(head, bg=CARD)
            logo_lbl.pack(side="left")

            def _set_logo(h=head, k=icon_key, lb=logo_lbl):
                photo = pixel_ui.icon_photo(lb, k, scale=3)
                self._pixel_logos.append(photo)
                lb.config(image=photo)
                lb.image = photo
            _logo_jobs.append(_set_logo)
            tk.Label(head, text=title, bg=CARD, fg=accent,
                     font=("Microsoft YaHei", 11, "bold")).pack(
                side="left", padx=(8, 0))
            inner = tk.Frame(outer, bg=CARD)
            inner.pack(fill="x", padx=14, pady=(0, 10))
            inner.grid_columnconfigure(0, weight=1)
            _add_card(outer)
            return inner

        def _label_row(parent, r, label, tip=None):
            frm = tk.Frame(parent, bg=CARD)
            frm.grid(row=r, column=0, sticky="w", pady=3)
            tk.Label(frm, text=label, bg=CARD, fg=TEXT, font=F).pack(side="left")
            if tip:
                _badge(frm, tip).pack(side="left", padx=(5, 0))
            return frm

        def _check(parent, r, text, var, tip=None):
            """自绘像素勾选框：点击直接写变量并重绘像素图标，
            视觉状态与变量严格同步（不依赖平台指示器）。"""
            frm = tk.Frame(parent, bg=CARD)
            frm.grid(row=r, column=0, columnspan=2, sticky="w", pady=3)
            box = tk.Label(frm, bg=CARD, cursor="hand2")
            lbl = tk.Label(frm, text=text, bg=CARD, fg=TEXT, font=F,
                           cursor="hand2")
            box.pack(side="left")
            lbl.pack(side="left", padx=(6, 0))
            self._pixel_cb_vars[text] = var

            def _render():
                photo = pixel_ui.checkbox_photo(box, bool(var.get()))
                box.config(image=photo)
                box.image = photo          # 挂在控件上防 GC
                lbl.config(fg=pixel_ui.GREEN if var.get() else TEXT)

            def _toggle(_e=None):
                var.set(not bool(var.get()))
                _render()

            box.bind("<Button-1>", _toggle)
            lbl.bind("<Button-1>", _toggle)
            _logo_jobs.append(_render)     # 窗口映射后首次渲染
            if tip:
                _badge(frm, tip).pack(side="left", padx=(5, 0))
            return var

        def _combo(parent, r, var, values, width=14):
            try:
                from tkinter import ttk
                cb = ttk.Combobox(parent, textvariable=var, state="readonly",
                                  values=values, width=width)
            except Exception:
                cb = tk.Entry(parent, textvariable=var, width=width + 2)
            cb.grid(row=r, column=1, sticky="e", pady=3)
            return cb

        def _spin(parent, r, var, lo, hi, step):
            sb = tk.Spinbox(parent, from_=lo, to=hi, increment=step, width=6,
                            textvariable=var, font=("Consolas", 10),
                            justify="right", relief="flat", bd=0,
                            bg="#0B1016", fg=MINT, insertbackground=MINT,
                            buttonbackground="#111820",
                            highlightthickness=1,
                            highlightbackground=BORDER,
                            highlightcolor=GREEN)
            sb.grid(row=r, column=1, sticky="e", pady=3)
            return sb

        def _entry(parent, r, var, width=30, show=None):
            kw = {"textvariable": var, "width": width, "font": ("Consolas", 9),
                  "relief": "flat", "bd": 0, "bg": "#0B1016", "fg": MINT,
                  "insertbackground": MINT, "highlightthickness": 1,
                  "highlightbackground": BORDER, "highlightcolor": GREEN}
            if show:
                kw["show"] = show
            ent = tk.Entry(parent, **kw)
            ent.grid(row=r, column=1, sticky="e", pady=3)
            return ent

        c1 = _card("外观与行为", "sliders", pixel_ui.GREEN)
        _label_row(c1, 0, "显示缩放",
                   "宠物大小倍率，范围 0.50 ~ 2.00，修改后需重启宠物生效。")
        scale_var = tk.StringVar(value=f"{st['scale']:.2f}")
        _spin(c1, 0, scale_var, 0.5, 2.0, 0.25)
        _label_row(c1, 1, "行为模式",
                   "不同性格模式下 Vivian 的动作频率和风格不同：\n"
                   "调皮=频繁小动作 · 悠闲=偶尔走动 · 好奇=常观察四周 · "
                   "活跃=高频切换动作 · 关闭=静止。")
        preset_names = {"playful": "调皮", "relaxed": "悠闲",
                        "curious": "好奇", "active": "活跃", "off": "关闭"}
        behavior_var = tk.StringVar(value=preset_names.get(st["behavior"], "调皮"))
        _combo(c1, 1, behavior_var, list(preset_names.values()), 8)
        _label_row(c1, 2, "边缘处理",
                   "精灵图透明边缘的处理方式，解决半透明紫边问题：\n"
                   "软边=自然贴合（推荐） · 硬边=锐利无紫边 · 关闭=保留原始紫边。"
                   "修改后需重启生效。")
        edge_names = {"soft": "软边（自然贴合）", "hard": "硬边（锐利无紫边）",
                      "off": "关闭（保留紫边）"}
        edge_var = tk.StringVar(value=edge_names.get(
            getattr(self, "edge_mode", "soft"), "软边（自然贴合）"))
        _combo(c1, 2, edge_var, list(edge_names.values()), 18)

        c2 = _card("互动与提醒", "heart", pixel_ui.YELLOW)
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
        _check(c2, 0, "跟随鼠标模式", follow_var,
               "Vivian 会跟着鼠标移动，像被牵着走～\n"
               "与观察模式互斥，同时只能开启一个。")
        _check(c2, 1, "观察模式", watch_var,
               "Vivian 的眼睛会看向鼠标位置，静静观察你。\n"
               "与跟随模式互斥，同时只能开启一个。")
        auto_var = tk.BooleanVar(value=autorun_enabled())
        _check(c2, 2, "开机自动启动", auto_var,
               "通过当前用户的注册表自启动项实现，\n仅对当前 Windows 账户生效。")
        mood_var = tk.BooleanVar(value=getattr(self, "mood_auto", True))
        _check(c2, 3, "情绪随电脑负载变化", mood_var,
               "电脑负载低时开心捧花，负载高时抱臂生气，\n"
               "让 Vivian 的心情和你的电脑状态同步。")
        wink_var = tk.BooleanVar(value=getattr(self, "wink_auto", True))
        _check(c2, 4, "长时间未点击时眨眼提醒", wink_var,
               "超过提醒时间没有互动时，Vivian 会放大头部眨眼，\n提醒你回来玩～")
        _label_row(c2, 5, "提醒时间（秒）",
                   "多久没有互动才触发眨眼提醒，范围 5 ~ 600 秒。")
        try:
            cur_reminder = int(getattr(self, "reminder_s", DEFAULT_REMINDER_S))
        except Exception:
            cur_reminder = DEFAULT_REMINDER_S
        reminder_var = tk.StringVar(value=str(cur_reminder))
        _spin(c2, 5, reminder_var, 5, 600, 5)
        dance_var = tk.BooleanVar(value=bool(self._dance_cfg.get("enabled", False)))
        _check(c2, 6, "音乐跳舞（跟随系统音乐）", dance_var,
               "电脑播放音乐时，Vivian 会跟着节奏跳舞；\n"
               "跳舞时鼠标停在她身上会暂停，移开后继续。\n\n"
               "⚠️ 开启后会常驻一个系统声音监听通道用于检测音乐，\n"
               "会增加少量后台内存占用（约 5~15MB，CPU 极低），\n"
               "不常用时建议关闭。当前仅支持 Windows。")

        c3 = _card("语音包", "note", pixel_ui.BLUE)
        voice_var = tk.BooleanVar(value=getattr(self, "voice_enabled", True))
        _check(c3, 0, "启用语音包", voice_var,
               "动画切换、情绪变化、打招呼等事件时自动播放对应语音。")
        _label_row(c3, 1, "语音包",
                   "内置\"甜嗓默认\"语音包；也可自制语音包：\n"
                   "打开语音包目录，按 README 说明放入对应 mp3 即可。")
        packs = list_voice_packs()
        NO_PACK = "（不使用）"
        cur_pack = getattr(self, "voice_pack", "")
        pack_names = [NO_PACK] + packs
        if cur_pack and cur_pack not in packs:
            pack_names.append(cur_pack)
        pack_var = tk.StringVar(value=cur_pack if cur_pack in packs else NO_PACK)
        _combo(c3, 1, pack_var, pack_names, 14)
        _label_row(c3, 2, "语音音量", "语音包播放音量，0 ~ 100。")
        vol_var = tk.StringVar(value=str(int(getattr(self, "voice_volume", 80))))
        _spin(c3, 2, vol_var, 0, 100, 10)

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

        voice_btns = tk.Frame(c3, bg=CARD)
        voice_btns.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        tk.Button(voice_btns, text="🔊 试听", font=FS, relief="flat",
                  bg="#0B1016", fg=pixel_ui.GREEN, activebackground="#0F2A1C",
                  activeforeground=ACCENT, cursor="hand2",
                  command=_on_preview_voice).pack(side="left", padx=(0, 8))
        tk.Button(voice_btns, text="📂 打开语音包目录", font=FS, relief="flat",
                  bg="#0B1016", fg=pixel_ui.GREEN, activebackground="#0F2A1C",
                  activeforeground=ACCENT, cursor="hand2",
                  command=_on_open_voice_dir).pack(side="left")

        c4 = _card("语音交互", "mic", pixel_ui.GREEN)
        vic = dict(st.get("voice_interact", {}))
        vi_var = tk.BooleanVar(value=bool(vic.get("enabled", True)))
        _check(c4, 0, "启用语音交互", vi_var,
               "需要麦克风。说出\"Hi, Vivian\"唤醒 Vivian，她会随机应答"
               "（气泡 + 语音）。\n未检测到麦克风时自动关闭，"
               "可在托盘菜单\"重新检测麦克风\"。\n建议先在托盘执行\"校准唤醒词\"，"
               "识别更准。")
        _label_row(c4, 1, "模型 API 地址（选填）",
                   "OpenAI 兼容接口地址（如 https://api.openai.com/v1）。\n"
                   "填写后：唤醒 → 录下你说的话 → API 转写并对话 → 气泡回复；\n"
                   "不填写则只做本地随机应答，不上传任何音频。")
        api_url_var = tk.StringVar(value=str(vic.get("api_endpoint", "") or ""))
        _entry(c4, 1, api_url_var)
        _label_row(c4, 2, "API Key（选填）",
                   "仅保存在本机 settings.json 中，用于调用你填写的 API。")
        api_key_var = tk.StringVar(value=str(vic.get("api_key", "") or ""))
        _entry(c4, 2, api_key_var, show="*")
        _label_row(c4, 3, "模型名（选填）",
                   "对话使用的模型名，如 gpt-4o-mini，\n"
                   "具体取决于你的 API 服务商。")
        api_model_var = tk.StringVar(value=str(vic.get("api_model", "") or ""))
        _entry(c4, 3, api_model_var)
        _label_row(c4, 4, "转写模型名（选填）",
                   "语音转文字（STT）使用的模型，默认 whisper-1。\n"
                   "与对话模型名分开填写，适配不同服务商。")
        api_stt_var = tk.StringVar(value=str(vic.get("api_stt_model", "") or ""))
        _entry(c4, 4, api_stt_var, width=18)

        def _on_test_api():
            url = api_url_var.get().strip()
            if not url:
                api_test_lbl.config(text="✗ 请先填写 API 地址", fg="#FF5D5D")
                return
            api_test_lbl.config(text="测试中…", fg=SUB)
            client = vi.ModelAPIClient(
                endpoint=url,
                api_key=api_key_var.get().strip(),
                model=api_model_var.get().strip(),
                stt_model=api_stt_var.get().strip())

            def _work():
                ok, msg = client.test_connection()
                self._post_to_main(lambda: api_test_lbl.config(
                    text=("✓ " if ok else "✗ ") + msg,
                    fg=pixel_ui.GREEN if ok else "#FF5D5D"))

            threading.Thread(target=_work, daemon=True).start()

        api_btns = tk.Frame(c4, bg=CARD)
        api_btns.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        tk.Button(api_btns, text="🔌 测试连接", font=FS, relief="flat",
                  bg="#0B1016", fg=pixel_ui.GREEN, activebackground="#0F2A1C",
                  activeforeground=ACCENT, cursor="hand2",
                  command=_on_test_api).pack(side="left")
        api_test_lbl = tk.Label(api_btns, text="", bg=CARD, fg=SUB, font=FS)
        api_test_lbl.pack(side="left", padx=(10, 0))

        c5 = _card("其他", "star", pixel_ui.YELLOW)
        replay_var = tk.BooleanVar(value=not st.get("hatched", False))
        _check(c5, 0, "下次启动时播放破壳孵化动画", replay_var,
               "首次启动已自动播放过；勾选后下次启动会重新播放\n破壳孵化的小动画。")
        wiz_btns = tk.Frame(c5, bg=CARD)
        wiz_btns.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        tk.Button(wiz_btns, text="🧚 更换形象向导", font=FS, relief="flat",
                  bg="#0B1016", fg=pixel_ui.GREEN, activebackground="#0F2A1C",
                  activeforeground=ACCENT, cursor="hand2",
                  command=self._open_appearance_wizard).pack(side="left",
                                                             padx=(0, 8))
        try:
            from hatch_pet.appearance_wizard import has_custom_appearance
            if has_custom_appearance():
                tk.Button(wiz_btns, text="↩️ 恢复默认形象", font=FS,
                          relief="flat", bg="#0B1016", fg=pixel_ui.GREEN,
                          activebackground="#0F2A1C",
                          activeforeground=ACCENT, cursor="hand2",
                          command=self._restore_default_appearance
                          ).pack(side="left")
        except Exception:
            pass

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

            new_vic = {
                "enabled": bool(vi_var.get()),
                "cooldown_sec": 10,
                "api_endpoint": api_url_var.get().strip(),
                "api_key": api_key_var.get().strip(),
                "api_model": api_model_var.get().strip(),
                "api_stt_model": api_stt_var.get().strip(),
            }
            old_vic = dict(st.get("voice_interact", {}))
            self.voice_cfg = new_vic
            svc = getattr(self, "voice_service", None)
            if svc is not None:
                # API 配置热更新：无需重启语音流即可生效
                svc.set_api(vi.ModelAPIClient(
                    endpoint=new_vic["api_endpoint"],
                    api_key=new_vic["api_key"],
                    model=new_vic["api_model"],
                    stt_model=new_vic.get("api_stt_model", "")))
            if bool(old_vic.get("enabled", True)) != new_vic["enabled"]:
                if svc is not None:
                    svc.stop()
                if new_vic["enabled"]:
                    self._start_voice_service()

            # —— 音乐跳舞开关（立即生效）——
            new_dance = {"enabled": bool(dance_var.get())}
            old_dance_on = bool(self._dance_cfg.get("enabled", False))
            self._dance_cfg = new_dance
            if new_dance["enabled"] and not old_dance_on:
                self._start_music_dance(notify_fail=True)
            elif not new_dance["enabled"] and old_dance_on:
                self._stop_music_dance()

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
                           "voice_volume": new_vol,
                           "voice_interact": new_vic,
                           "music_dance": new_dance})
            save_settings(merged)

            need_restart = abs(new_scale - old_scale) > 1e-6 or new_edge != self.edge_mode

            def _after_close():
                if need_restart:
                    from tkinter import messagebox
                    msg = []
                    if abs(new_scale - old_scale) > 1e-6:
                        msg.append("缩放")
                    if new_edge != self.edge_mode:
                        msg.append("边缘处理")
                    if messagebox.askyesno(
                            APP_NAME,
                            f"{'、'.join(msg)}已修改，需要重启宠物才能生效。\n现在重启吗？",
                            parent=self.root):
                        restart()

            _close_settings(_after_close)

        def _save_window_size():
            try:
                merged = load_settings()
                merged["settings_window"] = {
                    "w": max(500, win.winfo_width()),
                    "h": max(430, win.winfo_height())}
                save_settings(merged)
            except Exception:
                pass

        def _close_settings(then=None):
            _unbind_wheel()
            _save_window_size()
            glass_ui.animate_close(win, lambda: _destroy_win(then))

        def _destroy_win(then):
            try:
                win.destroy()
            except Exception:
                pass
            if then:
                then()

        def on_cancel():
            _close_settings()

        btn_cancel = tk.Button(footer, text="取消", width=9, font=F,
                               relief="flat", bg="#0B1016", fg=pixel_ui.BLUE,
                               activebackground="#0F2A1C",
                               activeforeground=pixel_ui.BLUE, cursor="hand2",
                               command=on_cancel)
        btn_save = tk.Button(footer, text="保存设置", width=12,
                             font=("Microsoft YaHei", 10, "bold"),
                             relief="flat", bg=pixel_ui.YELLOW, fg="#0A0E14",
                             activebackground="#FFE94A",
                             activeforeground="#0A0E14", cursor="hand2",
                             command=on_save)
        _add_btn(btn_save, "right")
        _add_btn(btn_cancel, "right")
        btn_about = tk.Button(footer, text="ℹ️ 关于", width=9, font=FS,
                              relief="flat", bg="#0B1016", fg=pixel_ui.GREEN,
                              activebackground="#0F2A1C",
                              activeforeground=pixel_ui.GREEN, cursor="hand2",
                              command=lambda: self._show_about(win))
        _add_btn(btn_about, "left")
        win.protocol("WM_DELETE_WINDOW", on_cancel)

        # —— 计算尺寸与位置 → 抓取背后屏幕生成毛玻璃 → 显示 ——
        win.update_idletasks()
        _relayout()
        try:
            content_h = 78 + sum(max(1, w.winfo_reqheight()) + 12
                                 for _, w in _cards) + 56
        except Exception:
            content_h = 680
        sh = win.winfo_screenheight()
        sw = win.winfo_screenwidth()
        canvas_h = max(320, min(content_h, sh - 170))
        saved = st.get("settings_window") or {}
        try:
            W_TOTAL = max(500, min(int(saved.get("w", CW + SBW)), sw - 16))
            outer_h = max(430, min(int(saved.get("h", canvas_h + 40 + FTR_H)),
                                   sh - 60))
        except Exception:
            W_TOTAL = CW + SBW
            outer_h = canvas_h + glass_ui.TITLE_H
        px, py = self.root.winfo_x(), self.root.winfo_y()
        x = px + self.win_w + 14
        if x + W_TOTAL > sw - 8:
            x = px - W_TOTAL - 14
        x = max(8, min(x, sw - W_TOTAL - 8))
        y = max(8, min(py - 10, sh - outer_h - 60))

        win.geometry(f"{W_TOTAL}x{outer_h}+{x}+{y}")
        win.resizable(True, True)          # 窗口可自由调整大小
        win.minsize(500, 430)
        win.update_idletasks()
        _glass_pil = [None]                # 毛玻璃原图（缩放窗口时重采样）
        _glass_item = [None]
        _glass_size = [None]
        _glass_after = [None]

        def _resize_glass():
            _glass_after[0] = None
            if _glass_pil[0] is None:
                return
            w = canvas.winfo_width()
            h = canvas.winfo_height()
            if w < 20 or h < 20 or (w, h) == _glass_size[0]:
                return
            try:
                from PIL.ImageTk import PhotoImage as _GlassPhoto
                # 像素壁纸按新尺寸重新生成（固定种子），保持硬边不糊
                self._settings_glass = _GlassPhoto(pixel_ui.pixel_backdrop(w, h))
                canvas.itemconfig(_glass_item[0], image=self._settings_glass)
                _glass_size[0] = (w, h)
            except Exception:
                pass

        def _on_canvas_resize(_e=None):
            _relayout()
            if _glass_after[0] is not None:
                try:
                    win.after_cancel(_glass_after[0])
                except Exception:
                    pass
            _glass_after[0] = win.after(140, _resize_glass)

        canvas.bind("<Configure>", _on_canvas_resize)
        try:
            grab_h = max(canvas_h, min(content_h,
                                       sh - (y + glass_ui.TITLE_H) - 8))
            # 像素风壁纸：黑底渐变 + 星空 + 霓虹天际线（固定种子，缩放一致）
            img = pixel_ui.pixel_backdrop(W_TOTAL - SBW, grab_h)
            if img is not None:
                from PIL.ImageTk import PhotoImage as _GlassPhoto
                _glass_pil[0] = img
                self._settings_glass = _GlassPhoto(img)
                _glass_item[0] = canvas.create_image(
                    0, 0, anchor="nw", image=self._settings_glass)
                canvas.tag_lower(_glass_item[0])
                for _iid in (_title_id, _sub_id):
                    canvas.tag_raise(_iid)       # 确保标题在壁纸之上
                _glass_size[0] = (W_TOTAL - SBW, grab_h)
                win.configure(bg=pixel_ui.BLACK_BG)
        except Exception:
            log.exception("像素壁纸生成失败，使用纯色背景")
        _relayout()
        win.deiconify()
        win.attributes("-alpha", 0.0)
        win.grab_set()
        win.focus_set()

        def _install_logos():
            # PhotoImage 必须在窗口映射后创建，否则会得到空白图像
            for job in _logo_jobs:
                try:
                    job()
                except Exception:
                    pass
            _relayout()

        win.after(20, _install_logos)
        glass_ui.animate_open(win)         # 淡入 + 上滑入场

    def _show_about(self, parent=None):
        import webbrowser
        tk = dr.tk
        win = tk.Toplevel(parent or self.root)
        win.title(f"关于 {APP_NAME}")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win.configure(bg=pixel_ui.BLACK_BG)
        win.transient(parent or self.root)

        head = tk.Frame(win, bg="#0F1724", highlightbackground=pixel_ui.GREEN,
                        highlightthickness=2)
        head.pack(fill="x")
        face_lbl = tk.Label(head, bg="#0F1724")
        face_lbl.pack(pady=(16, 0))

        def _install_face():
            try:
                photo = pixel_ui.icon_photo(face_lbl, "face", scale=4)
                face_lbl.config(image=photo)
                face_lbl.image = photo
            except Exception:
                pass
        win.after(30, _install_face)
        tk.Label(head, text=APP_NAME, font=("Microsoft YaHei", 15, "bold"),
                 fg=pixel_ui.GREEN, bg="#0F1724").pack()
        tk.Label(head, text=f"v{APP_VERSION} · {APP_CREDIT}",
                 font=("Microsoft YaHei", 9), fg=pixel_ui.SUB,
                 bg="#0F1724").pack(pady=(2, 14))

        tk.Label(win, text="一只会看你的心情、会自然眨眼、会举臂打招呼的小裙裙 🌸\n"
                           "电脑负载低时捧花开心，负载高时抱臂生气，失败时叹口气。\n"
                           "听到音乐还会跟着跳舞，鼠标停在她身上就暂停。\n"
                           "支持语音交互（说话唤醒 · 多轮对话 · 可接入模型 API）\n"
                           "与自定义语音包，提醒时间可在设置中调整。",
                 bg=pixel_ui.BLACK_BG, fg=pixel_ui.TEXT,
                 font=("Microsoft YaHei", 10),
                 justify="left").pack(padx=24, pady=(16, 8))

        tk.Frame(win, bg=pixel_ui.BLACK_LINE, height=2).pack(fill="x", padx=24)

        tk.Label(win, text="🌐 开源地址", bg=pixel_ui.BLACK_BG,
                 fg=pixel_ui.BLUE,
                 font=("Microsoft YaHei", 10, "bold")).pack(
            anchor="w", padx=24, pady=(10, 4))

        def _link_row(url, label):
            frm = tk.Frame(win, bg=pixel_ui.BLACK_BG)
            frm.pack(fill="x", padx=24, pady=2)

            def _open(_e=None):
                try:
                    webbrowser.open(url)
                except Exception:
                    pass

            def _copy(_e=None):
                try:
                    win.clipboard_clear()
                    win.clipboard_append(url)
                    lbl_copy.config(text="已复制 ✓")
                    win.after(1500, lambda: lbl_copy.config(text="复制"))
                except Exception:
                    pass

            tk.Label(frm, text=label, bg=pixel_ui.BLACK_BG, fg=pixel_ui.SUB,
                     font=("Microsoft YaHei", 10)).pack(side="left")
            link = tk.Label(frm, text=url, bg=pixel_ui.BLACK_BG,
                            fg=pixel_ui.BLUE,
                            font=("Consolas", 9), cursor="hand2")
            link.pack(side="left", padx=(8, 0))
            link.bind("<Button-1>", _open)
            lbl_copy = tk.Label(frm, text="复制", bg="#0B1016", fg=pixel_ui.BLUE,
                                font=("Microsoft YaHei", 9), cursor="hand2",
                                padx=6)
            lbl_copy.pack(side="right")
            lbl_copy.bind("<Button-1>", _copy)

        _link_row("https://github.com/gb80231314/Vivian-DeskTopPet", "GitHub：")
        _link_row("https://gitee.com/Louis-QI/Vivian-DeskTopPet", "Gitee：")
        tk.Label(win, text="点击链接在浏览器打开 · 点击\"复制\"复制地址",
                 bg=pixel_ui.BLACK_BG, fg=pixel_ui.SUB,
                 font=("Microsoft YaHei", 8)).pack(anchor="w", padx=24)

        tk.Button(win, text="关闭", width=10, font=("Microsoft YaHei", 10),
                  relief="flat", bg=pixel_ui.YELLOW, fg="#0A0E14",
                  activebackground="#FFE94A", activeforeground="#0A0E14",
                  cursor="hand2", command=win.destroy).pack(pady=(12, 18))

def restart():
    python = sys.executable
    os.execv(python, [f'"{python}"'] + sys.argv[1:])

_SINGLE_MUTEX = None

def _acquire_single_instance() -> bool:
    global _SINGLE_MUTEX
    try:
        if not IS_WINDOWS:
            return True
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _SINGLE_MUTEX = kernel32.CreateMutexW(None, False, "QPet_VivianPet_SingleInstance")
        if ctypes.get_last_error() == 183:
            return False
    except Exception:
        pass
    return True

def _install_excepthook():
    import traceback

    def _hook(t, v, tb):
        try:
            log.error("未捕获异常:\n%s",
                      "".join(traceback.format_exception(t, v, tb)))
        except Exception:
            pass

    def _thread_hook(args):
        try:
            log.error("线程异常(%s):\n%s", args.thread.name if args.thread else "?",
                      "".join(traceback.format_exception(
                          args.exc_type, args.exc_value, args.exc_traceback)))
        except Exception:
            pass

    sys.excepthook = _hook
    threading.excepthook = _thread_hook

def main():
    _install_excepthook()
    if not _acquire_single_instance():
        log.info("已有实例在运行，本次启动退出")
        return
    try:
        _run_app()
    except Exception:
        log.exception("主流程异常退出")
    finally:
        logging.shutdown()
        os._exit(0)

def _run_app():
    st = load_settings()
    hatch = not st.get("hatched", False)

    if st.get("autostart") and getattr(sys, "frozen", False):
        try:
            set_autorun(True)
        except Exception:
            pass

    res = resource_dir()
    sheet_path = res / "spritesheet.png"
    config_path = res / "pet.json"
    try:
        # 用户自定义形象优先（更换形象向导产出）
        from hatch_pet.appearance_wizard import has_custom_appearance, \
            appearance_dir
        if has_custom_appearance():
            adir = appearance_dir()
            sheet_path = adir / "spritesheet.png"
            config_path = adir / "pet.json"
            logging.getLogger("qpet").info("使用自定义形象: %s", sheet_path)
    except Exception:
        pass
    pet = QPetApp(
        spritesheet_path=str(sheet_path),
        config_path=str(config_path),
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
        voice_cfg=dict(st.get("voice_interact", {})),
        music_cfg=dict(st.get("music_dance", {})),
    )
    if hatch:

        st["hatched"] = True
        save_settings(st)
    if st.get("behavior") == "off":
        pet.random_engine.enabled = False
    pet.run()

if __name__ == "__main__":
    main()
