def test_review_graph_importable():
    from review_agent.reviewer import review_graph
    assert review_graph is not None


def test_review_graph_uses_review_tools_and_skeptic_prompt():
    from review_agent import reviewer
    from review_agent.tools import REVIEW_TOOLS
    assert reviewer.REVIEW_TOOLS is REVIEW_TOOLS
    p = reviewer.REVIEW_SYSTEM_PROMPT.lower()
    assert "evidence" in p
    assert "begin_review" in p
    assert "never" in p  # objectivity/boundary language present
