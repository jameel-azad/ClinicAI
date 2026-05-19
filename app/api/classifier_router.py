"""
FellowAI — API Router
Exposes the /classify endpoint.
The endpoint invokes the LangGraph pipeline and maps the final state
back to the ClassifyResponse Pydantic model.
"""

from fastapi import APIRouter, HTTPException
import app.api as api_package

from app.schemas import ClassifyRequest, ClassifyResponse, Entities, IntentResult
from app.graph import classifier_graph

router = APIRouter()


@router.post("/classify", response_model=ClassifyResponse, tags=["Classifier"])
async def classify(request: ClassifyRequest):
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # ── Build initial state ────────────────────────────────────────────────────
    # Only set the fields the first node needs.
    # All other fields will be populated by the nodes as the graph runs.
    initial_state = {
        "from_number": request.from_number,
        "raw_message": request.message.strip(),


        "is_valid": False,
        "validation_error": None,
        "processed_message": "",
        "intent": "general_query",
        "confidence": 0.0,
        "entities": {},
        "bot_response": None,
        "llm_error": None,
        "all_intents": [],
        "is_multi_intent": False,
        "is_injection": False,
        "injection_reason": None,
        "is_emergency": False,
        "pipeline_log": [],
    }

    # ── Run the graph ──────────────────────────────────────────────────────────
    graph = getattr(api_package, "classifier_graph", classifier_graph)
    final_state = graph.invoke(initial_state)

    # ── Handle validation failure ──────────────────────────────────────────────
    if not final_state.get("is_valid", True):
        raise HTTPException(
            status_code=400,
            detail=final_state.get("validation_error", "Invalid message"),
        )

    # ── Map state → API response ───────────────────────────────────────────────
    entities_dict = final_state.get("entities") or {}
    all_intents = [
        IntentResult(
            intent=item["intent"],
            confidence=item["confidence"],
            entities=Entities(**(item.get("entities") or {})),
            bot_response=item.get("bot_response"),
        )
        for item in final_state.get("all_intents", [])
    ]

    return ClassifyResponse(
        intent=final_state["intent"],
        confidence=final_state["confidence"],
        entities=Entities(**entities_dict),
        bot_response=final_state.get("bot_response"),
        is_multi_intent=final_state.get("is_multi_intent", False),
        all_intents=all_intents,
        raw_message=request.message,
        flagged_as_injection=final_state.get("is_injection", False),
        pipeline_trace=final_state.get("pipeline_log", []),
    )
