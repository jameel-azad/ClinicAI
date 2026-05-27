"""
Backward-compatibility shim.
All booking logic now lives in app/graph/agents/booking_agent.py.
The top-level orchestrator is app/graph/router.py (router_graph).
"""

from app.graph.router import router_graph as booking_graph  # noqa: F401

__all__ = ["booking_graph"]
