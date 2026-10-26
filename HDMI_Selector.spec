# -*- mode: python ; coding: utf-8 -*-
# Build from the PARENT folder of this repo:
#   pyinstaller --noconfirm HDMI_selector/HDMI_Selector.spec
import os

from PyInstaller.utils.hooks import collect_all

ROOT = SPECPATH  # this repo (the HDMI_selector package)
ICON = os.path.join(ROOT, 'assets', 'app.ico')

datas = [(ICON, 'HDMI_selector/assets')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [os.path.join(ROOT, 'main.py')],
    pathex=[os.path.dirname(ROOT)],
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
    a.binaries,
    a.datas,
    [],
    name='HDMI_Selector',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)
