"""School-only browser tab relay for the existing PowerBid PMSS bridge.

This deliberately does NOT expose VNC, a desktop, CDP, arbitrary URLs, a
shell or school session cookies to the internet. It is called exclusively
by PowerBid's authenticated administrator endpoint using a host-only token.
"""
from __future__ import annotations

import hmac
import json
import os
import math
import stat
import struct
import threading
from pathlib import Path
from urllib.parse import urlsplit

_LOCK = threading.RLock()
_HANDLE = None
_FRAME_METRICS = None
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
    """Keep a single attached ChromeDriver throughout the service lifetime.

    Called only while holding _LOCK. Re-attaching to a running Chrome on
    every screenshot was the dominant avoidable per-frame overhead.
    """
    global _DRIVER
    if _DRIVER is None:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        options = Options()
        # VPN subresources can remain pending indefinitely. Relay commands
        # must not wait for the school's full page-load event.
        options.page_load_strategy = "none"
        options.debugger_address = os.environ.get(
            "POWERBID_CHROME_DEBUGGER", "127.0.0.1:9223"
        )
        driver_path = os.environ.get("POWERBID_CHROMEDRIVER")
        if driver_path:
            from selenium.webdriver.chrome.service import Service
            _DRIVER = webdriver.Chrome(service=Service(driver_path), options=options)
        else:
            _DRIVER = webdriver.Chrome(options=options)
        # Bound Chrome transport as well as the outer HTTP relay; otherwise
        # a stalled renderer holds _LOCK long after the caller has timed out.
        _DRIVER.command_executor._client_config.timeout = 3
        _DRIVER.set_page_load_timeout(4)
    return _DRIVER


def _reset_driver():
    """Discard stale attachment only on errors, never after normal frames."""
    global _DRIVER, _HANDLE, _FRAME_METRICS
    current = _DRIVER
    _DRIVER = None
    _HANDLE = None
    _FRAME_METRICS = None
    if current is not None:
        try:
            current.quit()
        except Exception:
            pass


def _pick_tab(driver):
    global _HANDLE
    handles = driver.window_handles
    if _HANDLE in handles:
        if driver.current_window_handle != _HANDLE:
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


def _screenshot_to_css(x, y, metrics):
    """Chrome CDP accepts CSS coordinates, screenshots contain device pixels."""
    if metrics is None:
        raise ValueError("Browser frame must be captured before clicking")
    pixel_w, pixel_h, css_w, css_h = metrics
    if not all(math.isfinite(v) and v > 0 for v in metrics):
        raise ValueError("Invalid browser dimensions")
    if not all(math.isfinite(v) for v in (x, y)):
        raise ValueError("Invalid pointer coordinates")
    if not (0 <= x < pixel_w and 0 <= y < pixel_h):
        raise ValueError("Pointer outside screenshot")
    return (x * css_w / pixel_w, y * css_h / pixel_h)


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
        x, y = _screenshot_to_css(x, y, _FRAME_METRICS)
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
    if kind == "click":
        # Safe focus signal only: do not inspect, store or return input contents.
        return {"focused_input": bool(driver.execute_script(
            "return ['INPUT','TEXTAREA'].includes(document.activeElement?.tagName)"
        ))}
    return {}


def _submit_school_login(driver, username, password):
    """Fill the two known school form fields and submit only after admin click.

    Inputs exist for this one operation; never return, persist or log either.
    Selenium/CDP acts on the already-authenticated, server-owned school tab.
    """
    page = urlsplit(driver.current_url)
    if page.hostname != _HOST or page.path != "/":
        raise ValueError("School login form is not the active page")
    # Only two exact field identifiers and the school's own submit control.
    form_ready = driver.execute_script(
        "return Boolean(document.querySelector('input#username[type=text]')"
        " && document.querySelector('input#password[type=password]')"
        " && document.querySelector('button[type=submit]'))"
    )
    if not form_ready:
        raise ValueError("School login form is unavailable")
    # Native input events are required for React / Ant Design form state.
    for field_id, value in (("username", username), ("password", password)):
        driver.execute_script(
            "const field=document.getElementById(arguments[0]);"
            "const setter=Object.getOwnPropertyDescriptor("
            "HTMLInputElement.prototype,'value').set;"
            "setter.call(field,'');"
            "field.dispatchEvent(new Event('input',{bubbles:true}));"
            "field.focus();",
            field_id,
        )
        driver.execute_cdp_cmd("Input.insertText", {"text": value})
    # No generic click: exactly the known school sign-in form submit button.
    driver.execute_script(
        "document.querySelector('button[type=submit]').click()"
    )

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
                _pick_tab(driver)
                frame = driver.get_screenshot_as_png()
                pixel_w, pixel_h = struct.unpack(">II", frame[16:24])
                css_w, css_h = driver.execute_script(
                    "return [window.innerWidth,window.innerHeight]"
                )
                global _FRAME_METRICS
                _FRAME_METRICS = (pixel_w, pixel_h, css_w, css_h)
                if not 100 <= len(frame) <= 2_000_000:
                    raise ValueError("Invalid frame")
            except Exception:
                _reset_driver()
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
    if path == "/operator/browser/login" and handler.command == "POST":
        try:
            size = int(handler.headers.get("Content-Length", "0"))
            if not 1 <= size <= 900:
                raise ValueError("Invalid login request size")
            body = json.loads(handler.rfile.read(size))
            if not isinstance(body, dict) or set(body) != {"username", "password"}:
                raise ValueError("Invalid login request")
            username, password = body["username"], body["password"]
            if not (isinstance(username, str) and isinstance(password, str)
                    and 1 <= len(username) <= 128 and 1 <= len(password) <= 256):
                raise ValueError("Invalid login field length")
            if any(ord(c) < 32 for c in username + password):
                raise ValueError("Invalid login characters")
            if authenticated():
                handler._json(409, {"error": "school_already_authorized"})
                return True
            with _LOCK:
                driver = _driver()
                _pick_tab(driver)
                _submit_school_login(driver, username, password)
        except (ValueError, TypeError, KeyError):
            handler._json(422, {"error": "invalid_school_login_form"})
            return True
        except Exception:
            with _LOCK:
                _reset_driver()
            handler._json(503, {"error": "school_login_unavailable"})
            return True
        handler._json(200, {"submitted": True})
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
                _pick_tab(driver)
                outcome = _act(driver, body)
        except (ValueError, TypeError, KeyError):
            handler._json(422, {"error": "invalid_browser_action"})
            return True
        except Exception:
            with _LOCK:
                _reset_driver()
            handler._json(503, {"error": "school_browser_unavailable"})
            return True
        handler._json(200, {"ok": True, **outcome})
        return True
    handler._json(405, {"error": "operator_method_not_allowed"})
    return True
