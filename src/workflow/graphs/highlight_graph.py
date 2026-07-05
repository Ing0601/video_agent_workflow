from langgraph.graph import END, START, StateGraph

from src.workflow.nodes.highlight_nodes import (
    asr_transcribe_node,
    collect_videos_node,
    content_clip_node,
    finish_highlight_node,
    init_highlight_task,
    maybe_generate_highlight_draft_node,
    save_highlight_result_node,
    select_highlights_node,
    split_and_group_node,
    vlm_analyze_node,
)
from src.workflow.states import HighlightState


def build_highlight_graph():
    graph = StateGraph(HighlightState)

    graph.add_node("init_task", init_highlight_task)
    graph.add_node("collect_videos", collect_videos_node)
    graph.add_node("asr_transcribe", asr_transcribe_node)
    graph.add_node("content_clip", content_clip_node)
    graph.add_node("split_and_group", split_and_group_node)
    graph.add_node("vlm_analyze", vlm_analyze_node)
    graph.add_node("select_highlights", select_highlights_node)
    graph.add_node("save_highlight_result", save_highlight_result_node)
    graph.add_node("maybe_generate_draft", maybe_generate_highlight_draft_node)
    graph.add_node("finish", finish_highlight_node)

    graph.add_edge(START, "init_task")
    graph.add_edge("init_task", "collect_videos")
    graph.add_edge("collect_videos", "asr_transcribe")
    graph.add_edge("asr_transcribe", "content_clip")
    graph.add_edge("content_clip", "split_and_group")
    graph.add_edge("split_and_group", "vlm_analyze")
    graph.add_edge("vlm_analyze", "select_highlights")
    graph.add_edge("select_highlights", "save_highlight_result")
    graph.add_edge("save_highlight_result", "maybe_generate_draft")
    graph.add_edge("maybe_generate_draft", "finish")
    graph.add_edge("finish", END)

    return graph.compile()

