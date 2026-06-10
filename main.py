import os
from contextlib import asynccontextmanager
from importlib import import_module
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth_router import router as auth_router
from app.api.clinic_router import router as clinic_router
from app.api.doctor_api_router import router as doctor_api_router
from app.api.config_router import router as config_router
from app.api.patient_router import router as patient_router


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
parser_router = _optional_attr("app.api.parser_router", "router")
scribe_router = _optional_attr("app.api.scribe_router", "router")
booking_graph = _optional_attr("app.graph.booking", "booking_graph")
scheduler = _optional_attr("app.services.scheduler", "scheduler")


def _graph_nodes(graph: Any | None) -> list[str]:
    if graph is None:
        return []
    return list(getattr(graph, "nodes", {}).keys())


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio as _asyncio
    # Register the main event loop so APScheduler jobs and synchronous LangGraph
    # nodes can run async coroutines on it (shares the DB connection pool).
    from app.services.async_runner import set_main_loop
    set_main_loop(_asyncio.get_running_loop())

    # Create DB tables at startup
    try:
        from app.database import engine, Base
        import app.models  # noqa — registers all models with Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as _exc:
        print(f"  [WARN] DB table creation failed: {_exc}")

    print("=" * 60)
    print("  ClinicAI - Sprint 2 Multi-Agent System")
    print("=" * 60)

    # ── Sync DB doctors into identity cache + Redis store ──────────────────
    try:
        from app.database import AsyncSessionLocal
        from app.models.doctor import Doctor as _Doctor
        from sqlalchemy import select as _select
        from app.services.identity import refresh_db_doctors_cache
        from app.services.doctor_directory import sync_doctors_to_store

        async with AsyncSessionLocal() as _db:
            _result = await _db.execute(_select(_Doctor).where(_Doctor.is_active.is_(True)))
            _db_doctors = _result.scalars().all()

        refresh_db_doctors_cache(_db_doctors)
        from app.services.doctor_directory import reset_store_to_db_doctors
        reset_store_to_db_doctors(_db_doctors)
        print(f"  Loaded {len(_db_doctors)} doctor(s) from DB — stale/demo profiles cleared")
    except Exception as _exc:
        print(f"  [WARN] DB doctor sync failed: {_exc}")

    # ── Verify WhatsApp Content Template approval status ──────────────────
    try:
        from app.services.whatsapp import check_content_template_approval
        _template_checks = {
            "APPOINTMENT_APPROVAL": os.getenv("APPOINTMENT_APPROVAL_CONTENT_SID", "").strip(),
            "SOAP_APPROVAL": os.getenv("SOAP_APPROVAL_CONTENT_SID", "").strip(),
        }
        for _name, _csid in _template_checks.items():
            if not _csid:
                continue
            _status = await check_content_template_approval(_csid)
            if _status == "approved":
                print(f"  Template {_name} ({_csid[:12]}...): APPROVED ✓")
            elif _status == "unknown":
                print(f"  Template {_name} ({_csid[:12]}...): status unknown (check Twilio console)")
            else:
                print(
                    f"  [WARN] Template {_name} ({_csid[:12]}...): status={_status.upper()} — "
                    "messages to doctors will be UNDELIVERED until approved by WhatsApp/Meta. "
                    "Go to Twilio Console → Content Template Builder → Submit for approval."
                )
    except Exception as _exc:
        print(f"  [WARN] Template approval check failed: {_exc}")

    if scheduler is not None:
        if not getattr(scheduler, "running", False):
            scheduler.start()
        print("  APScheduler ready — reminder + consultation timeout + after-hours flush + weekly insights jobs available")

        # Register after-hours flush and weekly insights for ALL doctors (env + DB)
        try:
            from app.services.identity import all_doctor_numbers
            from app.services.scheduler import schedule_afterhours_flush, schedule_weekly_insights
            for doc_num in all_doctor_numbers():
                schedule_afterhours_flush(doc_num)
                schedule_weekly_insights(doc_num)
        except Exception as _exc:
            print(f"  [WARN] Scheduler job registration failed: {_exc}")

    print(f"  Classifier graph nodes: {_graph_nodes(classifier_graph)}")
    if booking_graph is not None:
        print(f"  Router graph nodes    : {_graph_nodes(booking_graph)}")
    else:
        print("  Router graph          : not configured")
    print("  Agents: BookingAgent | ConsultationAgent | EmergencyAgent | AfterHoursAgent | LabAgent | FollowUpAgent")
    print("=" * 60)

    yield

    if scheduler is not None and getattr(scheduler, "running", False):
        scheduler.shutdown(wait=False)
    print("ClinicAI shutting down.")


app = FastAPI(
    title="ClinicAI - WhatsApp Clinic Assistant",
    description=(
        "Intent classifier, appointment booking, and lab report parser.\n"
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("DASHBOARD_URL", "http://localhost:3000"), "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if classifier_router is None:
    raise RuntimeError("Classifier router could not be loaded from app.api")

app.include_router(classifier_router)

if webhook_router is not None:
    app.include_router(webhook_router)

if parser_router is not None:
    app.include_router(parser_router)

if scribe_router is not None:
    app.include_router(scribe_router)

app.include_router(auth_router)
app.include_router(clinic_router)
app.include_router(doctor_api_router)
app.include_router(config_router)
app.include_router(patient_router)


@app.get("/health", tags=["Health"])
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
