from __future__ import annotations

import os
import time

import pytest

from szsdlc_ui_win95.project import Project, ProjectError, norm_id, plain, pluralize


def test_schema_comes_from_szsdlc_config(project):
    p = Project(project)
    s = p.schema
    assert s["source"] == "szsdlc"
    assert s["parent_relation"] == "parent"
    assert s["dependency_relation"] == "depends_on" and s["dependency_source"] == "convention"
    wi = next(t for t in s["types"] if t["prefix"] == "WI")
    assert wi["label"] == "Work item" and wi["plural"] == "Work items"
    assert wi["flags"]["tracks_progress"] and wi["flags"]["actionable"] and not wi["flags"]["can_parent"]
    states = {st["name"]: st for st in wi["workflow"]["statuses"]}
    assert wi["workflow"]["initial"] == "idea"
    assert states["done"]["terminal"] and not states["ready"]["terminal"]
    assert states["dropped"]["abandoned"]
    assert states["planned"]["requires_artifact"] == ["design.md"]
    assert states["ready"]["count"] == 1
    assert wi["progress_artifact"] == "plan.md"
    rel = {r["name"]: r for r in s["relations"]}
    assert rel["implements"]["inverse"] == "implemented_by"
    assert rel["implements"]["source_types"][:1] == ["WI"] and rel["implements"]["target_types"] == ["REQ"]
    epic = next(t for t in s["types"] if t["prefix"] == "EPIC")
    assert [d["kind"] for d in epic["derived"]] == ["aggregate_progress"]


def test_rows_carry_traits_placement_and_authored_relations(project):
    p = Project(project)
    rows = {r["id"]: r for r in p.rows()}
    wi = rows["WI-0001"]
    assert wi["progress"]["done"] == 2 and wi["progress"]["total"] == 3
    assert wi["progress"]["source"].endswith("/plan.md")
    assert wi["placement"] == {"roadmap": "roadmap", "horizon": "now", "position": 1}
    assert wi["parent"] == "EPIC-0001" and wi["tags"] == ["ui"]
    assert ["implements", "REQ-0001"] in wi["relations"]
    assert rows["EPIC-0001"]["children"] == 2
    assert rows["IDEA-0001"]["layout"] == "section"
    assert rows["REQ-0001"]["progress"] is None  # a type that does not track progress has none, not 0/0


def test_entity_detail_has_derived_inverses_and_documents(project, code_root):
    p = Project(project, code_root)
    req = p.entity("req-1")
    assert req["derived"] == {"covered": True, "delivered": False}
    assert {"direction": "in", "kind": "implements", "inverse": "implemented_by", "id": "WI-0001", "resolved": True} in req["relations"]
    epic = p.entity("EPIC-0001")
    assert epic["derived"]["progress"]["children"] == 2 and epic["derived"]["progress"]["percent"] == 0
    assert sorted(epic["children_ids"]) == ["WI-0001", "WI-0002"]
    docs = {d["name"]: d for d in p.entity("WI-0001")["documents"]}
    assert docs["entity.md"]["kind"] == "record"
    assert docs["plan.md"]["kind"] == "artifact" and docs["design.md"]["kind"] == "artifact"
    assert docs["../../docs/guide.md"]["root"] == "code" and docs["../../docs/guide.md"]["exists"]
    assert docs["../../requirements/REQ-0001-every-view-follows-traits.md"]["entity"] == "REQ-0001"
    assert docs["https://example.org/spec"]["kind"] == "link"
    assert p.entity("WI-9999") is None


def test_out_of_tree_reference_without_a_code_root_says_so(project):
    docs = {d["name"]: d for d in Project(project).entity("WI-0001")["documents"]}
    assert docs["docs/guide.md"]["exists"] is False and docs["docs/guide.md"]["root"] == "code?"


def test_doc_reading_is_contained(project, code_root):
    p = Project(project, code_root)
    d = p.doc("store", "epics/EPIC-0001-ship-the-viewer.md")
    assert d["exists"] and d["kind"] == "markdown" and d["entity"] == "EPIC-0001"
    assert d["frontmatter"]["id"] == "EPIC-0001" and d["raw"].startswith("---")
    assert p.doc("code", "docs/guide.md")["text"].startswith("# Guide")
    assert p.doc("store", "docs/guide.md", fallback=True)["root"] == "code"
    assert p.doc("store", "../code/docs/guide.md")["exists"] is False
    (project / ".git").mkdir()
    (project / ".git" / "config").write_text("[core]\n")
    assert p.doc("store", ".git/config")["exists"] is False
    (project / "blob.bin").write_bytes(b"\x00\x01binary")
    assert p.doc("store", "blob.bin")["kind"] == "binary"


def test_store_documents_list_generated_views_first(project):
    docs = Project(project).store_docs
    assert docs and docs[0]["generated"]
    assert any(d["path"] == "views/board.md" for d in docs)


def test_a_nested_store_is_its_own_project(project, tmp_path):
    import shutil
    from conftest import szsdlc
    built = tmp_path / "inner"  # szsdlc refuses to init inside a project, so build it beside, then move it in
    built.mkdir()
    szsdlc(built, "init")
    szsdlc(built, "new", "epic", "--title", "Inner epic")
    szsdlc(built, "render")
    inner = project / "examples" / "inner"
    inner.parent.mkdir()
    shutil.move(str(built), str(inner))
    p = Project(project)
    assert not any(d["path"].startswith("examples/") for d in p.store_docs)
    assert len(p.store_model) == 5
    assert Project(inner / "epics").store == inner.resolve()


def test_refresh_reloads_and_keeps_the_last_good_model_on_failure(project):
    p = Project(project)
    epic = project / "epics" / "EPIC-0001-ship-the-viewer.md"
    epic.write_text(epic.read_text().replace("Ship the viewer", "Ship it"), encoding="utf-8")
    bump = time.time() + 5
    os.utime(epic, (bump, bump))
    p.refresh()
    assert p.entity("EPIC-0001")["title"] == "Ship it" and p.load_error is None
    cfg = project / ".szsdlc" / "config.yml"
    cfg.write_text("entity_types: [not, a, mapping]\n", encoding="utf-8")
    os.utime(cfg, (bump + 5, bump + 5))
    p.refresh()
    assert p.load_error and p.entity("EPIC-0001")["title"] == "Ship it"
    assert p.info()["load_error"] == p.load_error


def test_info_and_snapshot_hide_local_paths(project, code_root):
    p = Project(project, code_root)
    info = p.info()
    assert info["backend"]["kind"] == "workdir" and info["readonly"]
    assert info["unparseable"] == [] and info["duplicates"] == []
    snap = p.snapshot()
    assert snap["project"]["store"] == "proj" and snap["project"]["code_root"] == "code"
    assert "code:docs/guide.md" in snap["docs"]
    assert set(snap["details"]) == {r["id"] for r in snap["entities"]}


def test_not_a_project():
    with pytest.raises(ProjectError, match="not a szsdlc project"):
        Project("/")


def test_helpers():
    assert norm_id("wi-42") == norm_id("WI-0042") == "WI-42" and norm_id("nope") is None
    assert [pluralize(x) for x in ("Work item", "Hypothesis", "Story", "Day", "Box")] == ["Work items", "Hypotheses", "Stories", "Days", "Boxes"]
    from szsdlc.graph import Aggregate
    from szsdlc.model import Progress
    out = plain(Aggregate(children=2, terminal=1, tasks=Progress(3, 4)))
    assert out["percent"] == 50 and out["tasks"]["done"] == 3
