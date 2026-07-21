import sys
import pathlib
import os

os.environ["ENV"] = "test"

# Ensure backend/core is at the front of sys.path
project_root = pathlib.Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
else:
    sys.path.remove(str(project_root))
    sys.path.insert(0, str(project_root))

# Clear any previously loaded mock 'app' modules (from backend/app)
# This allows 'pytest app/tests/ core/tests/' to run in one process without import shadowing.
for key in list(sys.modules.keys()):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]
