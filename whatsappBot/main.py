from contextlib import asynccontextmanager
from importlib import import_module
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def _optional_attr(module_name: str, attr_name: str) -> Any | None:
    """Import an optional module attribute without breaking the current app."""
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            return None
        raise
    return getattr(module, attr_name, None)


classifier_router = _optional_attr("app.api.classifier_router", "router")
if classifier_router is None:
    classifier_router = _optional_attr("app.api", "router")

classifier_graph = _optional_attr("app.graph.classifier", "classifier_graph")
if classifier_graph is None:
    classifier_graph = _optional_attr("app.graph", "classifier_graph")

webhook_router = _optional_attr("app.api.webhook_router", "router")
booking_graph = _optional_attr("app.graph.booking", "booking_graph")
scheduler = _optional_attr("app.services.scheduler", "scheduler")


def _graph_nodes(graph: Any | None) -> list[str]:
    if graph is None:
        return []
    return list(getattr(graph, "nodes", {}).keys())


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 60)
    print("  ClinicAI - Complete System")
    print("=" * 60)

    if scheduler is not None:
        if not getattr(scheduler, "running", False):
            scheduler.start()
        print("  APScheduler ready - reminder jobs available")
    else:
        print("  APScheduler not configured -  scheduler module not found")

    print(f"  Classifier graph nodes: {_graph_nodes(classifier_graph)}")
    if booking_graph is not None:
        print(f"  Booking graph nodes   : {_graph_nodes(booking_graph)}")
    else:
        print("  Booking graph nodes   : not configured")
    print("=" * 60)

    yield

    if scheduler is not None and getattr(scheduler, "running", False):
        scheduler.shutdown(wait=False)
    print("ClinicAI shutting down.")


app = FastAPI(
    title="ClinicAI - WhatsApp Clinic Assistant",
    description=(
        "Intent classifier and appointment booking bot.\n"
    ),
    version="2.0.0",
    lifespan=lifespan,  
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if classifier_router is None:
    raise RuntimeError("Classifier router could not be loaded from app.api")

app.include_router(classifier_router)

if webhook_router is not None:
    app.include_router(webhook_router)


@app.get("/", tags=["Health"])
def health():
    endpoints = {
        "classifier": "POST /classify",
        "docs": "GET /docs",
        "graph_nodes": "GET /graph/nodes",
    }
    if webhook_router is not None:
        endpoints.update(
            {
                "whatsapp_webhook": "POST /webhook/twilio",
                "debug_sessions": "GET /debug/sessions",
                "debug_appointments": "GET /debug/appointments",
            }
        )

    return {
        "status": "ok",
        "service": "ClinicAI WhatsApp Clinic Assistant",
        "version": "2.0.0 (LangGraph)",
        "features": {
            "classifier": classifier_graph is not None,
            "whatsapp_webhook": webhook_router is not None,
            "booking_graph": booking_graph is not None,
            "scheduler": scheduler is not None,
        },
        "endpoints": endpoints,
    }


@app.get("/graph/nodes", tags=["Debug"])
def graph_nodes():
    classifier_nodes = _graph_nodes(classifier_graph)
    booking_nodes = _graph_nodes(booking_graph)
    return {
        # Backward-compatible key used by the existing tests/UI.
        "nodes": classifier_nodes,
        "classifier_graph": classifier_nodes,
        "booking_graph": booking_nodes,
        "description": "Pipeline stages currently registered in each graph",
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
