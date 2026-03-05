"""Web chat server for nanobot — runs as a background thread alongside the gateway."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop

WEBCHAT_PORT = 17798


def _build_app(
    agent: "AgentLoop",
    agent_loop: asyncio.AbstractEventLoop,
):
    """Create and configure the Flask application backed by a live AgentLoop."""
    try:
        from flask import Flask, Response, jsonify, render_template, request, stream_with_context
    except ImportError as exc:
        raise ImportError(
            "Flask is required for the web chat UI. "
            "Install it with: pip install flask"
        ) from exc

    template_dir = Path(__file__).parent / "templates"
    app = Flask(__name__, template_folder=str(template_dir))

    # session_id -> concurrent.futures.Future (from run_coroutine_threadsafe)
    active_tasks: dict[str, "asyncio.Future"] = {}

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/chat/stream", methods=["POST"])
    def chat_stream():
        """SSE streaming endpoint — streams tokens as they arrive from the agent."""
        data = request.get_json(force=True)
        message = (data.get("message") or "").strip()
        session_id = data.get("session_id") or f"web:{uuid.uuid4().hex[:8]}"

        if not message:
            return jsonify({"error": "消息不能为空"}), 400

        # Synchronous queue bridges asyncio callbacks → Flask generator thread.
        q: queue.Queue = queue.Queue()
        cancel_event = threading.Event()

        async def run():
            async def on_token(chunk: str) -> None:
                if cancel_event.is_set():
                    raise asyncio.CancelledError()
                q.put(("token", chunk))

            async def on_progress(content: str, *, tool_hint: bool = False, full_content: str | None = None) -> None:
                if cancel_event.is_set():
                    return
                payload = {"content": content, "tool_hint": tool_hint}
                if full_content:
                    payload["full_content"] = full_content
                q.put(("progress", payload))

            try:
                await agent.process_direct(
                    message,
                    session_key=session_id,
                    channel="webchat",
                    chat_id=session_id,
                    on_token=on_token,
                    on_progress=on_progress,
                )
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001
                q.put(("error", str(exc)))
            finally:
                q.put(("done", None))

        future = asyncio.run_coroutine_threadsafe(run(), agent_loop)
        active_tasks[session_id] = future

        def generate():
            # Short poll interval: check queue every 30 s and emit a keep-alive
            # comment so proxies / browsers don't close the connection.
            # Total idle limit before giving up: 600 s (10 minutes).
            POLL_INTERVAL = 30
            MAX_IDLE = 600
            idle_elapsed = 0
            try:
                while True:
                    try:
                        kind, payload = q.get(timeout=POLL_INTERVAL)
                        idle_elapsed = 0  # reset on activity
                    except queue.Empty:
                        idle_elapsed += POLL_INTERVAL
                        if idle_elapsed >= MAX_IDLE:
                            # Truly timed out after MAX_IDLE seconds of silence.
                            yield f"data: {json.dumps({'error': 'timeout', 'session_id': session_id})}\n\n"
                            break
                        # Send SSE keep-alive comment to prevent proxy/browser disconnect.
                        yield ": keep-alive\n\n"
                        continue

                    if kind == "token":
                        yield f"data: {json.dumps({'chunk': payload, 'session_id': session_id})}\n\n"
                    elif kind == "progress":
                        yield f"data: {json.dumps({'progress': payload, 'session_id': session_id})}\n\n"
                    elif kind == "done":
                        yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"
                        break
                    elif kind == "error":
                        yield f"data: {json.dumps({'error': payload, 'session_id': session_id})}\n\n"
                        break
            except GeneratorExit:
                # Browser disconnected — cancel the in-flight agent task.
                cancel_event.set()
                future.cancel()
            finally:
                active_tasks.pop(session_id, None)

        resp = Response(stream_with_context(generate()), mimetype="text/event-stream")
        resp.headers["X-Accel-Buffering"] = "no"
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Connection"] = "keep-alive"
        return resp

    @app.route("/api/chat/abort", methods=["POST"])
    def abort():
        """Cancel an in-flight generation for the given session."""
        data = request.get_json(force=True)
        session_id = (data.get("session_id") or "").strip()
        fut = active_tasks.pop(session_id, None)
        if fut:
            fut.cancel()
        return jsonify({"aborted": bool(fut), "session_id": session_id})

    @app.route("/api/sessions/<session_id>")
    def get_session(session_id: str):
        """Return persisted conversation history for a session."""
        try:
            session = agent.sessions.get_or_create(session_id)
            history = [
                {
                    "role": m.get("role"),
                    "content": m.get("content"),
                    "timestamp": m.get("timestamp"),
                }
                for m in session.get_history(max_messages=200)
                if m.get("role") in ("user", "assistant")
            ]
        except Exception:  # noqa: BLE001
            history = []
        return jsonify({"history": history, "session_id": session_id})

    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok", "mode": "agent-direct"})

    return app


def start_webchat_server(
    agent: "AgentLoop | None" = None,
    agent_loop: "asyncio.AbstractEventLoop | None" = None,
    # Legacy fallback parameters kept for backward compatibility
    nanobot_path: str | None = None,
    workspace: str | None = None,
    port: int = WEBCHAT_PORT,
    *,
    open_browser: bool = True,
) -> threading.Thread:
    """Start the web chat server in a background daemon thread.

    When agent + agent_loop are provided the server communicates directly with
    the in-process AgentLoop (streaming, no subprocess).  If they are absent
    the server falls back to the legacy subprocess mode.

    Returns the thread so callers can join / inspect it if needed.
    """
    if agent is not None and agent_loop is not None:
        app = _build_app(agent, agent_loop)
    else:
        app = _build_legacy_app(nanobot_path, workspace)

    def _serve() -> None:
        import logging
        log = logging.getLogger("werkzeug")
        log.setLevel(logging.ERROR)
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

    thread = threading.Thread(target=_serve, daemon=True, name="webchat-server")
    thread.start()

    if open_browser:
        import time
        import webbrowser

        def _open_later() -> None:
            time.sleep(1.5)
            webbrowser.open(f"http://localhost:{port}")

        threading.Thread(target=_open_later, daemon=True, name="webchat-browser").start()

    return thread


# ---------------------------------------------------------------------------
# Legacy subprocess fallback (used when agent is not available, e.g. tests)
# ---------------------------------------------------------------------------

def _build_legacy_app(nanobot_path: str | None, workspace: str | None):
    """Fallback Flask app that calls nanobot via subprocess (non-streaming)."""
    import subprocess
    import sys

    try:
        from flask import Flask, jsonify, render_template, request
    except ImportError as exc:
        raise ImportError("Flask is required. pip install flask") from exc

    if nanobot_path:
        resolved_nanobot = nanobot_path
    else:
        venv_bin = Path(sys.executable).parent
        candidate = venv_bin / "nanobot"
        import shutil
        resolved_nanobot = str(candidate) if candidate.exists() else (shutil.which("nanobot") or "nanobot")

    resolved_workspace = workspace or str(Path.home() / ".nanobot" / "workspace")

    template_dir = Path(__file__).parent / "templates"
    app = Flask(__name__, template_folder=str(template_dir))
    sessions: dict[str, list[dict]] = {}

    def _call_nanobot(message: str, session_id: str) -> str:
        cmd = [resolved_nanobot, "agent", "-m", message, "-s", session_id,
               "--no-markdown", "--no-logs"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=120, cwd=resolved_workspace)
            if result.returncode == 0:
                output = result.stdout.strip()
                lines = [line for line in output.split("\n")
                         if line.strip() and not line.startswith("🐈")]
                return "\n".join(lines) if lines else output
            return f"错误: {result.stderr}"
        except subprocess.TimeoutExpired:
            return "请求超时，请稍后重试"
        except Exception as exc:  # noqa: BLE001
            return f"调用失败: {exc}"

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/chat", methods=["POST"])
    def chat():
        data = request.get_json(force=True)
        message = (data.get("message") or "").strip()
        session_id = data.get("session_id") or f"web:{uuid.uuid4().hex[:8]}"
        if not message:
            return jsonify({"error": "消息不能为空"}), 400
        response = _call_nanobot(message, session_id)
        sessions.setdefault(session_id, []).append({
            "timestamp": datetime.now().isoformat(),
            "user": message, "assistant": response,
        })
        return jsonify({"response": response, "session_id": session_id,
                        "timestamp": datetime.now().isoformat()})

    @app.route("/api/sessions/<session_id>")
    def get_session(session_id: str):
        return jsonify({"history": sessions.get(session_id, [])})

    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok", "nanobot": resolved_nanobot})

    return app
