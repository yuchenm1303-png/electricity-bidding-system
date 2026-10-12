"""School-only browser tab relay for the existing PowerBid PMSS bridge.

This deliberately does NOT expose VNC, a desktop, CDP, arbitrary URLs, a
shell or school session cookies to the internet. It is called exclusively
by PowerBid's authenticated administrator endpoint using a host-only token.
"""
from __future__ import annotations

import hmac
import json
import os
import stat
import threading
from pathlib import Path
from urllib.parse import urlsplit

_LOCK = threading.RLock()
_HANDLE = None
_DRIVER = None
_SCHOOL_URL = "http://cq.university.netts-dev.tsintergy.com/"
_HOST = "cq.university.netts-dev.tsintergy.com"
_TOKEN_FILE = "/srv/powerbid-platform/private-cases/.pmss-web-login-secret"
_KEYS = {
    "Enter": ("Enter", "Enter", 13), "Tab": ("Tab", "Tab", 9),
    "Backspace": ("Backspace", "Backspace", 8),
    "Delete": ("Delete", "Delete", 46), "Escape": ("Escape", "Escape", 27),
    "ArrowLeft": ("ArrowLeft", "ArrowLeft", 37), "ArrowUp": ("ArrowUp", "ArrowUp", 38),
    "ArrowRight": ("ArrowRight", "ArrowRight", 39),
    "ArrowDown": ("ArrowDown", "ArrowDown", 40),
}


def _trusted(handler):
    try:
        path = Path(_TOKEN_FILE)
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or stat.S_IMODE(mode) != 0o600:
            return False
        actual = path.read_text(encoding="ascii").strip()
        candidate = handler.headers.get("X-PowerBid-Operator-Token", "")
        return len(actual) >= 40 and hmac.compare_digest(actual, candidate)
    except (OSError, ValueError):
        return False


def _driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.debugger_address = os.environ.get(
        "POWERBID_CHROME_DEBUGGER", "127.0.0.1:9223"
    )
    return webdriver.Chrome(options=options)


def _pick_tab(driver):
    global _HANDLE
    handles = driver.window_handles
    if _HANDLE in handles:
        driver.switch_to.window(_HANDLE)
        if urlsplit(driver.current_url).hostname == _HOST:
            return
    for handle in handles:
        driver.switch_to.window(handle)
        url = urlsplit(driver.current_url)
        if url.hostname == _HOST and not url.path.startswith("/pmss/"):
            _HANDLE = handle
            return
    for handle in handles:
        driver.switch_to.window(handle)
        if urlsplit(driver.current_url).hostname == _HOST:
            _HANDLE = handle
            return
    raise ValueError("No school browser tab")


def _act(driver, payload):
    kind = payload.get("action")
    if kind == "open":
        driver.get(_SCHOOL_URL)
    elif kind == "click":
        x, y = payload.get("x"), payload.get("y")
        if type(x) not in (int, float) or type(y) not in (int, float):
            raise ValueError("Invalid coordinates")
        if not 0 <= x <= 2000 or not 0 <= y <= 1200:
            raise ValueError("Invalid coordinates")
        driver.execute_cdp_cmd("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        for event in ("mousePressed", "mouseReleased"):
            driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
                "type": event, "x": x, "y": y,
                "button": "left", "clickCount": 1,
            })
    elif kind == "text":
        value = payload.get("text")
        if not isinstance(value, str) or not 1 <= len(value) <= 128:
            raise ValueError("Invalid text")
        if any(ord(char) < 32 for char in value):
            raise ValueError("Invalid characters")
        # Native Chrome input: no storing or printing user-entered passwords.
        driver.execute_cdp_cmd("Input.insertText", {"text": value})
    elif kind == "key":
        name = payload.get("key")
        if name not in _KEYS:
            raise ValueError("Invalid key")
        key, code, vk = _KEYS[name]
        for event in ("rawKeyDown", "keyUp"):
            driver.execute_cdp_cmd("Input.dispatchKeyEvent", {
                "type": event, "key": key, "code": code,
                "windowsVirtualKeyCode": vk,
            })
    elif kind == "scroll":
        dy = payload.get("dy")
        if type(dy) is not int or dy not in (-1, 1):
            raise ValueError("Invalid scroll")
        driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
            "type": "mouseWheel", "x": 600, "y": 400,
            "deltaX": 0, "deltaY": dy * 380,
        })
    else:
        raise ValueError("Invalid action")
    if urlsplit(driver.current_url).hostname != _HOST:
        raise ValueError("School browser left the permitted host")


def handle_school_browser(handler, path, authenticated):
    """Return True only for the dedicated login routes on the local bridge."""
    if not path.startswith("/operator/browser/"):
        return False
    if not _trusted(handler):
        handler._json(403, {"error": "operator_denied"})
        return True
    if path == "/operator/browser/status" and handler.command == "GET":
        handler._json(200, {"ready": True})
        return True
    if path == "/operator/browser/frame" and handler.command == "GET":
        with _LOCK:
            try:
                driver = _driver()
                try:
                    _pick_tab(driver)
                    frame = driver.get_screenshot_as_png()
                finally:
                    driver.quit()
                if not 100 <= len(frame) <= 2_000_000:
                    raise ValueError("Invalid frame")
            except Exception:
                handler._json(503, {"error": "school_browser_unavailable"})
                return True
        handler.send_response(200)
        handler.send_header("Content-Type", "image/png")
        handler.send_header("Cache-Control", "private, no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("Content-Length", str(len(frame)))
        handler.end_headers()
        handler.wfile.write(frame)
        return True
    if path == "/operator/browser/action" and handler.command == "POST":
        try:
            size = int(handler.headers.get("Content-Length", "0"))
            if not 1 <= size <= 650:
                raise ValueError("Invalid body")
            body = json.loads(handler.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError("Invalid body")
            # After the school session becomes valid, interactive access stops.
            # School bid/clearing writes continue to require the dedicated,
            # separately confirmed original PMSS API workflow.
            if authenticated():
                handler._json(409, {"error": "school_already_authorized"})
                return True
            with _LOCK:
                driver = _driver()
                try:
                    _pick_tab(driver)
                    _act(driver, body)
                finally:
                    driver.quit()
        except (ValueError, TypeError, KeyError):
            handler._json(422, {"error": "invalid_browser_action"})
            return True
        except Exception:
            handler._json(503, {"error": "school_browser_unavailable"})
            return True
        handler._json(200, {"ok": True})
        return True
    handler._json(405, {"error": "operator_method_not_allowed"})
    return True
