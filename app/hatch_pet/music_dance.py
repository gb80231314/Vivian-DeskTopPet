# -*- coding: utf-8 -*-
"""music_dance — 系统音乐检测（Windows WASAPI 回环采集）

监听电脑正在播放的声音，判断「是否在放音乐」并输出节拍回调，
供桌面宠物跟随音乐跳舞。

采集实现：ctypes 直连 WASAPI 回环（IMMDeviceEnumerator → IAudioClient
带 AUDCLNT_STREAMFLAGS_LOOPBACK → IAudioCaptureClient 轮询）。
不依赖 sounddevice——其 0.5.6（含所有已发布版本）的 WasapiSettings
尚不支持 loopback 参数，只有 git master 支持，因此直接走系统 COM。
解析用 array/struct 标准库，全程零第三方依赖。

资源占用：常驻 1 条回环采集线程 + 1 条 8Hz 分析线程，
内存增量约 5~15MB，CPU 占用极低——因此该功能默认关闭，由设置面板开关。
"""
import array
import collections
import ctypes
import sys
import threading
import time
from ctypes import POINTER, Structure, byref, c_ubyte, c_uint16, c_uint32
from ctypes import c_uint64, c_void_p

# 采集与分析参数
TICK_S = 0.12               # 分析节拍
WINDOW_S = 8.0              # 能底统计窗口
FAST_S = 0.6                # 快能量窗口
NOW_S = 0.15                # 瞬时能量窗口
MUSIC_ON_S = 1.0            # 持续响亮多久判定「在放音乐」
MUSIC_OFF_S = 2.5           # 持续安静多久判定「音乐结束」
FLOOR_RATIO = 2.2           # 快能量 / 能底 判定阈值
BEAT_JUMP = 1.30            # 瞬时 / 快能量 跳变阈值（onset）
BEAT_GAP_S = 0.32           # 两次节拍最小间隔
ABS_FLOOR = 1.5e-4          # 绝对静音门限（数字静音保护）

# WASAPI 常量
_CLSCTX_ALL = 0x17
_AUDCLNT_SHAREMODE_SHARED = 0
_AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
_AUDCLNT_BUFFERFLAGS_SILENT = 0x2
_HNS_200MS = 2_000_000      # 100ns 单位
_COINIT_MULTITHREADED = 0x0

_CLSID_MMDeviceEnumerator = "BCDE0395-E52F-467C-8E3D-C4579291692E"
_IID_IMMDeviceEnumerator = "A95664D2-9614-4F35-A746-DE8DB63617E6"
_IID_IMMDevice = "0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"
_IID_IAudioClient = "1CB9AD4C-DBFA-4C32-B178-C2F568A703B2"
_IID_IAudioCaptureClient = "C8ADBD64-E71E-48A0-A4DE-185C395CD317"


class _GUID(Structure):
    _fields_ = [("Data1", c_uint32), ("Data2", c_uint16), ("Data3", c_uint16),
                ("Data4", c_ubyte * 8)]


def _guid(s: str) -> _GUID:
    d1, d2, d3, d4a, d4b = s.split("-")
    return _GUID(int(d1, 16), int(d2, 16), int(d3, 16),
                 (c_ubyte * 8)(*bytes.fromhex(d4a + d4b)))


class _WAVEFORMATEX(Structure):
    _fields_ = [("wFormatTag", c_uint16), ("nChannels", c_uint16),
                ("nSamplesPerSec", c_uint32), ("nAvgBytesPerSec", c_uint32),
                ("nBlockAlign", c_uint16), ("wBitsPerSample", c_uint16),
                ("cbSize", c_uint16)]


class _ComError(Exception):
    pass


def _vtbl_fn(obj: int, index: int, restype, *argtypes):
    """取 COM 对象 vtable 第 index 项。调用时需把对象地址作为第一个参数。"""
    lpVtbl = ctypes.cast(obj, POINTER(c_void_p)).contents.value
    fn = ctypes.cast(lpVtbl + index * ctypes.sizeof(c_void_p),
                     POINTER(c_void_p)).contents.value
    return ctypes.WINFUNCTYPE(restype, *argtypes)(fn)


def _hr(res, what=""):
    """校验一次 COM 调用的 HRESULT 结果（非 0 即失败）"""
    if res != 0:
        raise _ComError("%s failed (hr=0x%08X)" % (what or "?", res & 0xFFFFFFFF))
    return res


class _WasapiLoopback:
    """默认输出设备的 WASAPI 回环采集（单线程使用，COM 已在该线程初始化）。"""

    def __init__(self):
        self._ole = False
        self._dev = self._enum = self._client = self._capture = None
        self._fmt = None
        self.channels = 0
        self.sample_rate = 0
        self.bytes_per_sample = 0

    # ---- 生命周期 ----
    def open(self):
        ole32 = ctypes.windll.ole32
        hr = ole32.CoInitializeEx(None, _COINIT_MULTITHREADED)
        if hr in (0, 1):            # S_OK / S_FALSE
            self._ole = True
        elif hr != -2147417850:     # RPC_E_CHANGED_MODE：复用已有初始化
            raise _ComError("CoInitializeEx hr=0x%08X" % (hr & 0xFFFFFFFF))
        try:
            self._open_endpoint()
        except Exception:
            self.close()
            raise

    def _open_endpoint(self):
        enum = c_void_p()
        # CoCreateInstance(rclsid, pUnkOuter, dwClsContext, riid, ppv)
        hr = ctypes.windll.ole32.CoCreateInstance(
            byref(_guid(_CLSID_MMDeviceEnumerator)), None, _CLSCTX_ALL,
            byref(_guid(_IID_IMMDeviceEnumerator)), byref(enum))
        if hr != 0:
            raise _ComError("CoCreateInstance(MMDeviceEnumerator) hr=0x%08X"
                            % (hr & 0xFFFFFFFF))
        self._enum = enum
        enum_fn = _vtbl_fn(enum, 4, ctypes.HRESULT, c_void_p, c_uint32,
                           c_uint32, POINTER(c_void_p))
        dev = c_void_p()
        _hr(enum_fn(enum, 0, 1, byref(dev)), what="GetDefaultAudioEndpoint")  # eRender, eMultimedia
        self._dev = dev

        dev_fn = _vtbl_fn(dev, 3, ctypes.HRESULT, c_void_p, POINTER(_GUID),
                          c_uint32, c_void_p, POINTER(c_void_p))
        client = c_void_p()
        _hr(dev_fn(dev, byref(_guid(_IID_IAudioClient)), _CLSCTX_ALL, None,
                   byref(client)), what="IMMDevice.Activate")
        self._client = client

        client_fn8 = _vtbl_fn(client, 8, ctypes.HRESULT, c_void_p,
                              POINTER(c_void_p))
        fmt_ptr = c_void_p()
        _hr(client_fn8(client, byref(fmt_ptr)), what="GetMixFormat")
        self._fmt = fmt_ptr
        wfx = ctypes.cast(fmt_ptr, POINTER(_WAVEFORMATEX)).contents
        self.channels = max(1, wfx.nChannels)
        self.sample_rate = wfx.nSamplesPerSec
        self.bytes_per_sample = max(1, wfx.nBlockAlign // max(1, wfx.nChannels))

        client_fn3 = _vtbl_fn(client, 3, ctypes.HRESULT, c_void_p, c_uint32,
                              c_uint32, ctypes.c_int64, ctypes.c_int64,
                              c_void_p, c_void_p)
        _hr(client_fn3(client, _AUDCLNT_SHAREMODE_SHARED,
                       _AUDCLNT_STREAMFLAGS_LOOPBACK, _HNS_200MS, 0,
                       fmt_ptr, None), what="IAudioClient.Initialize(LOOPBACK)")

        client_fn14 = _vtbl_fn(client, 14, ctypes.HRESULT, c_void_p,
                               POINTER(_GUID), POINTER(c_void_p))
        capture = c_void_p()
        _hr(client_fn14(client, byref(_guid(_IID_IAudioCaptureClient)),
                        byref(capture)), what="GetService(CaptureClient)")
        self._capture = capture

        _hr(_vtbl_fn(client, 10, ctypes.HRESULT, c_void_p)(client),
            what="Start")

    def close(self):
        for attr in ("_capture", "_client", "_dev", "_enum"):
            obj = getattr(self, attr, None)
            if obj:
                try:
                    _vtbl_fn(obj, 2, c_uint32, c_void_p)(obj)  # IUnknown::Release
                except Exception:
                    pass
                setattr(self, attr, None)
        if self._fmt:
            try:
                ctypes.windll.ole32.CoTaskMemFree(self._fmt)
            except Exception:
                pass
            self._fmt = None
        if self._ole:
            try:
                ctypes.windll.ole32.CoUninitialize()
            except Exception:
                pass
            self._ole = False

    # ---- 采集 ----
    def read_packets(self):
        """非阻塞读取当前可用数据包，返回 [(rms, silent), ...]"""
        out = []
        capture = self._capture
        next_fn = _vtbl_fn(capture, 5, ctypes.HRESULT, c_void_p,
                           POINTER(c_uint32))
        buf_fn = _vtbl_fn(capture, 3, ctypes.HRESULT, c_void_p,
                          POINTER(c_void_p), POINTER(c_uint32),
                          POINTER(c_uint32), POINTER(c_uint64),
                          POINTER(c_uint64))
        rel_fn = _vtbl_fn(capture, 4, ctypes.HRESULT, c_void_p, c_uint32)
        bps = self.bytes_per_sample * self.channels
        while True:
            n = c_uint32(0)
            _hr(next_fn(capture, byref(n)), what="GetNextPacketSize")
            if n.value == 0:
                break
            data, frames, flags, _pos, _qpc = c_void_p(), c_uint32(0), \
                c_uint32(0), c_uint64(0), c_uint64(0)
            _hr(buf_fn(capture, byref(data), byref(frames), byref(flags),
                       byref(_pos), byref(_qpc)), what="GetBuffer")
            try:
                if frames.value == 0:
                    continue
                if flags.value & _AUDCLNT_BUFFERFLAGS_SILENT:
                    out.append((0.0, True))
                else:
                    raw = ctypes.string_at(data.value, frames.value * bps)
                    out.append((_rms_of(raw, self.bytes_per_sample), False))
            finally:
                try:
                    _hr(rel_fn(capture, frames.value), what="ReleaseBuffer")
                except _ComError:
                    pass
        return out


def _rms_of(raw: bytes, bytes_per_sample: int) -> float:
    if bytes_per_sample == 4:
        vals = array.array("f")
        vals.frombytes(raw[:len(raw) // 4 * 4])
        n = len(vals)
        if n == 0:
            return 0.0
        acc = 0.0
        for x in vals:
            acc += x * x
        return (acc / n) ** 0.5
    if bytes_per_sample == 2:
        vals = array.array("h")
        vals.frombytes(raw[:len(raw) // 2 * 2])
        n = len(vals)
        if n == 0:
            return 0.0
        acc = 0.0
        for x in vals:
            acc += x * x
        return (acc / n) ** 0.5 / 32768.0
    return 0.0


class MusicDetector:

    def __init__(self, on_beat, on_music, on_quiet, log_fn=None):
        self.on_beat = on_beat          # 检测到节拍（检测线程内调用）
        self.on_music = on_music        # 音乐开始
        self.on_quiet = on_quiet        # 音乐结束
        self._log = log_fn or (lambda *a, **k: None)

        self._cap_thread = None
        self._thread = None
        self._stop_evt = threading.Event()
        self._lock = threading.Lock()
        self._rms_q = collections.deque()   # (ts, rms)
        self.last_error = ""
        self.device_name = "默认输出设备"

    # ---------- 能力探测 ----------
    @staticmethod
    def supported() -> tuple:
        """(是否支持, 原因)。依赖 Windows WASAPI 回环（系统内置，无版本问题）"""
        if not sys.platform.startswith("win"):
            return False, "仅 Windows 支持（需要 WASAPI 回环采集）"
        if not hasattr(ctypes, "windll"):
            return False, "缺少 ctypes.windll"
        return True, "默认输出设备"

    # ---------- 生命周期 ----------
    @property
    def running(self) -> bool:
        threads = (self._cap_thread, self._thread)
        return any(t is not None and t.is_alive() for t in threads)

    def start(self) -> bool:
        if self.running:
            return True
        ok, why = self.supported()
        if not ok:
            self.last_error = why
            self._log("[music] 不可用: %s" % why)
            return False
        self._stop_evt.clear()
        self._cap_thread = threading.Thread(target=self._capture_loop,
                                            daemon=True, name="qpet-music-cap")
        self._cap_thread.start()
        self._thread = threading.Thread(target=self._analyze_loop,
                                        daemon=True, name="qpet-music")
        self._thread.start()
        # 采集线程若打开失败会立即退出（last_error 已记录原因）
        self._cap_thread.join(timeout=1.0)
        if not self._cap_thread.is_alive():
            self.stop(join_s=0.5)
            return False
        self._log("[music] 系统声音监听已启动 (%s)" % self.device_name)
        return True

    def stop(self, join_s: float = 2.0):
        self._stop_evt.set()
        t = self._cap_thread
        if t is not None and t.is_alive() and join_s > 0:
            t.join(timeout=join_s)
        t = self._thread
        if t is not None and t.is_alive() and join_s > 0:
            t.join(timeout=join_s)
        self._cap_thread = None
        self._thread = None
        self._log("[music] 系统声音监听已停止")

    # ---------- 采集线程（COM 需在调用线程内初始化） ----------
    def _capture_loop(self):
        wasapi = _WasapiLoopback()
        try:
            wasapi.open()
        except Exception as e:
            self.last_error = str(e)
            self._log("[music] 回环采集打开失败: %s" % e)
            wasapi.close()
            return
        self._log("[music] 回环已连接: %d Hz x %d ch (%d-bit)"
                  % (wasapi.sample_rate, wasapi.channels,
                     wasapi.bytes_per_sample * 8))
        errors = 0
        try:
            while not self._stop_evt.is_set():
                try:
                    self._stop_evt.wait(0.01)
                    now = time.time()
                    with self._lock:
                        q = self._rms_q
                        while q and now - q[0][0] > WINDOW_S:
                            q.popleft()
                    for rms, _silent in wasapi.read_packets():
                        with self._lock:
                            self._rms_q.append((time.time(), rms))
                    errors = 0
                except _ComError as e:
                    errors += 1
                    self._log("[music] 采集异常(%d): %s" % (errors, e))
                    if errors >= 3:
                        self.last_error = str(e)
                        return
                    self._stop_evt.wait(1.0)
        finally:
            wasapi.close()

    # ---------- 分析线程 ----------
    def _analyze_loop(self):
        was_music = False
        loud_s = 0.0
        quiet_s = 0.0
        last_beat = 0.0
        while not self._stop_evt.is_set():
            if self._stop_evt.wait(TICK_S):
                return
            now = time.time()
            with self._lock:
                q = self._rms_q
                while q and now - q[0][0] > WINDOW_S:
                    q.popleft()
                snap = list(q)
            if not snap:
                continue
            vals = [v for _, v in snap]

            def _mean_since(hi_s):
                seg = [v for t, v in snap if now - t <= hi_s]
                return sum(seg) / len(seg) if seg else None

            e_now = _mean_since(NOW_S)
            e_fast = _mean_since(FAST_S)
            # 能底取窗口最小值：真静音（含数字静音 0）远低于音乐谷值，
            # 音乐持续播放时也不会被自身能量抬升而误判为安静
            e_floor = min(vals) if vals else 0.0
            if e_now is None or e_fast is None:
                continue

            floor_gate = max(e_floor * FLOOR_RATIO, ABS_FLOOR)
            loud = e_fast > floor_gate

            if loud:
                loud_s = min(loud_s + TICK_S, MUSIC_ON_S + 0.5)
                quiet_s = 0.0
            else:
                quiet_s += TICK_S
                loud_s = max(0.0, loud_s - TICK_S * 0.5)

            if not was_music and loud_s >= MUSIC_ON_S:
                was_music = True
                loud_s = 0.0
                self._log("[music] 检测到音乐 (fast=%.5f floor=%.5f)"
                          % (e_fast, e_floor))
                try:
                    self.on_music()
                except Exception:
                    pass
            elif was_music and quiet_s >= MUSIC_OFF_S:
                was_music = False
                quiet_s = 0.0
                loud_s = 0.0  # 清空累计，重新开始需再持续响亮 MUSIC_ON_S
                self._log("[music] 音乐结束 (fast=%.5f)" % e_fast)
                try:
                    self.on_quiet()
                except Exception:
                    pass

            if was_music and e_now > e_fast * BEAT_JUMP \
                    and e_now > max(e_floor * 2.5, ABS_FLOOR * 2.0) \
                    and now - last_beat >= BEAT_GAP_S:
                last_beat = now
                try:
                    self.on_beat()
                except Exception:
                    pass
