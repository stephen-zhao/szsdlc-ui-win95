"""The services layer: what the viewer does, as plain Python, for any interface.

Framework-free: nothing here imports FastAPI, Starlette, uvicorn or pydantic,
or anything in `szsdlc_ui_win95.web`; a test holds that line (see AGENTS.md,
"Layers"). Dependencies arrive through constructors, never a framework's
injection.
"""

from .errors import Conflict, Forbidden, Invalid, NotFound, Rejected, ServiceError, Stale
from .viewer import Raw, ViewerService

__all__ = ["ServiceError", "NotFound", "Forbidden", "Invalid", "Conflict", "Stale", "Rejected", "Raw", "ViewerService"]
