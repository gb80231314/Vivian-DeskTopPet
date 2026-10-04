import json
import math
import os
import random
import struct
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path
from typing import Callable, Optional

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280
FRAME_MS = 80

DEFAULT_COOLDOWN_S = 10.0

UTTER_MAX_MS = 6000
UTTER_SILENCE_END_MS = 1200
UTTER_MIN_MS = 400
ECHO_DISCARD_MS = 1200

PROBE_MS = 300

MIC_DETECT_ATTEMPTS = 3
MIC_DETECT_RETRY_S = 15.0

WAKE_RESPONSES = [
    "在呢在呢～Vivian 听到啦！",
    "嗨～我一直都在哦，找我什么事呀？",
    "嗯？是叫我吗？来啦来啦！",
    "叮咚～Vivian 上线！有什么吩咐？",
    "听到你的声音啦，开心～ 🌸",
    "我在我在！今天也要元气满满哦！",
    "诶嘿嘿，被你叫醒了～",
    "来喽～有什么想跟我说的吗？",
    "竖起耳朵听你说～",
    "哇，是你呀！我刚才正想你来着～",
    "到！Vivian 随时待命！",
    "嗯哼？我在听，请讲～",
]

FALLBACK_REPLIES = [
    "嗯嗯，我在认真听～",
    "好呀好呀，就这样陪着你～",
    "唔……虽然没太听懂，但我会一直陪着你的！",
    "你说的话我都记住啦（大概）～",
    "嘿嘿，跟你聊天最开心了！",
]

SYSTEM_PROMPT = (
    "你是 Vivian，一只住在用户电脑桌面上的 Q 版小裙裙桌面宠物，性格活泼可爱、"
    "语气软萌，喜欢用「～」和颜文字。请用不超过 40 字的中文口语回复用户，"
    "不要使用 markdown 格式。"
)

BAND_FREQS = (250.0, 400.0, 600.0, 850.0, 1150.0, 1500.0, 1900.0, 2400.0, 3000.0, 3700.0)
NBANDS = len(BAND_FREQS)

BAND_SNR_GATE = 2.5
VAD_MIN_BANDS = 3
FLATNESS_MAX = 0.45
ZCR_MAX = 0.32
MIN_BAND_ENERGY = 5e5
NOISE_EMA = 0.04
RMS_FLOOR_INIT = 120.0

CAND_MIN_MS = 450
CAND_MAX_MS = 2500
CAND_END_SIL_MS = 700

WAKE_SCORE_GATE = 3.5
SYL_MIN_ENV = 2.0
SYL_MERGE_FRAMES = 3

HISTORY_MAX_MSGS = 8        # 对话上下文保留的最大消息数（user+assistant）
HISTORY_TTL_S = 600.0       # 上下文闲置多久后清空


def _goertzel_coeffs():
    coeffs = []
    for f in BAND_FREQS:
        k = max(1, min(FRAME_SAMPLES - 1, round(FRAME_SAMPLES * f / SAMPLE_RATE)))
        coeffs.append(2.0 * math.cos(2.0 * math.pi * k / FRAME_SAMPLES))
    return coeffs


_GOERTZEL = _goertzel_coeffs()


def _spectral_flatness(energy) -> float:
    logs = [math.log10(e + 1e-6) for e in energy]
    geo = sum(logs) / len(logs)
    arith = (sum(energy) + 1e-6) / len(energy)
    return (10 ** geo) / (arith + 1e-9)


def _frame_zcr(buf: bytes) -> float:
    cnt = len(buf) // 2
    if cnt < 2:
        return 0.0
    s = struct.unpack("<%dh" % cnt, buf)
    zc = 0
    prev = s[0] < 0
    for x in s[1:]:
        cur = x < 0
        if cur != prev:
            zc += 1
            prev = cur
    return zc / cnt


def _band_energies(buf: bytes):
    samples = struct.unpack("<%dh" % (len(buf) // 2), buf)
    emph = []
    prev = 0.0
    append = emph.append
    for x in samples:
        append(x - 0.95 * prev)
        prev = x
    energy = []
    for coeff in _GOERTZEL:
        s1 = 0.0
        s2 = 0.0
        for x in emph:
            s0 = x + coeff * s1 - s2
            s2 = s1
            s1 = s0
        energy.append(max(0.0, s1 * s1 + s2 * s2 - coeff * s1 * s2))
    return energy


def _frame_rms(buf: bytes) -> float:
    cnt = len(buf) // 2
    if cnt == 0:
        return 0.0
    vals = struct.unpack("<%dh" % cnt, buf)
    return (sum(v * v for v in vals) / cnt) ** 0.5


def detect_microphone() -> tuple:
    try:
        import sounddevice as sd
    except Exception:
        return False, "音频库不可用（sounddevice 未安装）"
    try:
        devs = sd.query_devices()
    except Exception:
        return False, "音频系统初始化失败"
    inputs = [d for d in devs if d.get("max_input_channels", 0) > 0]
    if not inputs:
        return False, "未检测到任何麦克风设备"
    try:
        default_in = sd.query_devices(kind="input")
    except Exception:
        return False, "未设置默认麦克风"
    if not default_in:
        return False, "未设置默认麦克风"
    return True, str(default_in.get("name", "麦克风"))


def probe_capture(ms: int = PROBE_MS) -> bool:
    try:
        import sounddevice as sd
        n = int(SAMPLE_RATE * ms / 1000)
        with sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1,
                               dtype="int16", blocksize=FRAME_SAMPLES) as s:
            total = 0
            peak = 0
            while total < n:
                data, _ = s.read(min(FRAME_SAMPLES, n - total))
                b = bytes(data)
                total += len(b) // 2
                cnt = len(b) // 2
                if cnt:
                    vals = struct.unpack("<%dh" % cnt, b)
                    peak = max(peak, max(abs(v) for v in vals))
        return peak > 0
    except Exception:
        return False


def find_wake_model() -> Optional[Path]:
    candidates = []
    try:
        base = os.environ.get("APPDATA")
        if base:
            candidates.append(Path(base) / "QPet" / "models" / "hi_vivian.onnx")
    except Exception:
        pass
    try:
        candidates.append(Path(__file__).resolve().parent / "models" / "hi_vivian.onnx")
    except Exception:
        pass
    for p in candidates:
        if p.exists():
            return p
    return None


def wake_templates_path() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) / "QPet" if base else Path.home() / ".qpet"
    return root / "models" / "wake_templates.json"


def load_wake_templates():
    try:
        data = json.loads(wake_templates_path().read_text("utf-8"))
        templates = data.get("templates") or []
        threshold = data.get("threshold")
        if templates and threshold:
            return templates, float(threshold)
    except Exception:
        pass
    return [], None


def save_wake_templates(templates, threshold) -> bool:
    try:
        p = wake_templates_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "version": 1,
            "threshold": round(float(threshold), 4),
            "templates": [[[round(v, 3) for v in f] for f in t] for t in templates],
        }, ensure_ascii=False), "utf-8")
        return True
    except Exception:
        return False


class ModelAPIClient:

    def __init__(self, endpoint: str = "", api_key: str = "", model: str = "",
                 stt_model: str = ""):
        self.endpoint = (endpoint or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self.stt_model = (stt_model or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.endpoint)

    def chat(self, messages: list, timeout: int = 20) -> str:
        if not self.configured:
            raise RuntimeError("模型 API 未配置")
        body = json.dumps({"model": self.model or "gpt-4o-mini",
                           "messages": messages,
                           "max_tokens": 120}).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint + "/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.api_key},
            method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return str(data["choices"][0]["message"]["content"]).strip()

    def test_connection(self, timeout: int = 8) -> tuple:
        """发起一次最小对话请求验证配置，返回 (是否成功, 描述文本)。"""
        t0 = time.time()
        try:
            reply = self.chat([{"role": "user", "content": "ping"}],
                              timeout=timeout)
            ms = (time.time() - t0) * 1000
            name = self.model or "gpt-4o-mini"
            tag = "，回复:%s" % reply[:12] if reply else ""
            return True, "连接成功（%s，%.0f ms%s）" % (name, ms, tag)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "ignore")[:120]
            except Exception:
                detail = ""
            return False, "HTTP %s %s" % (e.code, detail or e.reason)
        except Exception as e:
            return False, str(e)[:120]

    def transcribe(self, wav_path, timeout: int = 25) -> str:
        if not self.configured:
            raise RuntimeError("模型 API 未配置")
        boundary = "----QPetBoundary" + uuid.uuid4().hex
        fields = {"model": self.stt_model or "whisper-1"}
        body = bytearray()
        for k, v in fields.items():
            body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                     % (boundary, k, v)).encode("utf-8")
        fname = Path(wav_path).name
        body += ("--%s\r\nContent-Disposition: form-data; name=\"file\"; "
                 "filename=\"%s\"\r\nContent-Type: audio/wav\r\n\r\n"
                 % (boundary, fname)).encode("utf-8")
        body += Path(wav_path).read_bytes()
        body += ("\r\n--%s--\r\n" % boundary).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint + "/audio/transcriptions", data=bytes(body),
            headers={"Content-Type": "multipart/form-data; boundary=" + boundary,
                     "Authorization": "Bearer " + self.api_key},
            method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return str(data.get("text", "")).strip()

    def pet_reply(self, user_text: str, timeout: int = 20) -> str:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]
        return self.chat(messages, timeout)


class VivianWakeEngine:

    def __init__(self):
        self.floors = None
        self.noise_floor = RMS_FLOOR_INIT
        self._feats = []
        self._env = []
        self._speech = []
        self._in_cand = False
        self._sil_ms = 0
        self.templates = []
        self.dtw_threshold = None

    def _analyze(self, buf: bytes) -> tuple:
        rms = _frame_rms(buf)
        energy = _band_energies(buf)
        if self.floors is None:
            self.floors = list(energy)
        active = 0
        for e, fl in zip(energy, self.floors):
            if e > fl * BAND_SNR_GATE and e > MIN_BAND_ENERGY:
                active += 1
        speech = (active >= VAD_MIN_BANDS
                  and _spectral_flatness(energy) < FLATNESS_MAX
                  and _frame_zcr(buf) < ZCR_MAX)
        return speech, active, energy, rms

    def observe_frame(self, buf: bytes) -> tuple:
        speech, active, energy, rms = self._analyze(buf)
        if not speech:
            self._adapt_noise(energy, rms)
        return speech, active

    def _adapt_noise(self, energy, rms):
        a = NOISE_EMA
        b = 1.0 - a
        self.floors = [fl * b + e * a for fl, e in zip(self.floors, energy)]
        self.noise_floor = self.noise_floor * b + rms * a

    def process_frame(self, buf: bytes) -> bool:
        speech, active, energy, _ = self._analyze(buf)
        if not speech:
            self._adapt_noise(energy, _frame_rms(buf))
        if speech:
            if not self._in_cand:
                self._in_cand = True
                self._feats = []
                self._env = []
                self._speech = []
                self._sil_ms = 0
            self._feats.append([math.log10(e + 1e-6) for e in energy])
            self._env.append(active)
            self._speech.append(True)
            self._sil_ms = 0
        elif self._in_cand:
            self._feats.append([math.log10(e + 1e-6) for e in energy])
            self._env.append(active)
            self._speech.append(False)
            self._sil_ms += FRAME_MS
            if self._sil_ms >= CAND_END_SIL_MS or len(self._feats) * FRAME_MS >= CAND_MAX_MS:
                last = 0
                for i, s in enumerate(self._speech):
                    if s:
                        last = i
                self._feats = self._feats[:last + 2]
                self._env = self._env[:last + 2]
                self._speech = self._speech[:last + 2]
                hit = self.verify()
                self._in_cand = False
                self._feats = []
                self._env = []
                self._speech = []
                if hit:
                    return True
        return False

    def verify(self) -> bool:
        n = len(self._speech)
        if n == 0:
            return False
        dur_ms = n * FRAME_MS
        if not (CAND_MIN_MS <= dur_ms <= CAND_MAX_MS):
            return False
        voiced = sum(1 for s in self._speech if s) / n
        peaks = self._peaks()
        n_syl = len(peaks)
        score = 0.0
        if 3 <= n_syl <= 5:
            score += 1.0
        elif n_syl in (2, 6):
            score += 0.5
        if 0.5 <= dur_ms / 1000.0 <= 1.9:
            score += 1.0
        if voiced >= 0.55:
            score += 1.0
        elif voiced >= 0.45:
            score += 0.5
        if len(peaks) >= 2:
            gaps = [peaks[i + 1][0] - peaks[i][0] for i in range(len(peaks) - 1)]
            rest = gaps[1:] if len(gaps) > 1 else gaps
            if gaps[0] <= 1.6 * (sum(rest) / len(rest) + 1):
                score += 0.5
        if self._first_syllable_bright(peaks):
            score += 0.5
        if self.templates:
            if not (2 <= n_syl <= 6 and voiced >= 0.35):
                return False
            seq = self._feature_sequence()
            best = min(self._dtw(seq, t) for t in self.templates)
            return best <= self.dtw_threshold
        return score >= WAKE_SCORE_GATE

    def _envelope(self):
        env = self._env
        sm = []
        for i in range(len(env)):
            lo = max(0, i - 1)
            hi = min(len(env), i + 2)
            sm.append(sum(env[lo:hi]) / (hi - lo))
        return sm

    def _peaks(self):
        sm = self._envelope()
        peaks = []
        for i, v in enumerate(sm):
            if v < SYL_MIN_ENV:
                continue
            if i > 0 and sm[i - 1] > v:
                continue
            if i + 1 < len(sm) and (sm[i + 1] > v or sm[i + 1] == v):
                continue
            if peaks and i - peaks[-1][0] <= SYL_MERGE_FRAMES:
                if v > peaks[-1][1]:
                    peaks[-1] = (i, v)
                continue
            peaks.append((i, v))
        return peaks

    def _first_syllable_bright(self, peaks) -> bool:
        if not peaks:
            first_end = 3
        else:
            first_end = peaks[0][0] + 2
        seg = self._feats[:max(1, first_end)]
        total = 0.0
        top = 0.0
        for f in seg:
            s = sum(f)
            if s <= 0:
                continue
            total += s
            top += f[-1] + f[-2]
        if total <= 0:
            return False
        return (top / total) >= 0.12

    @staticmethod
    def _norm_frame(f):
        m = sum(f) / len(f)
        return [x - m for x in f]

    def _feature_sequence(self):
        return [self._norm_frame(f) for f in self._feats]

    @classmethod
    def features_from_frames(cls, frames) -> list:
        feats = []
        for buf in frames:
            energy = _band_energies(buf)
            feats.append(cls._norm_frame([math.log10(e + 1e-6) for e in energy]))
        return feats

    @staticmethod
    def _dist(u, v):
        s = 0.0
        for x, y in zip(u, v):
            d = x - y
            s += d * d
        return math.sqrt(s)

    @classmethod
    def _dtw(cls, a, b) -> float:
        n, m = len(a), len(b)
        if n == 0 or m == 0:
            return 1e9
        prev = [0.0] * m
        for j in range(m):
            d = cls._dist(a[0], b[j])
            prev[j] = d if j == 0 else prev[j - 1] + d
        cur = [0.0] * m
        for i in range(1, n):
            cur[0] = prev[0] + cls._dist(a[i], b[0])
            for j in range(1, m):
                d = cls._dist(a[i], b[j])
                cur[j] = d + min(prev[j], cur[j - 1], prev[j - 1])
            prev, cur = cur, prev
        return prev[m - 1] / (n + m)


def compute_template_threshold(templates) -> float:
    ds = []
    for i in range(len(templates)):
        for j in range(i + 1, len(templates)):
            ds.append(VivianWakeEngine._dtw(templates[i], templates[j]))
    base = sum(ds) / len(ds) if ds else 0.18
    return base * 1.9 + 0.08


class OpenWakeWordEngine:

    def __init__(self, model_path: Path, threshold: float = 0.5):
        from openwakeword.model import Model
        self.model = Model(wakeword_model_paths=[str(model_path)],
                           inference_framework="onnx")
        self.threshold = threshold

    def process_frame(self, buf: bytes) -> bool:
        import numpy as np
        frame = np.frombuffer(buf, dtype=np.int16)
        scores = self.model.predict(frame)
        for score in scores.values():
            if score >= self.threshold:
                self.model.reset()
                return True
        return False


class VoiceService:

    def __init__(self, post_fn: Callable, on_wake: Callable,
                 on_reply: Optional[Callable] = None,
                 api: Optional[ModelAPIClient] = None,
                 cooldown_s: float = DEFAULT_COOLDOWN_S,
                 log_fn=None, on_status=None, on_cal=None):
        self._post = post_fn
        self._on_wake = on_wake
        self._on_reply = on_reply
        self._api = api
        self._cooldown = max(3.0, float(cooldown_s))
        self._log = log_fn or (lambda *a, **k: None)
        self._on_status = on_status
        self._on_cal = on_cal

        self._thread = None
        self._stop_evt = threading.Event()
        self._stream = None
        self._last_wake = 0.0
        self._state = "idle"
        self._cal_pending = False
        self._cal_target = 3
        self._history = []
        self._history_ts = 0.0

        model = find_wake_model()
        if model is not None:
            try:
                self._engine = OpenWakeWordEngine(model)
                self.engine_name = "openwakeword:" + model.name
            except Exception as e:
                self._log("openwakeword 加载失败，回退本地引擎: %s" % e)
                self._engine = self._make_local_engine()
        else:
            self._engine = self._make_local_engine()
        self.calibratable = isinstance(self._engine, VivianWakeEngine)

    def _make_local_engine(self):
        eng = VivianWakeEngine()
        templates, threshold = load_wake_templates()
        if templates and threshold:
            eng.templates = templates
            eng.dtw_threshold = threshold
            self.engine_name = "vivian-dtw"
        else:
            self.engine_name = "vivian-rhythm"
        return eng

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_api(self, api):
        """热更新模型 API 客户端（设置保存后无需重启语音流即可生效）"""
        self._api = api
        self._history = []
        self._history_ts = 0.0
        self._log("模型 API 已更新 (configured=%s)"
                  % bool(api and api.configured))

    def start(self) -> bool:
        if self.running:
            return True
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="qpet-voice")
        self._thread.start()
        return True

    def stop(self, join_s: float = 2.0):
        self._stop_evt.set()
        self._cal_pending = False
        stream = self._stream
        if stream is not None:
            try:
                stream.abort()
            except Exception:
                pass
        t = self._thread
        if t is not None and t.is_alive() and join_s > 0:
            t.join(timeout=join_s)
        self._thread = None

    def calibrate(self, count: int = 3) -> bool:
        if not self.running or not self.calibratable:
            return False
        self._cal_target = max(2, int(count))
        self._cal_pending = True
        return True

    def _status(self, stage: str, msg: str):
        if self._on_status is not None:
            self._post(lambda: self._on_status(stage, msg))

    def _cal_event(self, ev: tuple):
        if self._on_cal is not None:
            self._post(lambda: self._on_cal(ev))

    def _detect_with_retry(self):
        last = "未检测到麦克风"
        for i in range(MIC_DETECT_ATTEMPTS):
            if self._stop_evt.is_set():
                return False, "已停止"
            ok, name = detect_microphone()
            if ok:
                return True, name
            last = name
            if i < MIC_DETECT_ATTEMPTS - 1:
                self._log("麦克风暂不可用(%s)，%.0f 秒后重试 %d/%d"
                          % (name, MIC_DETECT_RETRY_S, i + 1, MIC_DETECT_ATTEMPTS - 1))
                self._stop_evt.wait(MIC_DETECT_RETRY_S)
        return False, last

    def _run(self):
        try:
            import sounddevice as sd
        except Exception:
            self._log("sounddevice 不可用，语音线程退出")
            self._status("fail", "音频库不可用")
            return
        ok, name = self._detect_with_retry()
        if not ok:
            self._log("语音启动失败: %s" % name)
            self._status("fail", name)
            return
        if not probe_capture():
            self._log("麦克风可枚举但录音失败（可能被系统隐私设置禁用）")
            self._status("fail", "录音被系统隐私设置阻止")
            return
        try:
            stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                blocksize=FRAME_SAMPLES)
            stream.start()
        except Exception as e:
            self._log("麦克风打开失败: %s" % e)
            self._status("fail", "麦克风打开失败")
            return
        self._stream = stream
        self._log("语音监听已启动 (engine=%s, api=%s, mic=%s)"
                  % (self.engine_name, bool(self._api and self._api.configured), name))
        self._status("ok", name)
        try:
            while not self._stop_evt.is_set():
                if self._cal_pending:
                    self._cal_pending = False
                    self._cal_loop(stream)
                    continue
                self._listen(stream)
        finally:
            self._stream = None
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
            self._state = "idle"

    def _listen(self, stream):
        utter = bytearray()
        silence_ms = 0
        utter_ms = 0
        discard_ms = 0
        capturing = False
        while not self._stop_evt.is_set():
            if self._cal_pending:
                return
            try:
                data, _ = stream.read(FRAME_SAMPLES)
            except Exception as e:
                self._log("音频读取失败: %s" % e)
                return
            buf = bytes(data)
            if capturing:
                if discard_ms > 0:
                    discard_ms -= FRAME_MS
                    continue
                utter += buf
                utter_ms += FRAME_MS
                rms = _frame_rms(buf)
                threshold = max(getattr(self._engine, "noise_floor", 120.0) * 5.0,
                                250.0)
                silence_ms = 0 if rms > threshold else silence_ms + FRAME_MS
                if silence_ms >= UTTER_SILENCE_END_MS or utter_ms >= UTTER_MAX_MS:
                    self._finish_utterance(utter, utter_ms)
                    capturing = False
                    utter = bytearray()
                    utter_ms = 0
                    silence_ms = 0
                continue
            woken = self._engine.process_frame(buf)
            if woken:
                now = time.time()
                if now - self._last_wake < self._cooldown:
                    continue
                self._last_wake = now
                self._state = "awake"
                self._post(self._on_wake)
                if self._api is not None and self._api.configured \
                        and self._on_reply is not None:
                    capturing = True
                    discard_ms = ECHO_DISCARD_MS
                    utter = bytearray()
                    utter_ms = 0
                    silence_ms = 0

    def _cal_loop(self, stream):
        self._log("进入唤醒词校准模式")
        collected = []
        eng = self._engine if isinstance(self._engine, VivianWakeEngine) \
            else VivianWakeEngine()
        for k in range(self._cal_target):
            self._cal_event(("ask", k + 1, self._cal_target))
            frames = self._record_one(stream, eng)
            if self._stop_evt.is_set():
                return
            if frames is None:
                self._cal_event(("fail", "没听清，请靠近麦克风、放慢语速再试"))
                self._log("校准失败：录音无效")
                return
            collected.append(frames)
        templates = [VivianWakeEngine.features_from_frames(fs) for fs in collected]
        threshold = compute_template_threshold(templates)
        if not save_wake_templates(templates, threshold):
            self._cal_event(("fail", "模板保存失败"))
            return
        if isinstance(self._engine, VivianWakeEngine):
            self._engine.templates = templates
            self._engine.dtw_threshold = threshold
            self.engine_name = "vivian-dtw"
        self._log("唤醒词校准完成 (threshold=%.3f)" % threshold)
        self._cal_event(("done", self._cal_target))

    def _record_one(self, stream, eng, timeout_s: float = 15.0):
        frames = []
        speech_flags = []
        speech_ms = 0
        sil_ms = 0
        started = False
        t0 = time.time()
        while not self._stop_evt.is_set():
            if time.time() - t0 > timeout_s:
                return None
            try:
                data, _ = stream.read(FRAME_SAMPLES)
            except Exception:
                return None
            buf = bytes(data)
            speech, _ = eng.observe_frame(buf)
            if not started:
                if speech:
                    started = True
                    frames.append(buf)
                    speech_flags.append(True)
                    speech_ms += FRAME_MS
                continue
            frames.append(buf)
            speech_flags.append(speech)
            if speech:
                speech_ms += FRAME_MS
                sil_ms = 0
            else:
                sil_ms += FRAME_MS
                if sil_ms >= CAND_END_SIL_MS or speech_ms + sil_ms >= 3000:
                    break
        if self._stop_evt.is_set():
            return None
        if not (400 <= speech_ms <= 2600):
            return None
        last_speech = 0
        for i, s in enumerate(speech_flags):
            if s:
                last_speech = i
        return frames[:last_speech + 2]

    def _finish_utterance(self, utter: bytearray, ms: int):
        if ms < UTTER_MIN_MS:
            return
        self._state = "idle"
        wav_path = None
        try:
            base = os.environ.get("APPDATA") or str(Path.home())
            tmpdir = Path(base) / "QPet"
            tmpdir.mkdir(parents=True, exist_ok=True)
            wav_path = tmpdir / "utterance.wav"
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(bytes(utter))
            text = self._api.transcribe(wav_path)
            if not text:
                self._log("转写结果为空，忽略本次发言")
                return
            self._log("识别: %s" % text)
        except Exception as e:
            self._log("语音转写失败: %s" % e)
            self._post(lambda: self._on_reply(
                "呜……转写接口出了点问题：%s" % str(e)[:80]))
            return
        finally:
            if wav_path is not None:
                try:
                    wav_path.unlink()
                except Exception:
                    pass
        # —— 带上下文的多轮对话 ——
        now = time.time()
        if now - self._history_ts > HISTORY_TTL_S:
            self._history = []
        try:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            messages += self._history[-HISTORY_MAX_MSGS:]
            messages.append({"role": "user", "content": text})
            reply = self._api.chat(messages)
            self._history.append({"role": "user", "content": text})
            self._history.append({"role": "assistant", "content": reply})
            self._history = self._history[-HISTORY_MAX_MSGS:]
            self._history_ts = now
            final_reply = reply or random.choice(FALLBACK_REPLIES)
        except Exception as e:
            self._log("模型回复失败: %s" % e)
            final_reply = "呜……模型接口出了点问题：%s" % str(e)[:80]
        self._post(lambda: self._on_reply(final_reply))


def pick_response() -> str:
    return random.choice(WAKE_RESPONSES)
