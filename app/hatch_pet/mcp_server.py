import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hatch_pet.status_watcher import (
    write_status,
    write_event,
    read_status,
    clear_status,
    STATE_MAP,
    EVENT_STATE_MAP,
    DEFAULT_STATUS_PATH,
    DEFAULT_EVENTS_PATH,
)

_auto_attached: bool = True
_auto_source: str = "auto"
_auto_last_activity: float = 0.0
_auto_lock = threading.Lock()
_auto_running: bool = False
_auto_daemon_thread: "threading.Thread | None" = None
_auto_phase: str = "idle"

def _auto_attach_daemon():
    global _auto_source, _auto_last_activity, _auto_running, _auto_phase

    while _auto_running:
        time.sleep(5)
        if not _auto_running:
            break

        with _auto_lock:
            now = time.time()
            gap = now - _auto_last_activity
            source = _auto_source

        if gap < 30:

            if _auto_phase in ("idle", "done"):

                write_event("AutoThinking", source=source, events_path=_events_path())
                _auto_phase = "thinking"
            elif _auto_phase == "thinking":

                write_event("AutoWorking", source=source, events_path=_events_path())
                _auto_phase = "working"

        else:

            if _auto_phase == "working":

                write_event("AutoDone", source=source, events_path=_events_path())
                _auto_phase = "done"
            elif _auto_phase == "done":

                write_event("AutoIdle", source=source, events_path=_events_path())
                _auto_phase = "idle"

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "desktop-buddy"
SERVER_VERSION = "1.0.2"

TOOLS = [
    {
        "name": "pet_emit_event",
        "description": (
            "发送事件到 DesktopBuddy 桌宠，触发状态联动。"
            "AI 助手在开始任务、使用工具、完成任务等时机调用。"
            "\n\n事件类型:\n"
            "  SessionStart     — 新会话开始（标记 greetPending）\n"
            "  UserPromptSubmit — 用户提交问题（触发 greet + thinking）\n"
            "  PreToolUse       — 工具调用前（→ working）\n"
            "  PostToolUse      — 工具调用后（→ working）\n"
            "  SubagentStart    — 子代理启动（→ juggling 多任务）\n"
            "  SubagentStop     — 子代理停止（→ working）\n"
            "  Stop             — 任务完成（→ done 庆祝动画）\n"
            "  StopFailure      — 任务失败（→ error 45秒）\n"
            "  Notification     — 需要用户输入（→ needsinput）\n"
            "  PermissionRequest — 等待授权（→ waiting）\n"
            "  PreCompact       — 上下文压缩（→ sweeping）\n"
            "  SessionEnd       — 会话结束（→ idle）"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "event": {
                    "type": "string",
                    "description": "事件名，如 SessionStart, UserPromptSubmit, PreToolUse, Stop 等",
                    "enum": list(EVENT_STATE_MAP.keys()),
                },
                "source": {
                    "type": "string",
                    "description": "来源标记，如 trae, reasonix, workbuddy（默认 trae）",
                    "default": "trae",
                },
                "tool": {
                    "type": "string",
                    "description": "当前工具名（PreToolUse/PostToolUse 时可选）",
                },
                "msg": {
                    "type": "string",
                    "description": "附加消息",
                },
            },
            "required": ["event"],
        },
    },
    {
        "name": "pet_set_status",
        "description": (
            "设置 DesktopBuddy 桌宠的持续状态。"
            "与 emit_event 不同，这是持续态快照（不会自动衰减），适合长时间保持某种状态。"
            "\n\n可用状态:\n"
            "  idle       — 待机\n"
            "  thinking   — 思考中\n"
            "  working    — 工作中\n"
            "  needsinput — 等待用户输入\n"
            "  waiting    — 等待授权\n"
            "  juggling   — 多任务中\n"
            "  sweeping   — 清理中\n"
            "  loafing    — 摸鱼中\n"
            "  sleeping   — 睡觉中\n"
            "  error      — 出错\n"
            "  done       — 完成\n"
            "  happy      — 开心\n"
            "  greet      — 打招呼\n"
            "  roam       — 闲逛"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "description": "状态名",
                    "enum": list(STATE_MAP.keys()),
                },
                "source": {
                    "type": "string",
                    "description": "来源标记（默认 trae）",
                    "default": "trae",
                },
                "tool": {
                    "type": "string",
                    "description": "当前工具名（可选）",
                },
                "msg": {
                    "type": "string",
                    "description": "附加消息（可选）",
                },
            },
            "required": ["state"],
        },
    },
    {
        "name": "pet_clear_status",
        "description": "清除桌宠状态（回到 idle）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "来源标记（默认 trae）",
                    "default": "trae",
                },
            },
        },
    },
    {
        "name": "pet_get_status",
        "description": "查询桌宠当前状态。",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "pet_complete",
        "description": "任务完成 → 桌宠播放庆祝动画 (done 2.5s)。在任务成功结束时调用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "msg": {"type": "string", "description": "附加消息"},
                "source": {"type": "string", "description": "来源标记（默认 trae）", "default": "trae"},
            },
        },
    },
    {
        "name": "pet_fail",
        "description": "任务失败 → 桌宠显示错误状态 (error 45s)。在任务出错时调用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "msg": {"type": "string", "description": "附加消息"},
                "source": {"type": "string", "description": "来源标记（默认 trae）", "default": "trae"},
            },
        },
    },
    {
        "name": "pet_subagent_start",
        "description": "子代理启动 → 桌宠显示多任务状态 (juggling)。启动子代理时调用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "来源标记（默认 trae）", "default": "trae"},
            },
        },
    },
    {
        "name": "pet_subagent_stop",
        "description": "子代理停止 → 回到工作状态 (working)。子代理完成时调用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "来源标记（默认 trae）", "default": "trae"},
            },
        },
    },
    {
        "name": "pet_notify",
        "description": "需要用户输入 → 桌宠显示等待状态 (needsinput)。在等待用户回复时调用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "msg": {"type": "string", "description": "提示消息"},
                "source": {"type": "string", "description": "来源标记（默认 trae）", "default": "trae"},
            },
        },
    },
    {
        "name": "pet_authorize",
        "description": "等待授权 → 桌宠显示授权等待状态 (waiting)。在需要用户授权时调用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "来源标记（默认 trae）", "default": "trae"},
            },
        },
    },
    {
        "name": "pet_compact",
        "description": "上下文压缩 → 桌宠显示清理状态 (sweeping)。在压缩上下文时调用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "来源标记（默认 trae）", "default": "trae"},
            },
        },
    },
    {
        "name": "pet_sad",
        "description": "被否定/拒绝 → 桌宠显示委屈状态 (sad 8s)。在被用户否定或任务被拒时调用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "msg": {"type": "string", "description": "附加消息"},
                "source": {"type": "string", "description": "来源标记（默认 trae）", "default": "trae"},
            },
        },
    },
    {
        "name": "pet_auto_attach",
        "description": (
            "开启自动托管模式。调用后，MCP 服务器自动追踪工具调用活动，"
            "无需 AI 手动发送 PreToolUse/PostToolUse。"
            "AI 只需在会话开始时调用一次，之后所有 MCP 工具调用都会被自动感知。"
            "\n\n工作原理:\n"
            "  - 每次调用本 MCP 服务器的任意工具（包括 pet_get_status），自动记录活跃时间\n"
            "  - 后台守护线程每 5 秒检查：30 秒内有活动 → 维持 working；超过 30 秒 → 降为 idle\n"
            "  - AI 仍可手动调用 pet_emit_event(Stop) 触发完成动画"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "来源标记（默认 trae）",
                    "default": "trae",
                },
            },
        },
    },
    {
        "name": "pet_auto_detach",
        "description": "关闭自动托管模式，回到手动事件发送模式。",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]

def _status_path() -> str:
    return os.environ.get("HATCH_PET_STATUS_PATH", DEFAULT_STATUS_PATH)

def _events_path() -> str:
    return os.environ.get("HATCH_PET_EVENTS_PATH", DEFAULT_EVENTS_PATH)

def _source_from_env(args: dict) -> str:
    return args.get("source") or os.environ.get("HATCH_PET_SOURCE", "trae")

def execute_tool(name: str, args: dict) -> str:

    global _auto_attached, _auto_source, _auto_running, _auto_daemon_thread, _auto_last_activity
    if _auto_attached:
        with _auto_lock:
            _auto_last_activity = time.time()

    if name == "pet_emit_event":
        event = args.get("event", "")
        source = _source_from_env(args)
        tool = args.get("tool")
        msg = args.get("msg")
        write_event(
            event=event,
            source=source,
            tool=tool,
            msg=msg,
            events_path=_events_path(),
        )
        mapped = EVENT_STATE_MAP.get(event)
        if event == "SessionStart":
            return f"已发送事件 {event} (source={source})，标记 greetPending，等首条 prompt 触发欢迎"
        elif mapped and mapped[0]:
            state, is_oneshot, ttl, bubble = mapped
            return f"已发送事件 {event} → 状态={state}" + (
                f" (oneshot {ttl}s)" if is_oneshot else ""
            ) + (f" 气泡: {bubble}" if bubble else "")
        else:
            return f"已发送事件 {event} (source={source})"

    if name == "pet_set_status":
        state = args.get("state", "")
        if state not in STATE_MAP:
            return f"错误: 未知状态 '{state}'，可用: {', '.join(STATE_MAP.keys())}"
        source = _source_from_env(args)
        write_status(
            state=state,
            tool=args.get("tool"),
            msg=args.get("msg"),
            source=source,
            status_path=_status_path(),
        )
        return f"已设置状态: {state} (source={source})"

    if name == "pet_clear_status":
        source = _source_from_env(args)
        status_path = _status_path()
        if source:
            from pathlib import Path as _P
            sp = _P(_status_path().replace(".json", f"-{source}.json")).expanduser()
            status_path = str(sp)
        clear_status(status_path=status_path)
        return f"已清除状态 (source={source})"

    if name == "pet_get_status":
        data = read_status(_status_path())
        if data is None:
            return "桌宠状态: 未启动或无状态文件"
        return json.dumps(data, ensure_ascii=False, indent=2)

    _EVENT_TOOLS = {
        "pet_complete": "Stop",
        "pet_fail": "StopFailure",
        "pet_subagent_start": "SubagentStart",
        "pet_subagent_stop": "SubagentStop",
        "pet_notify": "Notification",
        "pet_authorize": "PermissionRequest",
        "pet_compact": "PreCompact",
        "pet_sad": "Sad",
        "pet_session_end": "SessionEnd",
    }
    if name in _EVENT_TOOLS:
        event = _EVENT_TOOLS[name]
        source = _source_from_env(args)
        msg = args.get("msg")
        write_event(event=event, source=source, msg=msg, events_path=_events_path())
        return f"已发送事件 {event} (source={source})"

    if name == "pet_auto_attach":
        _auto_attached = True
        _auto_source = _source_from_env(args)
        with _auto_lock:
            _auto_last_activity = time.time()
        return f"✅ 自动托管已更新 (source={_auto_source})"

    if name == "pet_auto_detach":
        _auto_attached = False
        _auto_running = False
        return "✅ 已关闭自动托管，回到手动模式"

    return f"未知工具: {name}"

def _send(msg: dict):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()

def _result(req_id: str, result: dict):
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})

def _error(req_id: str, code: int, message: str):
    _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})

def handle_request(msg: dict):
    method = msg.get("method", "")
    req_id = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        _result(req_id, {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {},
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
        })
        return

    if method == "notifications/initialized":

        return

    if method == "tools/list":
        _result(req_id, {"tools": TOOLS})
        return

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        try:
            text = execute_tool(tool_name, tool_args)
            _result(req_id, {
                "content": [{"type": "text", "text": text}],
            })
        except Exception as e:
            _error(req_id, -32603, f"工具执行失败: {e}")
        return

    if method == "ping":
        _result(req_id, {})
        return

    if req_id is not None:
        _error(req_id, -32601, f"未知方法: {method}")

def main():
    global _auto_running, _auto_daemon_thread

    if not _auto_running:
        _auto_running = True
        _auto_daemon_thread = threading.Thread(
            target=_auto_attach_daemon,
            name="auto-attach-daemon",
            daemon=True,
        )
        _auto_daemon_thread.start()
    with _auto_lock:
        _auto_last_activity = time.time()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            handle_request(msg)
        except json.JSONDecodeError:

            continue
        except Exception as e:

            sys.stderr.write(f"[desktop-buddy MCP] 错误: {e}\n")
            sys.stderr.flush()

if __name__ == "__main__":
    main()
