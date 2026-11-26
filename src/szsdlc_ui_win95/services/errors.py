"""Why a service refused, in words any interface can render. No status codes here."""

from __future__ import annotations


class ServiceError(Exception):
    """A refusal: a short title, the detail, and optionally the fix."""

    def __init__(self, title: str, detail: str, fix: str | None = None):
        super().__init__(detail)
        self.title = title
        self.detail = detail
        self.fix = fix


class NotFound(ServiceError):
    """What was asked for does not exist."""


class Forbidden(ServiceError):
    """This viewer was configured not to do that."""


class Invalid(ServiceError):
    """The request cannot be carried out as given."""


class Conflict(ServiceError):
    """Carrying it out would lose something; asked again with consent, it can be."""
