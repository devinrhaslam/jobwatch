import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

sys.path.insert(0, str(REPO_ROOT))

# Some sandboxed environments point PLAYWRIGHT_BROWSERS_PATH at a temporary
# cache directory that is wiped between sessions. Drop the override when it no
# longer exists so Playwright falls back to its own installed-browser cache.
_browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
if _browsers_path and not Path(_browsers_path).is_dir():
    del os.environ["PLAYWRIGHT_BROWSERS_PATH"]
