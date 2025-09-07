import subprocess
import time
import requests
import pytest
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, timezone

CLIENT_COUNT=20

# -------------------------
# Constants / Config
# -------------------------
DOCKER_COMPOSE_FILE = "docker-compose.yml"
SERVICE_NAME = "main-server"
BASE_URL = "http://localhost:5000"
HEALTH_URL = f"{BASE_URL}/health"
SERVICES = ["main-server", "message-client", "watchdog"]  # for log collection

# One timestamp + artifacts dir for the whole test session
START_TS = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
ARTIFACT_DIR = Path("test_artifacts") / START_TS
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


# -------------------------
# docker-compose helpers
# -------------------------
def _compose(*args, check=True, capture_output=False):
    """Run docker-compose with Windows-safe decoding."""
    return subprocess.run(
        ["docker-compose", "-f", DOCKER_COMPOSE_FILE, *args],
        check=check,
        capture_output=capture_output,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _start_server_process_in_container():
    """
    Start server.py inside the main-server container even though compose runs /bin/bash.
    We import the module and call socketio.run(app, allow_unsafe_werkzeug=True) so we
    do NOT need to modify your code or compose.
    """
    start_script = r'''
set -eu
PY="$(command -v python || true)"
if [ -z "${PY}" ]; then
  PY="$(command -v python3 || true)"
fi
if [ -z "${PY}" ]; then
  echo "ERROR: no python/python3 in PATH" >&2
  exit 1
fi

# Prefer /app/src/server.py, but import as a module path so we can override run() args
if [ -f /app/src/server.py ]; then
  MODPATH="/app/src"
elif [ -f /app/server.py ]; then
  MODPATH="/app"
else
  echo "ERROR: server.py not found under /app/src or /app" >&2
  ls -la /app || true
  ls -la /app/src || true
  exit 1
fi

# Clear old log to avoid confusion
: > /tmp/server.log || true

# Start Flask-SocketIO app with Werkzeug allowed for tests
nohup "${PY}" -c "import sys; sys.path.insert(0, '${MODPATH}'); import server; server.socketio.run(server.app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)" >/tmp/server.log 2>&1 & echo $! >/tmp/server.pid
'''
    subprocess.run(
        ["docker-compose", "-f", DOCKER_COMPOSE_FILE, "exec", "-T",
         SERVICE_NAME, "sh", "-lc", start_script],
        check=False
    )


def _container_server_log_tail(lines=2000):
    """Tail the internal server log from inside the container."""
    try:
        out = subprocess.run(
            ["docker-compose", "-f", DOCKER_COMPOSE_FILE, "exec", "-T",
             SERVICE_NAME, "sh", "-lc", f"tail -n {lines} /tmp/server.log || true"],
            capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        return out.stdout
    except Exception as e:
        return f"<unable to fetch /tmp/server.log: {e}>"


def _wait_for_health(timeout_sec=90):
    """Poll /health until it's ready or raise with logs."""
    start = time.time()
    last_err = None
    while time.time() - start < timeout_sec:
        try:
            r = requests.get(HEALTH_URL, timeout=2)
            if r.status_code == 200 and r.json().get("status") == "ok":
                return
            last_err = f"HTTP {r.status_code} {r.text}"
        except Exception as e:
            last_err = str(e)
        time.sleep(1)

    # On failure, dump compose + internal logs to help diagnose startup issues
    logs = _compose("logs", SERVICE_NAME, capture_output=True).stdout
    server_log = _container_server_log_tail(2000)
    raise RuntimeError(
        "Server did not become healthy in time.\n"
        f"Last error: {last_err}\n"
        f"---- docker logs ({SERVICE_NAME}) ----\n{logs}\n"
        f"---- /tmp/server.log ({SERVICE_NAME}) ----\n{server_log}"
    )


# -------------------------
# Log collection (end of run)
# -------------------------
def _gather_all_logs():
    logs = {}
    # Whole-compose logs (timestamps, no color)
    try:
        logs["compose_all"] = _compose("logs", "-t", "--no-color", capture_output=True).stdout
    except Exception as e:
        logs["compose_all"] = f"<compose logs error: {e}>"

    # Per-service logs
    for svc in SERVICES:
        try:
            logs[f"compose_{svc}"] = _compose("logs", "-t", "--no-color", svc, capture_output=True).stdout
        except Exception as e:
            logs[f"compose_{svc}"] = f"<compose logs {svc} error: {e}>"

    # Internal server log
    logs["server_log"] = _container_server_log_tail(2000)
    return logs


def _dump_logs_to_console(logs: dict, banner="FINAL LOGS"):
    sep = "=" * 80
    print(f"\n{sep}\n[{banner}] docker-compose logs (all)\n{sep}\n{logs.get('compose_all','')}")
    for svc in SERVICES:
        print(f"\n{sep}\n[{banner}] docker-compose logs ({svc})\n{sep}\n{logs.get(f'compose_{svc}','')}")
    print(f"\n{sep}\n[{banner}] /tmp/server.log inside {SERVICE_NAME}\n{sep}\n{logs.get('server_log','')}\n")


def _save_text(filename: str, content: str):
    path = ARTIFACT_DIR / filename
    path.write_text(content or "", encoding="utf-8", errors="replace")
    return path


def _save_json(filename: str, data):
    path = ARTIFACT_DIR / filename
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _save_logs_to_files(logs: dict):
    _save_text("compose_all.log", logs.get("compose_all", ""))
    for svc in SERVICES:
        _save_text(f"compose_{svc}.log", logs.get(f"compose_{svc}", ""))
    _save_text("server_internal.log", logs.get("server_log", ""))
    print(f"[ARTIFACTS] Logs saved to: {ARTIFACT_DIR.resolve()}")


# -------------------------
# Pytest fixture: bring stack up / down
# -------------------------
@pytest.fixture(scope="session", autouse=True)
def bring_up_stack():
    # Up (leaves bash idle in your containers)
    _compose("up", "--build", "-d")
    # Start server process inside main-server container
    _start_server_process_in_container()
    # Wait for readiness
    _wait_for_health(timeout_sec=90)

    # Run tests
    yield

    # Collect + show + save logs before we tear down
    logs = _gather_all_logs()
    _dump_logs_to_console(logs, banner="TEST RUN")
    _save_logs_to_files(logs)

    # Down
    _compose("down")


# -------------------------
# Test 1: HTTP multi-client
# -------------------------
def _http_client(i: int):
    r = requests.get(HEALTH_URL, timeout=5)
    assert r.status_code == 200, f"Client {i} bad status {r.status_code}"
    data = r.json()
    assert data.get("status") == "ok", f"Client {i} bad payload {data}"
    return (i, data)


def test_http_multi_client(bring_up_stack):
    client_count = CLIENT_COUNT
    results = []
    with ThreadPoolExecutor(max_workers=client_count) as pool:
        futures = [pool.submit(_http_client, i) for i in range(client_count)]
        for f in as_completed(futures):
            results.append(f.result())
    assert len(results) == client_count
    for i, data in sorted(results):
        print(f"[HTTP] Client {i} got: {data}")


# -------------------------
# Test 2: Socket.IO multi-client + JSON transcript
# -------------------------
def test_socketio_multi_client_join_and_chat(bring_up_stack):
    try:
        import socketio  # pip install python-socketio websocket-client (host env)
    except ImportError:
        pytest.skip("Install `python-socketio` + `websocket-client` to run the Socket.IO test")

    class ChatClient:
        def __init__(self, name: str, room: str):
            self.name = name
            self.room = room
            self.received_chat = []
            self.received_system = []
            self.errors = []
            self.sio = socketio.Client(reconnection=False)

            @self.sio.event
            def connect():
                pass

            @self.sio.on("chat")
            def on_chat(payload):
                self.received_chat.append(
                    (payload.get("from"), payload.get("body"), payload.get("ts"))
                )

            @self.sio.on("system")
            def on_system(payload):
                msg = payload.get("msg")
                if msg:
                    self.received_system.append(msg)

            @self.sio.on("error")
            def on_error(payload):
                self.errors.append(payload)

            @self.sio.event
            def disconnect():
                pass

        def connect_and_join(self):
            # Force polling transport to avoid WS dependency in Werkzeug
            self.sio.connect(BASE_URL, wait=True, wait_timeout=10, transports=['polling'])
            self.sio.emit("join", {"name": self.name, "room": self.room})

        def send_chat(self, body: str):
            self.sio.emit("chat", {"body": body})

        def disconnect(self):
            try:
                self.sio.emit("leave", {})
                self.sio.disconnect()
            except Exception:
                pass

    room = f"room-{int(time.time())}"
    client_count = CLIENT_COUNT
    clients = [ChatClient(name=f"user{i}", room=room) for i in range(client_count)]

    # Connect & join concurrently
    with ThreadPoolExecutor(max_workers=client_count) as pool:
        join_futs = [pool.submit(c.connect_and_join) for c in clients]
        for f in as_completed(join_futs):
            f.result(timeout=15)

    time.sleep(0.5)

    # Verify room state via REST
    info = requests.get(f"{BASE_URL}/rooms/{room}", timeout=5).json()
    members = info.get("members", [])
    assert isinstance(members, list)
    assert len(members) == client_count, f"Expected {client_count} members, got {len(members)}: {members}"

    # Send concurrent chat messages
    with ThreadPoolExecutor(max_workers=client_count) as pool:
        send_futs = [pool.submit(c.send_chat, f"hello from {c.name}") for c in clients]
        for f in as_completed(send_futs):
            f.result(timeout=10)

    time.sleep(1.0)

    # Each client should receive all chat messages from all clients
    for c in clients:
        user_msgs = [(frm, body) for (frm, body, ts) in c.received_chat if frm and frm.startswith("user")]
        assert len(user_msgs) == client_count, f"{c.name} received {len(user_msgs)} chat msgs, expected {client_count}. Got={user_msgs}"
        expected_bodies = {f"hello from user{i}" for i in range(client_count)}
        got_bodies = {body for (frm, body) in user_msgs}
        assert got_bodies == expected_bodies, f"{c.name} missing/extra bodies: got={got_bodies}, expected={expected_bodies}"
        assert not c.errors, f"{c.name} received errors: {c.errors}"

    # Fetch persisted messages (newest-first from API), convert to chronological,
    # and extract only client-to-client chat (exclude system/server entries).
    raw_msgs = requests.get(f"{BASE_URL}/rooms/{room}/messages?limit=200", timeout=5).json()
    chronological = list(reversed(raw_msgs))  # server returns newest-first
    client_chats = [
        {"from": m.get("from"), "body": m.get("body"), "ts": m.get("ts")}
        for m in chronological
        if isinstance(m, dict) and str(m.get("from", "")).startswith("user")
    ]

    # Assertions on persistence
    for i in range(client_count):
        expected = {"from": f"user{i}", "body": f"hello from user{i}"}
        assert any(
            (msg.get("from") == expected["from"] and msg.get("body") == expected["body"])
            for msg in client_chats
        ), f"Persisted messages missing user{i}'s chat"

    # -------------------------
    # Write JSON transcript artifact
    # -------------------------
    transcript = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "room": room,
        "client_count": client_count,
        "clients": [c.name for c in clients],
        "messages": client_chats,  # strictly between users
        # Optional: include raw (with system messages) if you ever need it:
        # "raw_messages": chronological,
    }
    out_path = _save_json(f"chat_transcript_{room}.json", transcript)
    print(f"[ARTIFACTS] Chat transcript written to: {out_path.resolve()}")

    # Cleanly disconnect everyone
    for c in clients:
        c.disconnect()
