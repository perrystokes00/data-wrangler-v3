# catalog_capture.py (root) — shim; canonical implementation lives in modules/
from modules.catalog_capture import *          # noqa: F401,F403
from modules.catalog_capture import (           # explicit, for `from catalog_capture import X`
    capture, reset_replace_state,
)
