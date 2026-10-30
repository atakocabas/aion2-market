# PyInstaller build of the desktop app (src/aion2market/app.py, entry: __main__.py) as a single windowed exe.
#   .venv\Scripts\pip install -e ".[app]"
#   .venv\Scripts\pyinstaller aion2market.spec      -> dist\Aion2Market.exe
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["src/aion2market/__main__.py"],
    pathex=["src"],
    datas=[("src/aion2market/web", "aion2market/web")],
    # scapy loads its layers by name at runtime.
    hiddenimports=collect_submodules("scapy.layers")
    + collect_submodules("aion2market", filter=lambda name: name != "aion2market.mcp_server"),
    excludes=["mcp", "aion2market.mcp_server", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="Aion2Market",
    console=False,
    upx=False,
)
