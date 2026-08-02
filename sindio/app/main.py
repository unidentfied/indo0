import os
import sys

# Add the project root to sys.path so absolute imports like backend.core.app work
_current_dir = os.path.abspath(os.path.dirname(__file__))
_project_root = os.path.abspath(os.path.join(_current_dir, ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from backend.core.app.main import app  # noqa: F401
