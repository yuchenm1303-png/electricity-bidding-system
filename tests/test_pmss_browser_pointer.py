"""No school API requests; verify rendered screenshots map into Chrome CSS pixels."""
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pmss_browser_operator as browser


def test_school_screenshot_pixel_ratio():
    metrics = (1356, 676, 1695, 845)
    assert browser._screenshot_to_css(960, 280, metrics) == (1200, 350)
    assert browser._screenshot_to_css(0, 0, metrics) == (0, 0)
    with pytest.raises(ValueError):
        browser._screenshot_to_css(1356, 20, metrics)
    with pytest.raises(ValueError):
        browser._screenshot_to_css(1, 2, None)


def test_click_uses_css_coordinates_and_reports_focus(monkeypatch):
    monkeypatch.setattr(browser, "_FRAME_METRICS", (1356, 676, 1695, 845))
    class Dummy:
        current_url = "http://cq.university.netts-dev.tsintergy.com/"
        def __init__(self):
            self.events = []
        def execute_cdp_cmd(self, name, params):
            self.events.append((name, params))
        def execute_script(self, source):
            return True
    d = Dummy()
    assert browser._act(d, {"action": "click", "x": 960, "y": 280}) == {
        "focused_input": True
    }
    assert len(d.events) == 3
    assert [item[1]["type"] for item in d.events] == [
        "mouseMoved", "mousePressed", "mouseReleased"
    ]
    assert all(item[1]["x"] == 1200 and item[1]["y"] == 350 for item in d.events)
