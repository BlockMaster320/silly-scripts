# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('app/ui/styles.qss', 'app/ui'),
        ('app/ui/icons', 'app/ui/icons'),
        ('app/ui/graphics', 'app/ui/graphics'),
        ('scripts/templates', 'scripts/templates'),
        ('scripts/default', 'scripts/default'),
        ('scripts/test_scripts', 'scripts/test_scripts'),
        ('app/shot_selection.py', 'app'),
    ],
    hiddenimports=[],
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
    name='SillyScripts',
    icon='app/ui/graphics/logo.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name='SillyScripts',
)
