import os
import sys

# Add the backend/app directory to sys.path so we can import its main module
_current_dir = os.path.abspath(os.path.dirname(__file__))
_backend_app_path = os.path.abspath(os.path.join(_current_dir, "..", "backend", "app"))
if _backend_app_path not in sys.path:
    sys.path.insert(0, _backend_app_path)

# Re-export the FastAPI app instance
from main import app  # noqa: F401
