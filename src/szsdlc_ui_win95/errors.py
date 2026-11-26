"""Errors shown to a person, with a message fit to show."""


class ProjectError(ValueError):
    """A location that cannot be opened as a project."""


class UnsentChanges(ProjectError):
    """Refreshing would replace the copy's unsent changes."""
