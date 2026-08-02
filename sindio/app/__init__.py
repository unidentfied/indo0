import sys
from pathlib import Path

# Add the project root to sys.path for absolute imports
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

# Import the FastAPI application from the backend core package
from backend.core.app.main import app
