"""Build the LangGraph agent workflow graph."""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from .nodes import (
    execute_tool_node,
    model_node,
    observe_tool_result,
    parse_tool_calls,
    permission_node,
    plan_node,
    prepare_context,
    request_plan_approval,
    route_after_model,
    route_after_observe,
    route_after_permission,
    route_after_verify,
    route_mode,
    summarize_node,
    verify_node,
)
from .state import AgentGraphState


def build_agent_graph(checkpointer=None):
    graph = StateGraph(AgentGraphState)

    graph.add_node("prepare_context", prepare_context)
    graph.add_node("plan", plan_node)
    graph.add_node("request_plan_approval", request_plan_approval)
    graph.add_node("model", model_node)
    graph.add_node("parse_tool_calls", parse_tool_calls)
    graph.add_node("permission", permission_node)
    graph.add_node("execute_tool", execute_tool_node)
    graph.add_node("verify", verify_node)
    graph.add_node("observe_tool_result", observe_tool_result)
    graph.add_node("summarize", summarize_node)

    graph.set_entry_point("prepare_context")

    graph.add_conditional_edges(
        "prepare_context",
        route_mode,
        {
            "model": "model",
        },
    )

    # Plan path: plan -> approval -> END
    graph.add_edge("plan", "request_plan_approval")
    graph.add_edge("request_plan_approval", END)

    # Act path: model -> (tools or finish)
    graph.add_conditional_edges(
        "model",
        route_after_model,
        {
            "tools": "parse_tool_calls",
            "finish": "summarize",
        },
    )

    graph.add_edge("parse_tool_calls", "permission")

    # Permission -> (execute or deny/summarize)
    graph.add_conditional_edges(
        "permission",
        route_after_permission,
        {
            "execute": "execute_tool",
            "deny": "summarize",
        },
    )

    graph.add_edge("execute_tool", "verify")

    # After verify: halt on unrecoverable failures, else continue
    graph.add_conditional_edges(
        "verify",
        route_after_verify,
        {
            "halt": "summarize",
            "continue": "observe_tool_result",
        },
    )

    # After observing results: loop back to model or finish
    graph.add_conditional_edges(
        "observe_tool_result",
        route_after_observe,
        {
            "continue": "model",
            "finish": "summarize",
        },
    )

    graph.add_edge("summarize", END)

    return graph.compile(checkpointer=checkpointer)
