"""The CLI, driven the way a run drives it: end to end, against real files."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

from gcl.cli import main


def run(*argv: str) -> tuple[int, dict]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(list(argv))
    return code, json.loads(buffer.getvalue())


def gcl(project, *argv: str) -> tuple[int, dict]:
    return run("--root", str(project), *argv)


def test_check_passes_on_the_example_plan(project):
    code, payload = gcl(project, "check")
    assert code == 0
    assert payload["defects"] == []
    assert payload["topological_order"][0] == "IU-MIGRATION"


def test_check_reports_every_defect_at_once_not_the_first(project):
    text = (project / "PLAN.md").read_text(encoding="utf-8")
    text = text.replace("manager_id: M-STORAGE", "manager_id:", 1).replace(
        "risk: high", "risk: extreme", 1
    )
    (project / "PLAN.md").write_text(text, encoding="utf-8")
    code, payload = gcl(project, "check")
    assert code == 1
    assert len(payload["defects"]) >= 2


def test_emit_refuses_to_declare_an_unrouted_plan_ready(project):
    code, payload = gcl(project, "emit")
    assert code == 0
    assert payload["preflight"]["ready_to_dispatch"] is False
    assert payload["preflight"]["unrouted_units"] == ["IU-MIGRATION", "IU-SCHEMA"]


def test_emit_only_offers_the_frontier(project):
    _, payload = gcl(project, "emit")
    assert [entry["id"] for entry in payload["spawn"]] == ["IU-MIGRATION", "IU-SCHEMA"]


class TestRouteSet:
    def test_it_fills_every_placeholder_in_one_call(self, project):
        # Hand-editing is not the fallback: every unrouted unit holds the
        # identical line `primary: local`, so a text edit cannot target one.
        code, payload = gcl(project, "route", "set", "--model", "m1", "--fallback", "m2")
        assert code == 0
        assert payload["routed"] == ["IU-MIGRATION", "IU-SCHEMA", "IU-STORE", "IU-ENDPOINT"]
        _, emitted = gcl(project, "emit")
        assert emitted["preflight"]["unrouted_units"] == []
        assert emitted["spawn"][0]["model"] == "m1"
        assert emitted["spawn"][0]["fallback_model"] == "m2"

    def test_it_can_target_exactly_one_unit(self, project):
        gcl(project, "route", "set", "--model", "m1", "--unit", "IU-STORE")
        _, payload = gcl(project, "check")
        assert payload["defects"] == []
        _, emitted = gcl(project, "emit", "--unit", "IU-STORE")
        assert emitted["spawn"][0]["model"] == "m1"
        _, still = gcl(project, "emit", "--unit", "IU-MIGRATION")
        assert still["spawn"][0]["model"] == "local"

    def test_the_plan_still_parses_after_rewriting(self, project):
        gcl(project, "route", "set", "--model", "m1", "--fallback", "m2")
        code, payload = gcl(project, "check")
        assert code == 0 and payload["defects"] == []

    def test_it_records_where_the_choice_came_from(self, project):
        _, payload = gcl(
            project, "route", "set", "--model", "m1", "--evidence", "harness_model_list"
        )
        assert payload["evidence"] == "harness_model_list"
        state = json.loads((project / ".gcl" / "state.json").read_text(encoding="utf-8"))
        assert state["events"][-1]["evidence"] == "harness_model_list"


class TestApprove:
    def test_a_summary_is_not_an_approval_view(self, project):
        gcl(project, "route", "set", "--model", "m1")
        code, payload = gcl(project, "approve")
        assert code == 1
        assert "not a summary" in payload["error"]

    def test_approval_binds_to_the_unit_contracts(self, project):
        gcl(project, "route", "set", "--model", "m1")
        code, payload = gcl(project, "approve", "--rendered")
        assert code == 0
        first = payload["plan_hash"]
        _, emitted = gcl(project, "emit")
        assert emitted["preflight"]["ready_to_dispatch"] is True

        text = (project / "PLAN.md").read_text(encoding="utf-8")
        text = text.replace(
            "    write_scope: [src/api/schemas.py, tests/test_schemas.py]",
            "    write_scope: [src/api/schemas.py]",
        )
        (project / "PLAN.md").write_text(text, encoding="utf-8")
        _, second = gcl(project, "check")
        assert second["defects"] == []
        _, rehash = gcl(project, "approve", "--rendered")
        assert rehash["plan_hash"] != first

    def test_a_plan_with_defects_cannot_be_approved(self, project):
        code, payload = gcl(project, "approve", "--rendered")
        assert code == 0  # unrouted is a preflight matter, not a readiness defect
        text = (project / "PLAN.md").read_text(encoding="utf-8")
        (project / "PLAN.md").write_text(text.replace("readiness: ready", "readiness: draft"))
        code, payload = gcl(project, "approve", "--rendered")
        assert code == 1 and "cannot be approved" in payload["error"]


def test_status_reports_what_blocks_what(project):
    code, payload = gcl(project, "status")
    assert code == 0
    assert payload["frontier"] == ["IU-MIGRATION", "IU-SCHEMA"]
    assert payload["waiting_on_dependencies"]["IU-STORE"] == ["IU-MIGRATION"]
    assert payload["complete"] is False


def test_set_refuses_a_worker_completing_itself(project):
    gcl(project, "set", "IU-MIGRATION", "ready")
    gcl(project, "set", "IU-MIGRATION", "running")
    code, payload = gcl(project, "set", "IU-MIGRATION", "completed")
    assert code == 1
    assert "manager verdict" in payload["error"]
    assert "gcl review" in payload["error"]


def test_set_rejects_a_unit_the_plan_does_not_have(project):
    code, payload = gcl(project, "set", "IU-GHOST", "ready")
    assert code == 1 and "no unit IU-GHOST" in payload["error"]


def test_a_completed_dependency_releases_its_dependent(project):
    for target in ("ready", "running", "awaiting_review"):
        gcl(project, "set", "IU-MIGRATION", target)
    gcl(project, "review", "IU-MIGRATION", "--verdict", "pass", "--evidence", "make migrate-test")
    _, payload = gcl(project, "status")
    assert "IU-STORE" in payload["frontier"]


def test_verify_gathers_evidence_without_deciding_the_verdict(project):
    (project / "src" / "store").mkdir(parents=True)
    (project / "src" / "store" / "tokens.py").write_text("def revoke_token(): ...\n")
    code, payload = gcl(project, "verify", "IU-STORE")
    assert code == 0
    assert payload["review_owner"] == "M-STORAGE"
    assert payload["missing_paths"] == ["tests/test_token_store.py"]
    assert "not its existence" in payload["next"]
    assert "verdict" not in payload


def test_init_writes_a_plan_that_passes_check(tmp_path):
    code, payload = run("--root", str(tmp_path), "init")
    assert code == 0 and payload["created"] is True
    code, _ = run("--root", str(tmp_path), "check")
    assert code == 0


def test_init_does_not_overwrite_an_existing_plan(project):
    original = (project / "PLAN.md").read_text(encoding="utf-8")
    (project / "PLAN.md").write_text(original + "\nedited\n", encoding="utf-8")
    _, payload = gcl(project, "init")
    assert payload["created"] is False
    assert (project / "PLAN.md").read_text(encoding="utf-8").endswith("edited\n")


def test_a_missing_plan_names_the_fix(tmp_path):
    code, payload = run("--root", str(tmp_path), "check")
    assert code == 1
    assert "gcl init" in payload["error"]
