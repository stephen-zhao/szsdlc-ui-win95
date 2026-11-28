"""The wire model: the HTTP request and response types. Operation `Foo` has `FooRequest`
and `FooResponse`.

They describe the API (`/api/openapi.json`) and validate request bodies.
Handlers render responses themselves, so the bytes stay exactly the viewer's.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, RootModel, StrictBool, StrictFloat, StrictInt, StrictStr


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
    #: The project asset root: the code and other assets the project describes.
    asset_root: str | None = None
    #: The 0.1 name for `asset_root`, still accepted for one release.
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


# -- edits ------------------------------------------------------------------
# Every edit names the content hash the page was drawn from (`expect`): szsdlc
# refuses the write if the item changed since.

class SetRequest(BaseModel):
    """Fields and the status, through `szsdlc set`."""
    model_config = ConfigDict(extra="forbid")
    expect: str
    #: field → value, applied in order. A bool or number is sent as szsdlc reads it.
    values: dict[str, StrictStr | StrictBool | StrictInt | StrictFloat]
    #: Override the workflow for a status; needs `reason`.
    force: StrictBool = False
    reason: str | None = None


class TagRequest(BaseModel):
    """Tags to add (`tag`) or remove (`untag`)."""
    model_config = ConfigDict(extra="forbid")
    expect: str
    tags: list[StrictStr]


class CaptureRequest(BaseModel):
    """A thought for `szsdlc capture`: its first line is the summary."""
    model_config = ConfigDict(extra="forbid")
    text: StrictStr
    #: The intake type's name, from the schema descriptor; needed when there are several.
    type: StrictStr | None = None


class Edit(BaseModel):
    """One change this viewer made since the last send."""
    at: str
    ref: str
    op: str
    summary: str


class ChangesResponse(BaseModel):
    """Whether the project has unsent changes, and the ones this viewer made."""
    unsent: bool
    edits: list[Edit]
    #: Unsent changes this viewer did not make (the CLI, an agent, an earlier run).
    outside: bool


class FindingCounts(BaseModel):
    errors: int
    warnings: int


class EditResponse(BaseModel):
    """The post-state of an edit."""
    #: szsdlc's own result for the operation.
    result: dict
    #: The item as it is now, with its new `hash`.
    entity: dict
    changes: ChangesResponse
    findings: FindingCounts | None = None


class SendResponse(BaseModel):
    #: The views redrawn before sending.
    changed: list[str]
    #: Others' changes arrived: reload.
    arrived: bool
    #: Local changes were sent.
    sent: bool
    changes: ChangesResponse


class Finding(BaseModel):
    level: str
    kind: str
    ref: str
    message: str
    fix: str | None = None


class FindingsResponse(FindingCounts):
    total: int
    rows: list[Finding]
