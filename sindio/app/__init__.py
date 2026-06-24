import sys
import pathlib

# Resolve the path to the actual FastAPI application package located in the backend core directory.
_backend_app_path = pathlib.Path(__file__).parent.parent / "backend" / "core" / "app"

if _backend_app_path.is_dir():
    # Add the backend app directory to sys.path so that submodules can be imported.
    sys.path.append(str(_backend_app_path))
    # Define the package __path__ for namespace package resolution.
    __path__ = [_backend_app_path]
else:
    raise FileNotFoundError(f"Backend app directory not found at {_backend_app_path}")
