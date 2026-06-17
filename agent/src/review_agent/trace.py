"""Read-only LangSmith trace evidence for the reviewer.

Reads the TRADING agent's run traces (tool calls + timing + errors) as evidence.
Project name comes from LANGSMITH_PROJECT. The reviewer only READS LangSmith.
"""
import os

from langsmith import Client


def select_roots_by_name(roots, graph_name: str, limit: int):
    """Pure: keep only roots whose name == graph_name (excludes reviewer/chat runs),
    preserving order, capped at limit."""
    return [r for r in roots if r.name == graph_name][:limit]


def read_run_trace(run_id: str | None = None, graph_name: str = "autonomous_loop",
                   limit: int = 5, config=None) -> dict:
    """Fetch trader run trace(s). Filters to `graph_name` (the trader graph) so the
    reviewer never audits its own or the chat graph's runs. `config` is accepted and
    ignored (runtime-injected; keeps the tool signature uniform)."""
    project = os.environ.get("LANGSMITH_PROJECT", "monet_agent")
    client = Client()

    if run_id:
        roots = [client.read_run(run_id)]
    else:
        # over-fetch then filter by name (a mixed project holds several graphs)
        raw = list(client.list_runs(project_name=project, is_root=True, limit=max(limit * 5, 25)))
        roots = select_roots_by_name(raw, graph_name, limit)

    runs_out = []
    for root in roots:
        children = list(client.list_runs(project_name=project, trace_id=root.trace_id))
        tool_calls = [
            {"name": c.name, "inputs": c.inputs, "outputs": c.outputs, "error": c.error,
             "start_time": str(c.start_time) if c.start_time else None,
             "end_time": str(c.end_time) if c.end_time else None}
            for c in children if c.run_type == "tool"
        ]
        runs_out.append({
            "run_id": str(root.id), "name": root.name, "start_time": str(root.start_time),
            "error": root.error, "total_tokens": getattr(root, "total_tokens", None),
            "tool_calls": tool_calls,
        })
    return {"project": project, "runs": runs_out}
