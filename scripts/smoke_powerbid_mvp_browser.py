"""End-to-end course demo smoke against an isolated LOCAL PowerBid candidate.

Requires playwright + Chrome and a server running with AUTH DISABLED for
QA only (never use this flag on production). Exercises real backend calls.
Only localhost URLs are permitted; no PMSS teacher account is touched.

Example:
  python scripts/smoke_powerbid_mvp_browser.py --origin http://127.0.0.1:18570
"""
from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="http://127.0.0.1:18570")
    parser.add_argument("--chrome", default="/usr/bin/google-chrome")
    args = parser.parse_args()
    url = urlparse(args.origin)
    if url.hostname not in ("127.0.0.1", "localhost") or url.scheme != "http":
        parser.error("MVP QA must target an isolated localhost-only candidate")
    assert Path(args.chrome).is_file(), "Chrome executable not found"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=args.chrome,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        desktop = browser.new_page(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN", accept_downloads=True,
        )
        errors: list[str] = []
        statuses: list[int] = []
        desktop.on("pageerror", lambda error: errors.append(str(error)[:400]))
        desktop.on(
            "response",
            lambda response: statuses.append(response.status)
            if response.url.endswith("/api/optimize") else None,
        )
        desktop.goto(args.origin + "/", wait_until="networkidle")
        desktop.get_by_role("link", name="进入工作台").first.click()
        desktop.get_by_role("heading", name="报价策略工作台").first.wait_for()
        desktop.get_by_role("button", name="运行报价分析").first.click()
        desktop.get_by_role("heading", name="报价决策结果").first.wait_for()
        assert statuses == [200], statuses
        desktop.get_by_role("button", name="策略分析").first.click()
        with desktop.expect_download() as export:
            desktop.get_by_role("button", name="下载完整报告").click()
        file = export.value
        assert file.suggested_filename == "powerbid_single_full_report.html"
        html = Path(file.path()).read_text()
        assert "<!doctype html>" in html
        assert "700.00 MW" in html and "23" in html
        assert "本地模型" in html and "G1" in html
        assert "<table>" in html and "候选报价" in html
        assert "<script" not in html.lower()
        print("DESKTOP: home -> app -> real optimization -> printable full report OK")

        with desktop.expect_download() as csv:
            desktop.get_by_role("button", name="导出 CSV").click()
        assert csv.value.suggested_filename == "powerbid_single_analysis.csv"
        print("DESKTOP: full trial CSV download OK")

        desktop.get_by_role("button", name="参数", exact=True).click()
        panel = desktop.locator("aside.settings-panel")
        demand = panel.locator("label.field").filter(
            has_text="市场负荷"
        ).locator("input")
        demand.fill("750")
        demand.press("Tab")
        panel.get_by_role("button", name="风险分析", exact=True).click()
        desktop.get_by_role("button", name="关闭策略参数").click()
        desktop.get_by_role("button", name="压力情景").first.click()
        desktop.get_by_role("button", name="运行报价分析").first.click()
        desktop.get_by_role("heading", name="风险策略分析").first.wait_for()
        assert statuses[-1] == 200
        with desktop.expect_download() as risk_export:
            desktop.get_by_role("button", name="下载完整报告").click()
        assert risk_export.value.suggested_filename == "powerbid_risk_full_report.html"
        risk_html = Path(risk_export.value.path()).read_text()
        assert "750.00 MW" in risk_html
        assert "九组" not in risk_html  # scenario table is explicit, not vague
        assert "压力情景" in risk_html and "情景" in risk_html
        print("DESKTOP: modified 750 MW risk analysis and standalone report OK")

        desktop.get_by_role("button", name="参数", exact=True).click()
        demand = desktop.locator("aside.settings-panel").locator(
            "label.field"
        ).filter(has_text="市场负荷").locator("input")
        demand.fill("760")
        demand.press("Tab")
        desktop.get_by_role("button", name="关闭策略参数").click()
        with desktop.expect_download() as frozen:
            desktop.get_by_role("button", name="下载完整报告").click()
        old = Path(frozen.value.path()).read_text()
        assert "750.00 MW" in old and "760.00 MW" not in old
        print("REPORT: original input snapshot frozen after editing controls OK")

        phone = browser.new_page(
            viewport={"width": 390, "height": 844},
            is_mobile=True, has_touch=True, device_scale_factor=2,
            locale="zh-CN",
        )
        phone.on("pageerror", lambda error: errors.append(str(error)[:400]))
        phone.goto(args.origin + "/app", wait_until="networkidle")
        phone.get_by_role("button", name="打开菜单").click()
        phone.get_by_role("button", name="PMSS 市场分析").first.click(
            timeout=9000
        )
        phone.get_by_role("heading", name="PMSS 真实市场分析").first.wait_for()
        assert not phone.get_by_role("button", name="关闭菜单").is_visible()
        viewport = phone.evaluate(
            "() => ({client: document.documentElement.clientWidth, "
            "scroll: document.documentElement.scrollWidth})"
        )
        assert viewport["scroll"] <= viewport["client"] + 1, viewport
        print("MOBILE: overlay does not block navigation; 390px no page overflow OK")

        assert not errors, errors
        browser.close()
    print("MVP_BROWSER_SMOKE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
