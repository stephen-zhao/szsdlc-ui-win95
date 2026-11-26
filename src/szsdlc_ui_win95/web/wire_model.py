"""The wire model: the HTTP request and response types. Operation `Foo` has `FooRequest`
and `FooResponse`.

They describe the API (`/api/openapi.json`) and validate request bodies.
Handlers render responses themselves, so the bytes stay exactly the viewer's.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, RootModel, StrictBool


class ProjectSummary(BaseModel):
    """One project, as the project list and Open project report it."""
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    entity_count: int


class MetaResponse(BaseModel):
    viewer: str
    version: str
    szsdlc_version: str
    readonly: bool


class ListProjectsResponse(RootModel[list[ProjectSummary]]):
    """Every project this viewer serves."""


class OpenProjectRequest(BaseModel):
    """A folder on this computer, or where a backend keeps a project."""
    model_config = ConfigDict(extra="ignore")
    location: str | None = None
    #: The 0.1 name for `location`, still accepted.
    store: str | None = None
    code_root: str | None = None


class OpenProjectResponse(ProjectSummary):
    """The project just opened."""


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    #: Replace unsent changes rather than refuse (409).
    replace: StrictBool = False


class RefreshResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    arrived: bool
    replaced: bool
    note: str | None = None
    project: ProjectSummary
