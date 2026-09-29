from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent

streamlit_datas, streamlit_binaries, streamlit_hidden = collect_all("streamlit")
powerbid_hidden = collect_submodules("powerbid")

datas = list(streamlit_datas)
datas.append((str(ROOT / "app" / "streamlit_app.py"), "app"))
for path in (ROOT / "data").rglob("*"):
    if path.is_file():
        destination = str(path.relative_to(ROOT).parent)
        datas.append((str(path), destination))

hiddenimports = streamlit_hidden + powerbid_hidden + [
    "pandas",
    "altair",
    "pyarrow",
]

a = Analysis(
    [str(ROOT / "app" / "windows_launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=streamlit_binaries,
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
    a.binaries,
    a.datas,
    [],
    name="PowerBidLab",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
