"""Read-only LangSmith trace evidence for the reviewer.

Reads the TRADING agent's run traces (tool calls + inputs/outputs/errors) as
evidence. Project name comes from LANGSMITH_PROJECT (currently 'monet_agent') —
never hardcoded. The reviewer only READS LangSmith; it never writes there.
"""
import os

from langsmith import Client


def read_run_trace(
    run_id: str | None = None,
    limit: int = 1,
) -> dict:
    """Fetch trading-agent run trace(s) from LangSmith.

    Args:
        run_id: a specific root run id; if omitted, fetches the most recent root run(s).
        limit: how many recent root runs to fetch when run_id is not given.

    Returns:
        {"project": str, "runs": [{run_id, name, start_time, error, tool_calls:[...]}]}
        where each tool_call = {name, inputs, outputs, error}.
    """
    project = os.environ.get("LANGSMITH_PROJECT", "monet_agent")
    client = Client()

    if run_id:
        roots = [client.read_run(run_id)]
    else:
        roots = list(client.list_runs(project_name=project, is_root=True, limit=limit))

    runs_out = []
    for root in roots:
        children = list(client.list_runs(project_name=project, trace_id=root.trace_id))
        tool_calls = [
            {"name": c.name, "inputs": c.inputs, "outputs": c.outputs, "error": c.error}
            for c in children
            if c.run_type == "tool"
        ]
        runs_out.append(
            {
                "run_id": str(root.id),
                "name": root.name,
                "start_time": str(root.start_time),
                "error": root.error,
                "tool_calls": tool_calls,
            }
        )
    return {"project": project, "runs": runs_out}
