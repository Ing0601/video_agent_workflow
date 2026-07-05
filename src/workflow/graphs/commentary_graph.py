from langgraph.graph import END, START, StateGraph

from src.workflow.nodes.commentary_nodes import (
    align_video_info_node,
    analyze_material_node,
    check_tts_duration_node,
    create_commentary_draft_node,
    finish_commentary_node,
    generate_bgm_node,
    generate_overlay_node,
    generate_script_node,
    generate_sound_node,
    init_commentary_task,
    synthesize_tts_node,
)
from src.workflow.states import CommentaryState


def build_commentary_graph():
    graph = StateGraph(CommentaryState)

    graph.add_node("init_task", init_commentary_task)
    graph.add_node("analyze_material", analyze_material_node)
    graph.add_node("generate_script", generate_script_node)
    graph.add_node("synthesize_tts", synthesize_tts_node)
    graph.add_node("check_tts_duration", check_tts_duration_node)
    graph.add_node("align_video_info", align_video_info_node)
    graph.add_node("generate_bgm", generate_bgm_node)
    graph.add_node("generate_overlay", generate_overlay_node)
    graph.add_node("generate_sound", generate_sound_node)
    graph.add_node("create_jianying_draft", create_commentary_draft_node)
    graph.add_node("finish", finish_commentary_node)

    graph.add_edge(START, "init_task")
    graph.add_edge("init_task", "analyze_material")
    graph.add_edge("analyze_material", "generate_script")
    graph.add_edge("generate_script", "synthesize_tts")
    graph.add_edge("synthesize_tts", "check_tts_duration")
    graph.add_edge("check_tts_duration", "align_video_info")
    graph.add_edge("align_video_info", "generate_bgm")
    graph.add_edge("generate_bgm", "generate_overlay")
    graph.add_edge("generate_overlay", "generate_sound")
    graph.add_edge("generate_sound", "create_jianying_draft")
    graph.add_edge("create_jianying_draft", "finish")
    graph.add_edge("finish", END)

    return graph.compile()

