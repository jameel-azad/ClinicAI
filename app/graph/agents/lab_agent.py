import os

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END

from app.schemas import BookingState

load_dotenv()


def lab_node(state: BookingState) -> dict:
    """
    For text-only lab_report_share intent (e.g. "I sent a lab report").
    Actual PDF parsing happens directly in webhook_router.py before graph invocation.
    This handles the case where intent fires but no PDF was attached.
    """
    bot_response = state.get("bot_response")
    return {
        "reply_message": (
            bot_response
            or (
                "📋 To share your lab report, please *forward the PDF* to this WhatsApp number directly.\n\n"
                "Once received, we'll send the AI summary to the doctor for review. 🙏"
            )
        ),
        "pipeline_log": ["lab_agent: prompted patient to send PDF"],
    }


def build_lab_graph():
    g = StateGraph(BookingState)
    g.add_node("lab_node", lab_node)
    g.add_edge(START, "lab_node")
    g.add_edge("lab_node", END)
    return g.compile()


lab_agent_graph = build_lab_graph()
