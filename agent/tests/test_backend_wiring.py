"""Backend wiring tests.

The reviewer is an independent auditor: everything it WRITES (scratch +
middleware-offloaded tool results) must stay off disk and out of any source
tree. So it uses a CompositeBackend whose default is an ephemeral StateBackend,
with /skills/ routed read-only to its own package skills dir.

The stock-agent graphs are intentionally left on a plain FilesystemBackend —
changing them is the stock-agent owner's call. Guarded here so the reviewer fix
never silently drags them along.
"""
import importlib
from pathlib import Path

import pytest
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend

REVIEWER_SKILLS_DIR = Path(__file__).resolve().parents[1] / "src" / "review_agent" / "skills"


def _backend(module_path):
    return importlib.import_module(module_path).backend


# --- Reviewer: ephemeral writable surface, skills routed read-only ---

def test_reviewer_uses_composite_backend():
    assert isinstance(_backend("review_agent.reviewer"), CompositeBackend)


def test_reviewer_writable_default_is_ephemeral_state():
    # Scratch + middleware offload land in graph state, never on disk / in source.
    assert isinstance(_backend("review_agent.reviewer").default, StateBackend)


def test_reviewer_skills_route_confined_to_its_own_skills_dir():
    route = _backend("review_agent.reviewer").routes["/skills/"]
    assert isinstance(route, FilesystemBackend)
    assert route.cwd == REVIEWER_SKILLS_DIR.resolve()


def test_reviewer_reads_its_skill_through_route():
    result = _backend("review_agent.reviewer").read("/skills/review-general/SKILL.md")
    assert result.error is None
    assert result.file_data["content"]


def test_reviewer_lists_its_skill_dirs():
    listing = _backend("review_agent.reviewer").ls("/skills/")
    assert listing.error is None
    assert any("review-" in entry["path"] for entry in listing.entries)


# --- Stock agent: intentionally unchanged (plain FilesystemBackend) ---

@pytest.mark.parametrize("module_path", ["stock_agent.agent", "stock_agent.autonomy"])
def test_stock_agent_left_on_filesystem_backend(module_path):
    assert isinstance(_backend(module_path), FilesystemBackend)
