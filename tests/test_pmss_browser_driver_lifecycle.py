"""Performance regressions for the restricted school-login driver lifecycle.

No school credentials, browser connection or school write APIs are exercised.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pmss_browser_operator as operator


def test_driver_is_reused_until_explicit_reset(monkeypatch):
    created = []
    class ChromeOptions:
        debugger_address = ""
    class Chrome:
        def __init__(self, options):
            created.append(options.debugger_address)
            self.quit_count = 0
        def quit(self):
            self.quit_count += 1

    selenium = types.ModuleType("selenium")
    webdriver = types.ModuleType("selenium.webdriver")
    chrome = types.ModuleType("selenium.webdriver.chrome")
    options = types.ModuleType("selenium.webdriver.chrome.options")
    options.Options = ChromeOptions
    webdriver.Chrome = Chrome
    selenium.webdriver = webdriver
    monkeypatch.setitem(sys.modules, "selenium", selenium)
    monkeypatch.setitem(sys.modules, "selenium.webdriver", webdriver)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.chrome", chrome)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.chrome.options", options)
    monkeypatch.setattr(operator, "_DRIVER", None)
    try:
        first = operator._driver()
        assert operator._driver() is first
        assert created == ["127.0.0.1:9223"]
        operator._reset_driver()
        assert first.quit_count == 1
        new = operator._driver()
        assert new is not first
        assert len(created) == 2
    finally:
        operator._reset_driver()


def test_reset_also_invalidates_screenshot_coordinates(monkeypatch):
    class DummyDriver:
        def quit(self):
            pass
    monkeypatch.setattr(operator, "_DRIVER", DummyDriver())
    monkeypatch.setattr(operator, "_HANDLE", "old-school-tab")
    monkeypatch.setattr(operator, "_FRAME_METRICS", (1356, 676, 1695, 845))
    operator._reset_driver()
    assert operator._DRIVER is None
    assert operator._HANDLE is None
    assert operator._FRAME_METRICS is None
