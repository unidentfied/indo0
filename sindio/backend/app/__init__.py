import os

# Extend package path to include core/app/services so that imports like app.services.xxx resolve correctly
_core_services_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'core', 'app', 'services'))
if os.path.isdir(_core_services_path):
    __path__.append(_core_services_path)
