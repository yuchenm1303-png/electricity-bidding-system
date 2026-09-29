from __future__ import annotations

import os
import socket
import sys
import traceback
from pathlib import Path


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _show_error(message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, "PowerBid Lab", 0x10)
    except Exception:
        pass


def main() -> int:
    root = _bundle_root()
    app_script = root / "app" / "streamlit_app.py"
    if not app_script.exists():
        raise FileNotFoundError(f"Missing bundled app: {app_script}")

    os.chdir(root)
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    os.environ.setdefault("STREAMLIT_SERVER_FILE_WATCHER_TYPE", "none")
    os.environ.setdefault("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "false")

    port = _free_port()
    sys.argv = [
        "streamlit",
        "run",
        str(app_script),
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--server.headless=false",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
    ]

    from streamlit.web import cli as stcli

    return int(stcli.main() or 0)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        detail = traceback.format_exc()
        log_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PowerBidLab"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "startup-error.log"
        log_path.write_text(detail, encoding="utf-8")
        _show_error(
            "PowerBid Lab 启动失败。\n\n"
            f"错误日志已保存到：\n{log_path}\n\n"
            "请把该日志发给开发者定位。"
        )
        raise
