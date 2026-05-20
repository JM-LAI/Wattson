# -*- mode: python ; coding: utf-8 -*-
block_cipher = None

a = Analysis(
    ['wattson_app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'rumps',
        'pynput',
        'pynput.keyboard',
        'pynput.keyboard._darwin',
        'pynput.mouse',
        'pynput.mouse._darwin',
        'pyperclip',
        'objc',
        'AppKit',
        'Foundation',
        'Quartz',
        'ApplicationServices',
        'CoreFoundation',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Wattson',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Wattson',
)

app = BUNDLE(
    coll,
    name='Wattson.app',
    icon='assets/wattson.icns',
    bundle_identifier='com.lightning.wattson',
    info_plist={
        'LSUIElement': True,
        'CFBundleShortVersionString': '2.0.0',
        'CFBundleVersion': '2.0.0',
        'NSAccessibilityUsageDescription': 'Wattson needs Accessibility access to read and replace selected text.',
    },
)
