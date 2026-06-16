from pathlib import Path

SKILL = Path(__file__).parent.parent / "src/review_agent/skills/review-strategy-conformance/SKILL.md"


def test_a1_skill_exists_and_satisfies_authoring_rubric():
    assert SKILL.exists()
    text = SKILL.read_text()
    # identity + memory scope (authoring rubric)
    assert "name: review-strategy-conformance" in text
    assert "memory_namespace: conformance" in text
    # disjoint description
    assert "Use when" in text and "Do NOT use" in text
    # the final review loop: begin → verdict → consolidate
    assert "begin_review" in text
    assert "write_review" in text
    assert "record_insight" in text
    # self-check / fit-check on entry
    assert "fit-check" in text.lower() or "self-announce" in text.lower()
