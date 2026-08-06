from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "src" / "gcl" / "templates" / "example-plan.md"


@pytest.fixture
def example_text() -> str:
    return EXAMPLE.read_text(encoding="utf-8")


def split(text: str) -> tuple[dict[str, Any], str]:
    """Split a plan into its frontmatter mapping and its body."""

    _, front, body = text.split("---\n", 2)
    return yaml.safe_load(front), body


def join(meta: dict[str, Any], body: str) -> str:
    return "---\n" + yaml.safe_dump(meta, sort_keys=False) + "---\n" + body


@pytest.fixture
def mutate(example_text):
    """Edit the example plan's frontmatter and hand back the whole file."""

    def _mutate(edit) -> str:
        meta, body = split(example_text)
        meta = copy.deepcopy(meta)
        edit(meta)
        return join(meta, body)

    return _mutate


@pytest.fixture
def unit_of():
    def _unit_of(meta: dict[str, Any], unit_id: str) -> dict[str, Any]:
        for unit in meta["units"]:
            if unit["unit_id"] == unit_id:
                return unit
        raise AssertionError(f"no unit {unit_id}")

    return _unit_of


@pytest.fixture
def project(tmp_path, example_text) -> Path:
    (tmp_path / "PLAN.md").write_text(example_text, encoding="utf-8")
    return tmp_path
