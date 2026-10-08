"""Shared offline-first Streamlit design system.

The same CSS bundle is used by both browser and desktop-webview frontends.
"""

from pathlib import Path

CSS_PATH = Path(__file__).resolve().parent / "assets" / "powerbid.css"
APP_CSS = f"<style>\n{CSS_PATH.read_text(encoding='utf-8')}\n</style>\n"
