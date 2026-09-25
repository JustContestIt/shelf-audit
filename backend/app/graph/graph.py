"""The LangGraph pipeline (ARCHITECTURE.md, «Целевая архитектура»).

validate_input -> input_guard -(не полка)-> reject
                               -> detect -> postprocess -> [uncertain groups?]
                                   -> retrieve_refs -> verify_subtypes -> [uncertain groups?] (≤ max_verify_iterations)
                                                    -(pass2_mode=check: ours/foreign check only)-> build_report
                                   -> build_report -> human_review (interrupt) -(переснять)-> validate_input
                                                                              -(утвердить/правка)-> persist
"""
from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph.deps import Deps
from app.graph.nodes.detect import make_detect, make_postprocess, route_after_detect
from app.graph.nodes.guard import make_input_guard, make_reject, make_validate_input, route_after_guard
from app.graph.nodes.report import (
    make_build_report,
    make_human_review,
    make_persist,
    route_after_report,
    route_after_review,
)
from app.graph.nodes.verify import (
    make_retrieve_refs,
    make_route_after_retrieve,
    make_route_uncertain,
    make_verify_subtypes,
)
from app.graph.state import AuditState

# Types stored in checkpoints; everything else is refused on load (LangGraph strict msgpack).
STATE_TYPES = [("app.graph.state", n) for n in ("AuditState", "Photo", "Store", "LLMCall", "ReportRow", "Report", "Review", "Progress")]


def serde():
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    return JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES)


NODES = ["validate_input", "input_guard", "reject", "detect", "postprocess", "retrieve_refs", "verify_subtypes",
         "build_report", "human_review", "persist"]


def build_graph(deps: Deps, checkpointer=None):
    g = StateGraph(AuditState)
    g.add_node("validate_input", make_validate_input(deps))
    g.add_node("input_guard", make_input_guard(deps))
    g.add_node("reject", make_reject(deps))
    g.add_node("detect", make_detect(deps))
    g.add_node("postprocess", make_postprocess(deps))
    g.add_node("retrieve_refs", make_retrieve_refs(deps))
    g.add_node("verify_subtypes", make_verify_subtypes(deps))
    g.add_node("build_report", make_build_report(deps))
    g.add_node("human_review", make_human_review(deps))
    g.add_node("persist", make_persist(deps))

    route_uncertain = make_route_uncertain(deps)
    g.add_edge(START, "validate_input")
    g.add_edge("validate_input", "input_guard")
    g.add_conditional_edges("input_guard", route_after_guard, {"reject": "reject", "detect": "detect"})
    g.add_edge("reject", END)
    g.add_conditional_edges("detect", route_after_detect, {"postprocess": "postprocess", "build_report": "build_report"})
    g.add_conditional_edges("postprocess", route_uncertain, {"retrieve_refs": "retrieve_refs", "build_report": "build_report"})
    g.add_conditional_edges("retrieve_refs", make_route_after_retrieve(deps),
                            {"verify_subtypes": "verify_subtypes", "build_report": "build_report"})
    g.add_conditional_edges("verify_subtypes", route_uncertain, {"retrieve_refs": "retrieve_refs", "build_report": "build_report"})
    g.add_conditional_edges("build_report", route_after_report, {"human_review": "human_review", "persist": "persist"})
    g.add_conditional_edges("human_review", route_after_review, {"validate_input": "validate_input", "persist": "persist"})
    g.add_edge("persist", END)
    return g.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver(serde=serde()))


def postgres_checkpointer(dsn: str):
    """PostgresSaver on a small pool; tables are created on first start (setup())."""
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(dsn, min_size=1, max_size=5, kwargs={"autocommit": True, "prepare_threshold": 0,
                                                                  "row_factory": dict_row}, open=True)
    saver = PostgresSaver(pool, serde=serde())
    saver.setup()
    return saver


def run_config(deps: Deps, report_id: str, extra_tags: list[str] | None = None) -> dict:
    """thread_id = report_id; tags/metadata go to LangSmith (prompt_version, model, config_id)."""
    s = deps.settings
    return {
        "configurable": {"thread_id": report_id},
        "run_name": f"shelf-audit:{report_id}",
        "tags": [f"prompt:{deps.detect_prompt.version}", f"verify:{deps.verify_prompt.version}",
                 f"model:{s.detect_models[0]}", f"config:{s.config_id}", f"pass2:{s.pass2_mode}/{s.pass2_refs}",
                 *(extra_tags or [])],
        "metadata": {"report_id": report_id, "prompt_version": deps.detect_prompt.version,
                     "verify_prompt_version": deps.verify_prompt.version, "model": s.detect_models[0],
                     "config_id": s.config_id, "llm_mode": s.llm_mode},
        "recursion_limit": 50,
    }
