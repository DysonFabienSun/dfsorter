import importlib
import site
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
site.addsitedir(str(root / ".venv" / "Lib" / "site-packages"))
sys.path.insert(0, str(root / "src"))

if __name__ == "__main__":
    sys.exit(importlib.import_module("dfsorter.ui").main())
