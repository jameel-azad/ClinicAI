from langgraph.graph import END, StateGraph

from app.graph.scribe.nodes import (
    followup_generator_node,
    grounding_check_node,
    pdf_output_node,
    soap_generator_node,
    transcribe_node,
)
from app.graph.scribe.state import ScribeState


def build_scribe_pipeline():
    graph = StateGraph(ScribeState)

    graph.add_node("transcribe", transcribe_node)
    graph.add_node("soap_generator", soap_generator_node)
    graph.add_node("grounding_check", grounding_check_node)
    graph.add_node("followup_generator", followup_generator_node)
    graph.add_node("pdf_output", pdf_output_node)

    graph.set_entry_point("transcribe")
    graph.add_edge("transcribe", "soap_generator")
    graph.add_edge("soap_generator", "grounding_check")
    graph.add_edge("grounding_check", "followup_generator")
    graph.add_edge("followup_generator", "pdf_output")
    graph.add_edge("pdf_output", END)

    return graph.compile()


scribe_pipeline = build_scribe_pipeline()
