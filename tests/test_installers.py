"""The installers, driven for real. Reading them is not evidence that they run."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ["graph-coder-lite", "gcl-plan", "gcl-review"]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_both_installers_install_exactly_the_three_skills():
    sh_list = re.search(r"^for skill in (.+); do$", read("scripts/install.sh"), re.M)
    ps_list = re.search(r"^\$Skills = @\((.+)\)$", read("scripts/install.ps1"), re.M)
    assert sh_list and ps_list
    for source, group in (("install.sh", sh_list), ("install.ps1", ps_list)):
        for skill in ACTIVE:
            assert skill in group.group(1), f"{source} does not install {skill}"


def test_the_installers_warn_about_the_full_graph_coder_skills():
    # Both sets installed together describe the same phases under different
    # names, and a run can select either.
    for name, flag in (
        ("scripts/install.sh", "--remove-retired"),
        ("scripts/install.ps1", "-RemoveRetired"),
    ):
        text = read(name)
        assert flag in text
        assert "plan-rehearsal" in text
        assert "shadows" in text


def run_install_sh(destination, *args):
    return subprocess.run(
        ["sh", str(ROOT / "scripts" / "install.sh"), "--dest", str(destination), *args],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    )


@pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX shell unavailable")
class TestInstallSh:
    def test_it_installs_every_skill_with_its_references(self, tmp_path):
        destination = tmp_path / "skills"
        run_install_sh(destination)
        for skill in ACTIVE:
            assert (destination / skill / "SKILL.md").is_file()
        assert (destination / "graph-coder-lite" / "references" / "dispatch.md").is_file()

    def test_it_warns_about_a_superseded_skill_and_removes_it_on_request(self, tmp_path):
        destination = tmp_path / "skills"
        shadow = destination / "plan-rehearsal"
        shadow.mkdir(parents=True)
        (shadow / "SKILL.md").write_text("---\nname: plan-rehearsal\n---\n", encoding="utf-8")

        warned = run_install_sh(destination)
        assert "plan-rehearsal" in warned.stderr and "shadows" in warned.stderr
        assert shadow.is_dir(), "a warning must not delete anything on its own"

        dry = run_install_sh(destination, "--remove-retired", "--dry-run")
        assert "DRY RUN remove superseded skill" in dry.stdout
        assert shadow.is_dir(), "--dry-run deleted a directory"

        removed = run_install_sh(destination, "--remove-retired")
        assert "REMOVED superseded skill" in removed.stdout
        assert not shadow.exists()

        clean = run_install_sh(destination)
        assert "plan-rehearsal" not in clean.stderr

    def test_it_treats_an_absolute_destination_as_absolute(self, tmp_path):
        # A drive-letter destination once fell through to the relative branch and
        # the skills landed under the repository instead.
        destination = tmp_path / "skills"
        before = {path.name for path in ROOT.iterdir()}
        run_install_sh(destination)
        assert (destination / "graph-coder-lite" / "SKILL.md").is_file()
        assert {path.name for path in ROOT.iterdir()} == before, "install wrote into the repo"

    def test_it_is_idempotent(self, tmp_path):
        destination = tmp_path / "skills"
        run_install_sh(destination)
        first = (destination / "graph-coder-lite" / "SKILL.md").read_text(encoding="utf-8")
        run_install_sh(destination)
        assert (destination / "graph-coder-lite" / "SKILL.md").read_text(encoding="utf-8") == first
