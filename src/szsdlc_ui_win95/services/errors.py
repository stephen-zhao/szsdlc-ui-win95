"""Why a service refused, in words any interface can render. No status codes here."""

from __future__ import annotations


class ServiceError(Exception):
    """A refusal: a short title, the detail, and optionally the fix."""

    def __init__(self, title: str, detail: str, fix: str | None = None, refusal: dict | None = None):
        super().__init__(detail)
        self.title = title
        self.detail = detail
        self.fix = fix
        #: szsdlc's refusal as data, `{class, problem, fix: {op, params} | None, see}`,
        #: when szsdlc refused: an interface passes it on as it is.
        self.refusal = refusal


class NotFound(ServiceError):
    """What was asked for does not exist."""


class Forbidden(ServiceError):
    """This viewer was configured not to do that."""


class Invalid(ServiceError):
    """The request cannot be carried out as given."""


class Conflict(ServiceError):
    """Carrying it out would lose something; asked again with consent, it can be."""


class Stale(ServiceError):
    """What was to be changed changed since it was read; nothing was written."""


class Rejected(ServiceError):
    """Well formed, but a gate or workflow rule declines it."""
