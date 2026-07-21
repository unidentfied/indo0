import os

# Extend this package's __path__ to include the core app services directory.
# The core services are located at ../../core/app/services relative to this file.
_core_services_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'core', 'app', 'services'))
if os.path.isdir(_core_services_path):
    __path__.append(_core_services_path)
