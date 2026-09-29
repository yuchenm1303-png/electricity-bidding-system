from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent

streamlit_datas, streamlit_binaries, streamlit_hidden = collect_all("streamlit")
webview_datas, webview_binaries, webview_hidden = collect_all("webview")
powerbid_hidden = collect_submodules("powerbid")

datas = list(streamlit_datas) + list(webview_datas)
datas.append((str(ROOT / "app" / "streamlit_app.py"), "app"))
for path in (ROOT / "data").rglob("*"):
    if path.is_file():
        destination = str(path.relative_to(ROOT).parent)
        datas.append((str(path), destination))

binaries = list(streamlit_binaries) + list(webview_binaries)
hiddenimports = streamlit_hidden + webview_hidden + powerbid_hidden + [
    "pandas",
    "altair",
    "pyarrow",
    "webview",
]

a = Analysis(
    [str(ROOT / "app" / "windows_launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PowerBidLab",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PowerBidLab",
)
