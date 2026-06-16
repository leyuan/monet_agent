"""
Structural well-formedness tests for Phase 2 reviewer skills.

These tests check that each SKILL.md:
  - exists on disk
  - declares the correct name and memory_namespace in frontmatter
  - carries disjoint use/don't-use guidance
  - contains the required review loop calls (begin_review, write_review)
  - contains record_insight (except review-general, which is the fallback)
  - for review-general: contains refusal language ("refus")
"""
from pathlib import Path

import pytest

SKILLS_ROOT = Path(__file__).parent.parent / "src/review_agent/skills"

# (directory-name, memory_namespace, expect_record_insight)
PHASE2_SKILLS = [
    ("review-decision-quality", "decision_quality", True),
    ("review-strategy-efficacy", "efficacy", True),
    ("review-tool-fidelity", "tool_fidelity", True),
    ("review-operation-success", "operation_success", True),
    ("review-general", "general", False),
]


@pytest.mark.parametrize("dir_name,namespace,expect_insight", PHASE2_SKILLS)
def test_skill_file_exists(dir_name, namespace, expect_insight):
    skill_path = SKILLS_ROOT / dir_name / "SKILL.md"
    assert skill_path.exists(), f"Missing SKILL.md for {dir_name}"


@pytest.mark.parametrize("dir_name,namespace,expect_insight", PHASE2_SKILLS)
def test_skill_name_in_frontmatter(dir_name, namespace, expect_insight):
    text = (SKILLS_ROOT / dir_name / "SKILL.md").read_text()
    assert f"name: {dir_name}" in text, (
        f"{dir_name}/SKILL.md missing 'name: {dir_name}' in frontmatter"
    )


@pytest.mark.parametrize("dir_name,namespace,expect_insight", PHASE2_SKILLS)
def test_skill_namespace_in_frontmatter(dir_name, namespace, expect_insight):
    text = (SKILLS_ROOT / dir_name / "SKILL.md").read_text()
    assert f"memory_namespace: {namespace}" in text, (
        f"{dir_name}/SKILL.md missing 'memory_namespace: {namespace}'"
    )


@pytest.mark.parametrize("dir_name,namespace,expect_insight", PHASE2_SKILLS)
def test_skill_has_use_when_and_do_not_use(dir_name, namespace, expect_insight):
    text = (SKILLS_ROOT / dir_name / "SKILL.md").read_text()
    assert "Use when" in text, f"{dir_name}/SKILL.md missing 'Use when'"
    assert "Do NOT use" in text, f"{dir_name}/SKILL.md missing 'Do NOT use'"


@pytest.mark.parametrize("dir_name,namespace,expect_insight", PHASE2_SKILLS)
def test_skill_has_begin_review(dir_name, namespace, expect_insight):
    text = (SKILLS_ROOT / dir_name / "SKILL.md").read_text()
    assert "begin_review" in text, f"{dir_name}/SKILL.md missing 'begin_review'"


@pytest.mark.parametrize("dir_name,namespace,expect_insight", PHASE2_SKILLS)
def test_skill_has_write_review(dir_name, namespace, expect_insight):
    text = (SKILLS_ROOT / dir_name / "SKILL.md").read_text()
    assert "write_review" in text, f"{dir_name}/SKILL.md missing 'write_review'"


@pytest.mark.parametrize("dir_name,namespace,expect_insight", PHASE2_SKILLS)
def test_skill_record_insight_presence(dir_name, namespace, expect_insight):
    text = (SKILLS_ROOT / dir_name / "SKILL.md").read_text()
    if expect_insight:
        assert "record_insight" in text, (
            f"{dir_name}/SKILL.md missing 'record_insight' (required for non-fallback skills)"
        )
    else:
        # review-general may or may not include record_insight — no assertion either way
        pass


def test_review_general_has_refusal_language():
    text = (SKILLS_ROOT / "review-general" / "SKILL.md").read_text()
    assert "refus" in text.lower(), (
        "review-general/SKILL.md missing refusal language ('refus')"
    )
