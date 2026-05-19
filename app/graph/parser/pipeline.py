"""
app/pipeline.py — Builds and returns the compiled LangGraph for lab report processing.

The graph is stateful and compiled once at startup (module level).
Each API call runs a fresh invocation through the compiled graph.

Graph structure (linear pipeline):

  extract_text → extract_all → flag_abnormals → generate_summary → END
"""

from langgraph.graph import StateGraph, START, END

from app.graph.parser.state import ReportState
from app.graph.parser.nodes import (
    extract_text_node,
    extract_all_node,
    flag_abnormals_node,
    generate_summary_node,
)


def build_pipeline():
    """
    Construct and compile the LangGraph pipeline.

    Returns a compiled graph that can be invoked with an initial ReportState.
    """
    # Initialise the graph with our state schema
    graph = StateGraph(ReportState)

    # --- Register nodes ---
    graph.add_node("extract_text", extract_text_node)
    graph.add_node("extract_all", extract_all_node)
    graph.add_node("flag_abnormals", flag_abnormals_node)
    graph.add_node("generate_summary", generate_summary_node)

    # --- Define edges (linear flow) ---
    graph.set_entry_point("extract_text")
    graph.add_edge("extract_text", "extract_all")
    graph.add_edge("extract_all", "flag_abnormals")
    graph.add_edge("flag_abnormals", "generate_summary")
    graph.add_edge("generate_summary", END)

    return graph.compile()


# Compile once at import time — reused across all API requests
lab_report_pipeline = build_pipeline()
