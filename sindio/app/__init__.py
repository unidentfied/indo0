import sys
from pathlib import Path

# Add the backend directory to sys.path to allow importing 'app'
_backend_path = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(_backend_path))

from app import *
