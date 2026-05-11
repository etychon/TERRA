"""Smoke tests: repository scaffolding and required entrypoints."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_required_entrypoints_exist() -> None:
    assert (REPO_ROOT / "README.md").is_file()
    assert (REPO_ROOT / "AGENTS.md").is_file()
    assert (REPO_ROOT / "LLM_CONTEXT.md").is_file()
    assert (REPO_ROOT / "LICENSE").is_file()
    root_pkg = REPO_ROOT / "package.json"
    assert root_pkg.is_file()
    text = root_pkg.read_text(encoding="utf-8")
    assert '"lint"' in text and "workspaces" in text and "terra-dashboard-frontend" in text


def test_specs_present() -> None:
    specs = REPO_ROOT / "specs"
    for name in (
        "architecture.md",
        "domain.md",
        "style.md",
        "integrations.md",
        "design-system.md",
    ):
        assert (specs / name).is_file()


def test_expected_directories_exist() -> None:
    for relative in ("src", "tests", "data", "notebooks", "models", "docs", "specs", "frontend"):
        assert (REPO_ROOT / relative).is_dir()


def test_frontend_token_layers_exist() -> None:
    fe = REPO_ROOT / "frontend"
    assert (fe / "package.json").is_file()
    assert (fe / "src" / "tokens" / "primitives.ts").is_file()
    assert (fe / "src" / "tokens" / "semantic.ts").is_file()
    assert (fe / "src" / "tokens" / "components.ts").is_file()
    assert (fe / "src" / "styles" / "globals.css").is_file()


def test_ui_skill_present() -> None:
    skill = (
        REPO_ROOT
        / ".cursor"
        / "skills"
        / "terra-ui-design-system"
        / "SKILL.md"
    )
    assert skill.is_file()
