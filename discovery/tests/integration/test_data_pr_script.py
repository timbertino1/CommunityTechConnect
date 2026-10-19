"""The data PR script refuses to stage anything outside data/ (T066/T067 safety rule)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _bash() -> str | None:
    """Git's own bash on Windows (``bash`` there may be the WSL launcher); ``bash`` elsewhere."""
    if sys.platform == "win32":
        git_exe = shutil.which("git")
        for folder in Path(git_exe).resolve().parents if git_exe else []:
            for candidate in (folder / "bin" / "bash.exe", folder / "usr" / "bin" / "bash.exe"):
                if candidate.exists():
                    return str(candidate)
        return None
    return shutil.which("bash")


BASH = _bash()
GIT = shutil.which("git")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(BASH is None or GIT is None, reason="needs bash and git"),
]

SCRIPT = Path(__file__).resolve().parents[3] / ".github" / "scripts" / "data-pr.sh"


def git(repo: Path, *args: str) -> None:
    subprocess.run([GIT or "git", *args], cwd=repo, check=True, capture_output=True)  # noqa: S603 - fixed test arguments


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "test")
    (tmp_path / "data" / "events").mkdir(parents=True)
    (tmp_path / "data" / "events" / "2026-10.json").write_text("[]\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("readme\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def check(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - runs the repo's own script on a temp repo
        [BASH or "bash", SCRIPT.as_posix()],
        cwd=repo,
        env={**os.environ, "CHECK_ONLY": "1"},
        capture_output=True,
        text=True,
    )


def test_no_changes_means_nothing_to_do(repo: Path) -> None:
    result = check(repo)
    assert result.returncode == 0
    assert "nothing to do" in result.stdout


def test_changes_under_data_pass(repo: Path) -> None:
    (repo / "data" / "events" / "2026-10.json").write_text('[{"x": 1}]\n', encoding="utf-8")
    (repo / "data" / "events" / "2026-11.json").write_text("[]\n", encoding="utf-8")
    result = check(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "data/events/2026-11.json" in result.stdout


@pytest.mark.parametrize(
    "path",
    ["README.md", ".github/workflows/evil.yml", "discovery/src/netc/x.py", "datax/file.json"],
)
def test_any_change_outside_data_is_refused(repo: Path, path: str) -> None:
    (repo / "data" / "events" / "2026-10.json").write_text('[{"x": 1}]\n', encoding="utf-8")
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed\n", encoding="utf-8")
    result = check(repo)
    assert result.returncode == 1
    assert "Refusing" in result.stdout
    assert path.split("/")[0] in result.stdout


def test_the_review_snapshot_is_refused(repo: Path) -> None:
    # data/review/open.json belongs to the review PR; a data PR must never change it.
    (repo / "data" / "events" / "2026-10.json").write_text('[{"x": 1}]\n', encoding="utf-8")
    (repo / "data" / "review").mkdir()
    (repo / "data" / "review" / "open.json").write_text('["rev_0123456789ab"]\n', encoding="utf-8")
    result = check(repo)
    assert result.returncode == 1
    assert "data/review/open.json changed" in result.stdout
