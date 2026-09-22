# PyInstaller onefile p/ Windows (duplo clique, sem Python instalado).
# Build oficial: GitHub Actions (runner Windows). Ver .github/workflows/ci.yml
# Uso local (Windows com Python): pip install pyinstaller pyserial && pyinstaller WheelBridge.spec

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("server/web", "server/web")],
    hiddenimports=["serial.tools.list_ports"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="WheelBridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # janela de status (F5 visível); sem terminal manual
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
