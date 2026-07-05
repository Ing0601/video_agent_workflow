from typing import Any, AsyncGenerator, Dict

from src.workflow.graphs import build_commentary_graph, build_highlight_graph
from src.workflow.runtime import workflow_event


async def stream_graph(graph, initial_state: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
    task_id = initial_state.get("task_id", "unknown")
    yield workflow_event("start", task_id=task_id, message="workflow started")

    final_state: Dict[str, Any] = {}
    async for update in graph.astream(initial_state, stream_mode="updates"):
        for node, payload in update.items():
            if not isinstance(payload, dict):
                payload = {"payload": payload}
            final_state.update(payload)
            task_id = final_state.get("task_id", task_id)
            yield workflow_event(
                "node_end",
                task_id=task_id,
                node=node,
                message=payload.get("logs", [""])[-1] if payload.get("logs") else None,
                progress=payload.get("progress"),
                current_node=payload.get("current_node", node),
                result=payload.get("final_result"),
            )

    yield workflow_event(
        "final",
        task_id=task_id,
        message="workflow finished",
        result=final_state.get("final_result", final_state),
    )


async def run_highlight_graph_stream(initial_state: Dict[str, Any]):
    graph = build_highlight_graph()
    async for event in stream_graph(graph, initial_state):
        yield event


async def run_commentary_graph_stream(initial_state: Dict[str, Any]):
    graph = build_commentary_graph()
    async for event in stream_graph(graph, initial_state):
        yield event

