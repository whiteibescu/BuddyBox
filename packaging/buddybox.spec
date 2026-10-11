# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH).parent
PY = ROOT / "python"

datas_app = [(str(PY / "models" / "rfdetr_nano_coco.onnx"), "models")]
classes_json = PY / "models" / "rfdetr_nano_coco.classes.json"
if classes_json.exists():
    datas_app.append((str(classes_json), "models"))

common = dict(
    pathex=[str(PY), str(PY / "tools")],
    binaries=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PySide6", "IPython", "pytest"],
    noarchive=False,
)

a_app = Analysis(
    [str(PY / "examples" / "person_follow.py")],
    datas=datas_app,
    hiddenimports=["pygrabber.dshow_graph", "comtypes.stream"],
    **common,
)
a_rep = Analysis(
    [str(PY / "tools" / "session_report.py")],
    datas=[],
    hiddenimports=[],
    **common,
)
a_swp = Analysis(
    [str(PY / "tools" / "session_sweep.py")],
    datas=[],
    hiddenimports=[],
    **common,
)

pyz_app = PYZ(a_app.pure)
pyz_rep = PYZ(a_rep.pure)
pyz_swp = PYZ(a_swp.pure)

exe_app = EXE(
    pyz_app,
    a_app.scripts,
    [],
    exclude_binaries=True,
    name="BuddyBox",
    console=True,
    upx=False,
    icon=str(Path(SPECPATH) / "buddybox.ico"),
)
exe_rep = EXE(
    pyz_rep,
    a_rep.scripts,
    [],
    exclude_binaries=True,
    name="session_report",
    console=True,
    upx=False,
)

exe_swp = EXE(
    pyz_swp,
    a_swp.scripts,
    [],
    exclude_binaries=True,
    name="session_sweep",
    console=True,
    upx=False,
)

coll = COLLECT(
    exe_app,
    a_app.binaries,
    a_app.datas,
    exe_rep,
    a_rep.binaries,
    a_rep.datas,
    exe_swp,
    a_swp.binaries,
    a_swp.datas,
    strip=False,
    upx=False,
    name="BuddyBox",
)
