"""Build a single local EXE from this code and the user's installed Vector files."""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


root = Path(__file__).resolve().parent
vector = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / "Documents" / "Vector2.1弹道版"
dll = vector / "dd" / "dd63330.dll"
weapons = vector / "config" / "weapons.json"
images = vector / "ModPic" / "2560x1440"
settings = vector / "config" / "app_settings.json"
for path in (dll, weapons, images, settings):
    if not path.exists():
        raise SystemExit(f"缺少本机文件：{path}")

with tempfile.TemporaryDirectory() as tmp:
    staged = Path(tmp) / "vector"
    (staged / "config").mkdir(parents=True)
    shutil.copy2(weapons, staged / "config" / "weapons.json")
    shutil.copytree(images, staged / "ModPic" / images.name)
    original = json.loads(settings.read_text(encoding="utf-8"))
    keys = ("gameResW", "gameResH", "roiX", "roiY", "roiW", "roiH", "matchThreshold", "detectInterval", "scaleFactor")
    (staged / "config" / "app_settings.json").write_text(json.dumps({key: original[key] for key in keys if key in original}), encoding="utf-8")
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "OfficeLogoDrag-Portable", "--hidden-import", "kmNet", "--hidden-import", "dxcam",
        "--hidden-import", "comtypes", "--hidden-import", "serial",
        "--add-binary", f"{root / 'kmNet.cp312-win_amd64.pyd'};.",
        "--add-binary", f"{dll};dd", "--add-data", f"{root / 'WEBUI'};WEBUI",
        "--add-data", f"{staged};vector", str(root / "main.py")
    ], cwd=root, check=True)
