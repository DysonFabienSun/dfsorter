import importlib
import site
import sys
from pathlib import Path

if sys.platform == "win32":
    import ctypes

    # Identify the Python host before loading Qt or application modules.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DFSorter.Desktop")

root = Path(__file__).resolve().parent
site.addsitedir(str(root / ".venv" / "Lib" / "site-packages"))
sys.path.insert(0, str(root / "src"))

if __name__ == "__main__":
    sys.exit(importlib.import_module("dfsorter.ui").main())
