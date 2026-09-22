import argparse
import json
import logging
import os
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Iterable, Optional

logger = logging.getLogger(__name__)

STATE_MAP = {
    "idle":       ("idle",       False, 0,    "待机中 🪑"),
    "thinking":   ("thinking",   False, 0,    "思考中… 🤔"),
    "working":    ("working",    False, 0,    "工作中… 🛠️"),
    "reviewing":  ("sweeping",   False, 0,    "清理中… 🧹"),
    "sweeping":   ("sweeping",   False, 0,    "清理中… 🧹"),
    "done":       ("happy",      True,  2.5,  "完成！🎉"),
    "happy":      ("happy",      True,  2.5,  "完成！🎉"),
    "error":      ("error",      True,  45.0, "出错了… 💥"),
    "waiting":    ("waiting",    False, 0,    "等待授权 ✋"),
    "talking":    ("talking",    False, 0,    "回应中… 💬"),
    "needsinput": ("needsinput", False, 0,   "等你回复 ❓"),
    "attention":  ("attention",  True,  15.0, "提醒 🔔"),
    "greet":      ("greet",      True,  2.0,  "你好！👋"),
    "juggling":   ("juggling",   False, 0,    "多任务中… 🤹"),
    "loafing":    ("loafing",    False, 0,    "摸鱼中… 🍦"),
    "roam":       ("roam",       False, 0,    "闲逛中… 🚶"),
    "sleeping":   ("sleeping",   False, 0,    "睡觉中… 😴"),
    "sad":        ("sad",        True,  8.0,  "委屈… 😢"),
}

STATE_PRIORITY = {
    "error":      8,
    "needsinput": 7,
    "sweeping":   6,
    "reviewing":  6,
    "attention":  5,
    "waiting":    4,
    "juggling":   4,
    "working":    3,
    "thinking":   2,
    "talking":    2,
    "idle":       1,
    "roam":       1,
    "loafing":    1,
    "sleeping":   0,

    "happy":      -1,
    "greet":      -1,
    "done":       -1,
}

ONESHOT_STATES = {"attention", "happy", "greet", "error", "done"}

TRANSIENT_STATES = {"happy", "greet", "attention"}

BUBBLE_MIN_DISPLAY_S = 1.5

LOAF_GAP_S = 5.0

LOAF_BACK_IDLE_S = 30.0

IDLE_LOAF_S = 60.0
IDLE_ROAM_S = 180.0
IDLE_SLEEP_S = 300.0

GREET_DEBOUNCE_S = 30 * 60

GREET_PENDING_WINDOW_S = 5 * 60

BUBBLE_ONLINE = "DesktopBuddy 上线，开始盯任务啦！"

DEFAULT_POLL_INTERVAL = 0.1

DEFAULT_STATUS_PATH = "~/.hatch-pet/status.json"

DEFAULT_EVENTS_PATH = "~/.hatch-pet/events.jsonl"

def get_priority(state: str) -> int:
    return STATE_PRIORITY.get(state, 0)

WORK_START_EVENTS = {"UserPromptSubmit", "PreToolUse", "PostToolUse",
                     "SubagentStart", "TaskStarted"}

DONE_EVENTS = {"Stop"}

ERROR_EVENTS = {"StopFailure", "PostToolUseFailure", "ApiError"}

EVENT_STATE_MAP = {
    "SessionStart":         (None,        False, 0,    None),
    "UserPromptSubmit":     ("thinking",  False, 0,    "思考中… 🤔"),
    "PreToolUse":           ("working",   False, 0,    None),
    "PostToolUse":          ("working",   False, 0,    None),
    "SubagentStart":        ("juggling",  False, 0,    "多任务中… 🤹"),
    "SubagentStop":         ("working",   False, 0,    None),
    "Stop":                 ("done",      True,  2.5,  "完成！🎉"),
    "StopFailure":          ("error",     True,  45.0, "出错了… 💥"),
    "PostToolUseFailure":   ("error",     True,  45.0, "出错了… 💥"),
    "ApiError":             ("error",     True,  45.0, "出错了… 💥"),
    "Notification":         ("needsinput", False, 0,   "等你回复 ❓"),
    "Elicitation":          ("needsinput", False, 0,   "等你回复 ❓"),
    "PermissionRequest":   ("waiting",    False, 0,    "等待授权 ✋"),
    "ExitPlanMode":         ("needsinput", False, 0,   "等你回复 ❓"),
    "Sad":                  ("sad",       True,  8.0,  "委屈… 😢"),
    "SessionEnd":           ("idle",      False, 0,    None),
    "PreCompact":           ("sweeping",  False, 0,    "清理中… 🧹"),
    "PostCompact":          ("thinking",  False, 0,    None),

    "AutoWorking":          ("working",   False, 0,    None),
    "AutoIdle":             ("idle",      False, 0,    None),
    "AutoThinking":         ("thinking",  False, 0,    "思考中…"),
    "AutoDone":             ("done",      True,  2.5,  "完成！"),
}

class EventRecorder:

    def __init__(
        self,
        events_path: str = DEFAULT_EVENTS_PATH,
        on_event: Optional[Callable[[dict], None]] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ):
        self.path = Path(events_path).expanduser().resolve()
        self.on_event = on_event
        self.poll_interval = poll_interval
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._file = None
        self._last_pos: int = 0
        self._recent_events: deque = deque(maxlen=100)

        self.path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def recent_events(self) -> list:
        return list(self._recent_events)

    def start(self):
        if self._running:
            return
        self._running = True

        try:
            self._file = open(self.path, "r", encoding="utf-8")
            self._file.seek(0, os.SEEK_END)
            self._last_pos = self._file.tell()
        except OSError:
            self._file = None
        self._thread = threading.Thread(
            target=self._read_loop,
            name="event-recorder",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"EventRecorder 已启动: {self.path}")

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._file:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None
        logger.info("EventRecorder 已停止")

    def _read_loop(self):
        while self._running:
            try:
                self._drain_new_lines()
            except Exception as e:
                logger.debug(f"EventRecorder 读取异常: {e}")
            time.sleep(self.poll_interval)

    def _drain_new_lines(self):
        if not self._file:
            return
        try:

            current_size = os.path.getsize(self.path) if self.path.exists() else 0
            if current_size < self._last_pos:
                self._file.seek(0, os.SEEK_END)
                self._last_pos = self._file.tell()

            self._file.seek(self._last_pos)
            lines = self._file.readlines()
            self._last_pos = self._file.tell()
        except (OSError, ValueError):

            if self._file:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None
                try:
                    self._file = open(self.path, "r", encoding="utf-8")
                    self._file.seek(0, os.SEEK_END)
                    self._last_pos = self._file.tell()
                except OSError:
                    pass
            return

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                self._recent_events.append(event)
                if self.on_event:
                    self.on_event(event)
            except json.JSONDecodeError:
                logger.debug(f"无效事件行: {line[:80]}")

class _StatusSource:

    def __init__(self, path: str, name: Optional[str] = None):
        self.path = Path(path).expanduser().resolve()
        self.name = name or self.path.stem
        self.last_state: Optional[str] = None
        self.last_tool: Optional[str] = None
        self.last_msg: Optional[str] = None
        self.last_mtime: float = 0.0

        self.last_event_time: float = 0.0

        self.last_event_name: Optional[str] = None

        self.last_data: Optional[dict] = None

        self.greet_pending: float = 0.0

class StatusWatcher:

    def __init__(
        self,
        status_path: "str | Iterable[str]" = DEFAULT_STATUS_PATH,
        events_path: str = DEFAULT_EVENTS_PATH,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        on_state_change: Optional[Callable[[str], None]] = None,
        on_bubble: Optional[Callable[[str, str], None]] = None,
        on_tool_change: Optional[Callable[[Optional[str]], None]] = None,
    ):
        if isinstance(status_path, str):
            paths = [p.strip() for p in status_path.split(",") if p.strip()]
        else:
            paths = [p.strip() for p in status_path if p and p.strip()]

        self.sources: list[_StatusSource] = [_StatusSource(p) for p in paths]
        self.poll_interval = poll_interval
        self.on_state_change = on_state_change
        self.on_bubble = on_bubble
        self.on_tool_change = on_tool_change

        self.event_recorder = EventRecorder(
            events_path=events_path,
            on_event=self._on_event,
            poll_interval=poll_interval,
        )

        self._thread: Optional[threading.Thread] = None
        self._running = False

        self._aggregate_state: Optional[str] = None
        self._aggregate_tool: Optional[str] = None

        self._transient_state: Optional[str] = None
        self._transient_until: float = 0.0
        self._transient_anim: Optional[str] = None

        self._oneshot_until: float = 0.0
        self._oneshot_anim: Optional[str] = None

        self._bubble_until: float = 0.0
        self._bubble_msg: Optional[str] = None

        self._last_greet_at: dict = {}

        for src in self.sources:
            src.path.parent.mkdir(parents=True, exist_ok=True)

    def start(self):
        if self._running:
            logger.warning("StatusWatcher 已在运行")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="status-watcher-v2",
            daemon=True,
        )
        self._thread.start()
        self.event_recorder.start()
        logger.info(
            f"StatusWatcher v2 已启动，监听 {len(self.sources)} 个源 + 事件流"
        )

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.event_recorder.stop()
        logger.info("StatusWatcher v2 已停止")

    @property
    def is_running(self) -> bool:
        return self._running

    def _on_event(self, event: dict):
        event_name = event.get("event", "")
        source = event.get("source", "default")
        tool = event.get("tool")
        msg = event.get("msg")
        ts = event.get("ts", time.time())

        logger.debug(f"收到事件: {event_name} (source={source}, tool={tool}, msg={msg})")

        src = self._find_source_by_name(source) or self.sources[0] if self.sources else None
        if src:
            src.last_event_name = event_name
            src.last_event_time = ts

        if event_name == "SessionStart":
            if src:
                src.greet_pending = ts
                logger.debug(f"源 {src.name} 标记 greetPending")

            self._recompute_aggregate()
            return

        if event_name == "UserPromptSubmit" and src and src.greet_pending:
            now = time.time()
            pending_age = now - src.greet_pending
            last_greet = self._last_greet_at.get(src.name, 0)
            recently_greeted = (now - last_greet) < GREET_DEBOUNCE_S

            if pending_age < GREET_PENDING_WINDOW_S and not recently_greeted:

                src.greet_pending = 0.0
                self._last_greet_at[src.name] = now
                greet_msg = f"👋 {src.name} 新会话，你好！"
                self._set_transient("greet", 2.0)
                self._show_bubble(greet_msg, "greet")
                logger.debug(f"源 {src.name} 触发 greet")
                self._recompute_aggregate()
                return
            else:

                src.greet_pending = 0.0

        mapped = EVENT_STATE_MAP.get(event_name)
        if mapped is None:
            return

        state, is_oneshot, duration_s, bubble_msg = mapped

        if msg:
            bubble_msg = msg

        if src:
            src.last_state = state

        if state == "working" and tool:
            if src:
                src.last_tool = tool

        if is_oneshot and duration_s > 0:
            anim_name = STATE_MAP.get(state, (state,))[0]
            self._set_transient(anim_name, duration_s)

        if bubble_msg:
            self._show_bubble(bubble_msg, state)

        self._recompute_aggregate()

    def _find_source_by_name(self, name: str) -> Optional[_StatusSource]:
        for src in self.sources:
            if src.name == name:
                return src
        return None

    def _set_transient(self, anim_name: str, duration_s: float):
        self._transient_anim = anim_name
        self._transient_state = anim_name
        self._transient_until = time.time() + duration_s
        logger.debug(f"设置短暂态: {anim_name} ({duration_s}s)")

    def _poll_loop(self):
        while self._running:
            try:
                self._check_all_sources()
                self._check_transient_expiry()
                self._check_loafing_synthesis()
                self._recompute_aggregate()
            except Exception as e:
                logger.debug(f"轮询异常: {e}")
            time.sleep(self.poll_interval)

    def _check_all_sources(self):
        for src in self.sources:
            self._check_one(src)

    def _check_one(self, src: _StatusSource):
        path = src.path
        if not path.exists():
            if src.last_state is not None:
                logger.debug(f"源 {src.name} 文件消失")
                src.last_state = None
                src.last_tool = None
                src.last_msg = None
                src.last_data = None
            return

        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return

        if mtime == src.last_mtime:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        src.last_mtime = mtime
        src.last_data = data
        self._process_source_status(src, data)

    def _process_source_status(self, src: _StatusSource, data: dict):
        raw_state = data.get("state", "idle")
        tool = data.get("tool")
        msg = data.get("msg")

        if raw_state != src.last_state:
            logger.debug(f"源 {src.name}: {src.last_state} → {raw_state}")

            src.last_event_time = time.time()
            src.last_event_name = f"status:{raw_state}"

        src.last_state = raw_state
        src.last_tool = tool
        src.last_msg = msg

        anim_name, is_oneshot, duration, _ = STATE_MAP.get(raw_state, ("idle", False, 0, ""))
        if is_oneshot and duration > 0:
            self._set_oneshot(anim_name, duration)

        default_bubble = STATE_MAP.get(raw_state, ("", False, 0, ""))[3]
        bubble_msg = msg or default_bubble
        if bubble_msg and bubble_msg != self._bubble_msg:
            self._show_bubble(bubble_msg, raw_state)

    def _set_oneshot(self, anim_name: str, duration_s: float):
        self._oneshot_anim = anim_name
        self._oneshot_until = time.time() + duration_s
        logger.debug(f"设置 oneshot: {anim_name} ({duration_s}s)")

    def _in_transient(self) -> bool:
        return time.time() < self._transient_until

    def _in_oneshot(self) -> bool:
        return time.time() < self._oneshot_until

    def _check_transient_expiry(self):
        if not self._in_transient() and self._transient_anim is not None:
            logger.debug(f"短暂态到期: {self._transient_anim}")
            self._transient_anim = None
            self._transient_state = None
            self._transient_until = 0.0

    def _check_loafing_synthesis(self):
        now = time.time()
        for src in self.sources:

            if src.last_state == "loafing" and src.last_event_name == "synthesized:loafing":
                gap = now - src.last_event_time
                if gap > LOAF_BACK_IDLE_S:
                    logger.debug(
                        f"源 {src.name} 合成态 loafing 超时，回退到 idle "
                        f"(gap={gap:.1f}s)"
                    )
                    src.last_state = "idle"
                    src.last_event_name = "synthesized:idle"
                    src.last_event_time = now
                continue

            if src.last_state != "working":
                continue
            if src.last_event_name not in ("PostToolUse", "SubagentStop", "status:working"):
                continue
            gap = now - src.last_event_time
            if gap > LOAF_GAP_S:

                if src.last_state != "loafing":
                    logger.debug(
                        f"源 {src.name} 合成 loafing: working → loafing "
                        f"(gap={gap:.1f}s, last_event={src.last_event_name})"
                    )
                    src.last_state = "loafing"
                    src.last_event_name = "synthesized:loafing"

    def _check_oneshot_expiry(self):
        if not self._in_oneshot() and self._oneshot_anim is not None:
            logger.debug(f"Oneshot 到期: {self._oneshot_anim}")
            self._oneshot_anim = None
            self._oneshot_until = 0.0

    def _recompute_aggregate(self):
        self._check_oneshot_expiry()

        new_anim = self._compute_aggregate_anim()

        if new_anim != self._aggregate_state:
            logger.debug(f"聚合状态切换: {self._aggregate_state} → {new_anim}")
            self._aggregate_state = new_anim
            if self.on_state_change:
                try:
                    self.on_state_change(new_anim)
                except Exception as e:
                    logger.error(f"on_state_change 回调异常: {e}")

        top_src = self._pick_top_source()
        new_tool = top_src.last_tool if top_src else None
        if new_tool != self._aggregate_tool:
            self._aggregate_tool = new_tool
            if self.on_tool_change:
                try:
                    self.on_tool_change(new_tool)
                except Exception as e:
                    logger.error(f"on_tool_change 回调异常: {e}")

    def _compute_aggregate_anim(self) -> str:
        now = time.time()

        if self._in_transient() and self._transient_anim:
            return self._transient_anim

        if self._in_oneshot() and self._oneshot_anim:
            return self._oneshot_anim

        counts = self._count_states()

        if counts.get("waiting", 0) > 0:
            return STATE_MAP["waiting"][0]

        if counts.get("error", 0) > 0:
            return STATE_MAP["error"][0]

        if counts.get("needsinput", 0) > 0:
            return STATE_MAP["needsinput"][0]

        if counts.get("sweeping", 0) > 0:
            return STATE_MAP["sweeping"][0]

        if counts.get("juggling", 0) > 0:
            return STATE_MAP["juggling"][0]

        if counts.get("working", 0) > 0:
            return STATE_MAP["working"][0]

        if counts.get("thinking", 0) > 0:
            return STATE_MAP["thinking"][0]

        if counts.get("talking", 0) > 0:
            return STATE_MAP["talking"][0]

        if counts.get("loafing", 0) > 0:
            return STATE_MAP["loafing"][0]

        if counts.get("roam", 0) > 0:
            return STATE_MAP["roam"][0]

        idle_level = self._idle_escalation_state()
        if idle_level != "idle":
            return STATE_MAP[idle_level][0]

        return STATE_MAP["idle"][0]

    def _count_states(self) -> dict:
        counts: dict = {}
        for src in self.sources:
            state = src.last_state
            if state is None or state in ONESHOT_STATES:
                continue
            counts[state] = counts.get(state, 0) + 1
        return counts

    def _idle_escalation_state(self) -> str:
        now = time.time()
        last_event = 0.0
        for src in self.sources:
            if src.last_state not in (None, "idle"):
                return "idle"
            if src.last_event_time and src.last_event_time > last_event:
                last_event = src.last_event_time

        if last_event == 0.0:
            return "idle"

        elapsed = now - last_event
        if elapsed >= IDLE_SLEEP_S:
            return "sleeping"
        elif elapsed >= IDLE_ROAM_S:
            return "roam"
        elif elapsed >= IDLE_LOAF_S:
            return "loafing"
        else:
            return "idle"

    def _pick_top_source(self) -> Optional[_StatusSource]:
        top = None
        top_prio = -1
        for src in self.sources:
            if src.last_state is None or src.last_state in ONESHOT_STATES:
                continue
            prio = get_priority(src.last_state)
            if prio > top_prio:
                top_prio = prio
                top = src
        return top

    def _show_bubble(self, msg: str, state: str):
        now = time.time()
        if now < self._bubble_until:
            logger.debug(f"气泡锁中，跳过: {msg}")
            return
        if self.on_bubble:
            try:
                self.on_bubble(msg, state)
            except Exception as e:
                logger.error(f"on_bubble 回调异常: {e}")
        self._bubble_until = now + BUBBLE_MIN_DISPLAY_S
        self._bubble_msg = msg

    def snapshot(self) -> dict:
        return {
            "aggregate_state": self._aggregate_state,
            "aggregate_tool": self._aggregate_tool,
            "transient_state": self._transient_anim if self._in_transient() else None,
            "oneshot_state": self._oneshot_anim if self._in_oneshot() else None,
            "counts": self._count_states(),
            "idle_escalation": self._idle_escalation_state(),
            "sources": [
                {
                    "name": s.name,
                    "state": s.last_state,
                    "tool": s.last_tool,
                    "msg": s.last_msg,
                    "last_event": s.last_event_name,
                    "last_event_time": s.last_event_time,
                }
                for s in self.sources
            ],
            "recent_events": self.event_recorder.recent_events[-5:],
        }

def create_watcher(
    status_path: "str | Iterable[str]" = DEFAULT_STATUS_PATH,
    events_path: str = DEFAULT_EVENTS_PATH,
    pet=None,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    auto_start: bool = True,
) -> StatusWatcher:
    watcher = StatusWatcher(
        status_path=status_path,
        events_path=events_path,
        poll_interval=poll_interval,
        on_state_change=lambda anim: (
            pet._switch_anim(anim) if pet else None
        ),
        on_bubble=lambda msg, state: (
            pet._show_bubble(msg, state) if pet and hasattr(pet, "_show_bubble") else None
        ),
        on_tool_change=lambda tool: None,
    )
    if auto_start:
        watcher.start()

        if pet and hasattr(pet, "_show_bubble"):
            try:
                pet._show_bubble(BUBBLE_ONLINE, "greet")
            except Exception:
                pass
    return watcher

def write_status(
    state: str,
    tool: Optional[str] = None,
    msg: Optional[str] = None,
    source: Optional[str] = None,
    status_path: str = DEFAULT_STATUS_PATH,
):
    if source and status_path == DEFAULT_STATUS_PATH:
        path = Path(f"~/.hatch-pet/status-{source}.json").expanduser()
    else:
        path = Path(status_path).expanduser()

    data = {
        "state": state,
        "tool": tool,
        "msg": msg,
        "source": source,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError as e:
        logger.error(f"写入状态文件失败: {e}")
        raise

def write_event(
    event: str,
    source: Optional[str] = None,
    tool: Optional[str] = None,
    msg: Optional[str] = None,
    events_path: str = DEFAULT_EVENTS_PATH,
):
    path = Path(events_path).expanduser()
    entry = {
        "event": event,
        "source": source or "default",
        "tool": tool,
        "msg": msg,
        "ts": time.time(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.error(f"写入事件文件失败: {e}")
        raise

def read_status(status_path: str = DEFAULT_STATUS_PATH) -> Optional[dict]:
    path = Path(status_path).expanduser()
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

def clear_status(status_path: str = DEFAULT_STATUS_PATH) -> bool:
    try:
        write_status(state="idle", msg=None, tool=None, status_path=status_path)
        return True
    except OSError:
        return False

def cli_status(args) -> int:
    if args.status_action == "set":
        if args.state not in STATE_MAP:
            logger.error(f"未知状态: {args.state}")
            logger.error(f"可用状态: {', '.join(STATE_MAP.keys())}")
            return 2
        write_status(
            state=args.state,
            tool=args.tool,
            msg=args.msg,
            source=args.source,
            status_path=args.status_path,
        )
        print(f"✅ 已写入状态: {args.state}"
              + (f" (tool={args.tool})" if args.tool else "")
              + (f" (source={args.source})" if args.source else ""))
        return 0

    if args.status_action == "get":
        data = read_status(args.status_path)
        if data is None:
            print(f"📭 状态文件不存在: {Path(args.status_path).expanduser()}")
            return 1
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    if args.status_action == "clear":
        ok = clear_status(args.status_path)
        print("✅ 已清空状态（写回 idle）" if ok else "❌ 清空失败")
        return 0 if ok else 1

    logger.error(f"未知子动作: {args.status_action}")
    return 2

def cli_event(args) -> int:
    if args.event_action == "emit":
        write_event(
            event=args.event,
            source=args.source,
            tool=args.tool,
            msg=args.msg,
            events_path=args.events_path,
        )
        if args.event == "SessionStart":
            print(f"✅ 已发送事件: {args.event} → 标记 greetPending（等首条 prompt 触发欢迎）")
        else:
            mapped = EVENT_STATE_MAP.get(args.event)
            if mapped and mapped[0]:
                state, is_oneshot, duration_s, bubble_msg = mapped
                print(f"✅ 已发送事件: {args.event} → 状态={state}"
                      + (f" (oneshot {duration_s}s)" if is_oneshot else "")
                      + (f" (bubble: {bubble_msg})" if bubble_msg else ""))
            else:
                print(f"✅ 已发送事件: {args.event}")
        return 0

    if args.event_action == "tail":
        path = Path(args.events_path).expanduser()
        if not path.exists():
            print(f"📭 事件文件不存在: {path}")
            return 1
        print(f"📜 最近事件 (tail {args.lines}):")
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines[-args.lines:]:
                    line = line.strip()
                    if line:
                        print(f"  {line}")
        except OSError:
            return 1
        return 0

    logger.error(f"未知子动作: {args.event_action}")
    return 2

def add_status_subparser(subparsers):
    p = subparsers.add_parser(
        "status",
        help="读写 AI agent 状态文件（持续态快照）",
    )
    p.add_argument("status_action", choices=["set", "get", "clear"])
    p.add_argument("--state", default="idle",
                   help=f"状态名，可选: {', '.join(STATE_MAP.keys())}")
    p.add_argument("--tool", default=None)
    p.add_argument("--msg", default=None)
    p.add_argument("--source", default=None,
                   help="来源标记；指定时写入 ~/.hatch-pet/status-<source>.json")
    p.add_argument("--status-path", default=DEFAULT_STATUS_PATH)
    p.set_defaults(func=cli_status)
    return p

def add_event_subparser(subparsers):
    p = subparsers.add_parser(
        "event",
        help="发送/查看 AI agent 事件流（事件驱动 oneshot/loafing）",
    )
    p.add_argument("event_action", choices=["emit", "tail"])
    p.add_argument("--event", default="SessionStart",
                   help="事件名 (emit 必填)，如: SessionStart, UserPromptSubmit, "
                        "PreToolUse, PostToolUse, SubagentStart, Stop, StopFailure, "
                        "Notification, PermissionRequest 等")
    p.add_argument("--tool", default=None, help="当前工具名 (如 grep, Edit, Bash)")
    p.add_argument("--msg", default=None, help="附加消息")
    p.add_argument("--source", default=None,
                   help="来源标记，如 reasonix, workbuddy, trae")
    p.add_argument("--events-path", default=DEFAULT_EVENTS_PATH)
    p.add_argument("--lines", type=int, default=20, help="tail 显示行数")
    p.set_defaults(func=cli_event)
    return p
