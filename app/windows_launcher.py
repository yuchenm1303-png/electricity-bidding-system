from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

APP_NAME = "PowerBid Lab"
SERVER_ARG = "--powerbid-server"
SELF_TEST_ARG = "--self-test"
STARTUP_TIMEOUT_SECONDS = 45.0


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def _state_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PowerBidLab"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _log_path() -> Path:
    return _state_dir() / "startup-error.log"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _show_error(message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, APP_NAME, 0x10)
    except Exception:
        pass


def _write_failure(detail: str) -> None:
    try:
        _log_path().write_text(detail, encoding="utf-8")
    except Exception:
        pass


def _server_command(port: int) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, SERVER_ARG, str(port)]
    return [sys.executable, str(Path(__file__).resolve()), SERVER_ARG, str(port)]


def _run_streamlit_server(port: int) -> int:
    root = _bundle_root()
    app_script = root / "app" / "streamlit_app.py"
    if not app_script.exists():
        raise FileNotFoundError(f"Missing bundled app: {app_script}")

    os.chdir(root)
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    os.environ.setdefault("STREAMLIT_SERVER_FILE_WATCHER_TYPE", "none")
    os.environ.setdefault("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "false")

    sys.argv = [
        "streamlit",
        "run",
        str(app_script),
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--server.headless=true",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
    ]

    from streamlit.web import cli as stcli

    return int(stcli.main() or 0)


def _start_server(port: int) -> tuple[subprocess.Popen[bytes], object]:
    server_log_path = _state_dir() / "server.log"
    server_log = server_log_path.open("wb")
    creationflags = 0
    if os.name == "nt":
        creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))

    process = subprocess.Popen(
        _server_command(port),
        stdin=subprocess.DEVNULL,
        stdout=server_log,
        stderr=subprocess.STDOUT,
        close_fds=True,
        creationflags=creationflags,
    )
    return process, server_log


def _wait_for_server(process: subprocess.Popen[bytes], port: int) -> None:
    health_url = f"http://127.0.0.1:{port}/_stcore/health"
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(
                f"Local application server exited before startup completed (exit code {exit_code})."
            )
        try:
            with urllib.request.urlopen(health_url, timeout=1.0) as response:
                if 200 <= int(response.status) < 300:
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc
        time.sleep(0.15)

    raise TimeoutError(f"Timed out waiting for the local application server: {last_error}")


def _stop_server(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=4)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _desktop_main(self_test: bool = False) -> int:
    port = _free_port()
    process: subprocess.Popen[bytes] | None = None
    server_log = None

    try:
        process, server_log = _start_server(port)
        _wait_for_server(process, port)

        if self_test:
            return 0

        import webview

        window = webview.create_window(
            APP_NAME,
            f"http://127.0.0.1:{port}",
            width=1440,
            height=900,
            min_size=(960, 640),
            resizable=True,
            text_select=True,
        )
        if window is None:
            raise RuntimeError("Failed to create the desktop application window.")

        # pywebview uses the installed Microsoft Edge WebView2 runtime on Windows.
        # The local Streamlit server remains bound to 127.0.0.1 and no external
        # browser is launched.
        webview.start(debug=False, private_mode=False)
        return 0
    finally:
        _stop_server(process)
        if server_log is not None:
            try:
                server_log.close()
            except Exception:
                pass


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == SERVER_ARG:
        return _run_streamlit_server(int(sys.argv[2]))
    return _desktop_main(self_test=SELF_TEST_ARG in sys.argv[1:])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        detail = traceback.format_exc()
        _write_failure(detail)
        _show_error(
            "PowerBid Lab 启动失败。\n\n"
            f"错误日志已保存到：\n{_log_path()}\n\n"
            "请把该日志发给开发者定位。"
        )
        raise
