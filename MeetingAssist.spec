# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for MeetingAssist.
# NOTE: Qwen3-ASR / Whisper models are NOT bundled. They must be placed
# in a "models" folder next to the built exe at runtime (see core/config.py).

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        # sherpa-onnx ships some data files; include any that exist
        ('config.json', '.'),
    ],
    hiddenimports=collect_submodules('sherpa_onnx')
                 + collect_submodules('faster_whisper'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter.test', 'unittest', 'pydoc',
        # heavy model dirs are excluded by not listing them in datas;
        # also drop unused optional deps to slim the binary
    ],
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
    name='MeetingAssist',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI app (no console window)
    disable_windowed_traceback=False,
    icon=None,
)
