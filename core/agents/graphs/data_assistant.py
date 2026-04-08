"""Data assistant graph - main agent graph."""
from typing import Dict, Any
from core.agents.generic_sql_agent import AgentState, build_graph
from core.agents.factory import AgentConfig


def load_scope(state: AgentState, agent_config: AgentConfig) -> AgentState:
    """
    Load scope (tables, connections) for the agent.
    
    This is the first node in the graph.
    """
    # Scope is already loaded in agent_config
    state.metadata["scope_loaded"] = True
    return state


def retrieval_node(state: AgentState, agent_config: AgentConfig, db) -> AgentState:
    """
    Retrieval node - uses RAG to find relevant context.
    
    This is handled in orchestrate_data_sources, so this is a placeholder.
    """
    return state


def sql_planner_node(state: AgentState, agent_config: AgentConfig, db) -> AgentState:
    """
    SQL planner node - generates SQL query.
    
    This is handled in plan_and_execute_sql, so this is a placeholder.
    """
    return state


def answer_node(state: AgentState, agent_config: AgentConfig) -> AgentState:
    """
    Answer node - formats final answer.
    
    This is handled in format_answer, so this is a placeholder.
    """
    return state


# Main graph execution is in generic_sql_agent.build_graph

