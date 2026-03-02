"""
Context Bundle Data Models

Dataclasses representing different layers of context for LLM inference.
Designed for CPU-optimized models with strict token budgets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from core.agents.generic_sql_agent import TableSchema
from core.sql.relationships import TableRelationship


@dataclass
class UserContext:
    """
    User identity and preferences.
    
    Used for role-based reasoning and personalization.
    """
    user_id: str
    platform_role: str = "user"  # admin/user/viewer
    crew_role: str = "guest"     # commander/navigator/explorer/guest
    role_label: Optional[str] = None # Display label like "CFO", "Lead Scientist"
    locale: str = "en"
    permissions: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for logging/debugging"""
        return {
            "user_id": self.user_id,
            "platform_role": self.platform_role,
            "crew_role": self.crew_role,
            "role_label": self.role_label,
            "locale": self.locale,
            "permissions": self.permissions,
        }


@dataclass
class CrewContext:
    """
    Crew-based access control context.
    
    Defines which datasets and domains the user can access.
    """
    crew_ids: List[str] = field(default_factory=list)
    allowed_datasets: List[str] = field(default_factory=list)  # Pre-filtered by backend
    restricted_domains: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for logging/debugging"""
        return {
            "crew_ids": self.crew_ids,
            "allowed_datasets": self.allowed_datasets,
            "restricted_domains": self.restricted_domains,
        }


@dataclass
class QueryContext:
    """
    Detected intent and query characteristics.
    
    Helps LLM understand what kind of analysis is needed.
    """
    intent: str = "analytical"  # analytical/exploratory/comparative/operational
    entities: List[str] = field(default_factory=list)  # Detected entities (customers, products, etc)
    metrics: List[str] = field(default_factory=list)   # Detected metrics (revenue, count, etc)
    time_range: Optional[str] = None                    # Detected time range (monthly, yearly, etc)
    requires_aggregation: bool = False
    requires_joins: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for logging/debugging"""
        return {
            "intent": self.intent,
            "entities": self.entities,
            "metrics": self.metrics,
            "time_range": self.time_range,
            "requires_aggregation": self.requires_aggregation,
            "requires_joins": self.requires_joins,
        }


@dataclass
class DataContext:
    """
    Schema and metadata about available data.
    
    Provides LLM with information about tables, columns, and relationships.
    """
    tables: List[TableSchema] = field(default_factory=list)
    relationships: List[Relationship] = field(default_factory=list)
    total_tables: int = 0
    context_freshness: str = "live"  # live/cached-5m/cached-30m
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for logging/debugging"""
        return {
            "total_tables": self.total_tables,
            "table_names": [t.logical_name for t in self.tables],
            "num_relationships": len(self.relationships),
            "context_freshness": self.context_freshness,
        }


@dataclass
class HistoricalContext:
    """
    Multi-layer RAG system for semantic retrieval.
    
    Each layer provides different types of context:
    - Schema RAG: Table/column semantics and descriptions
    - Metrics RAG: Business KPI definitions and calculations
    - Questions RAG: Past validated queries and SQL
    - Comments RAG: User clarifications and corrections
    - Glossary RAG: Domain terminology and acronyms
    """
    # Layer 1: Schema metadata
    schema_rag: List[str] = field(default_factory=list)
    
    # Layer 2: Business metrics
    metrics_rag: List[str] = field(default_factory=list)
    
    # Layer 3: Past questions
    questions_rag: List[str] = field(default_factory=list)
    
    # Layer 4: User comments
    comments_rag: List[str] = field(default_factory=list)
    
    # Layer 5: Business glossary
    glossary_rag: List[str] = field(default_factory=list)
    
    # NOVAS CAMADAS (Carregadas dinamicamente via RAG com alto threshold)
    catalog_rag: List[str] = field(default_factory=list)      # Data Catalog, Conexões, Infraestrutura
    analytics_rag: List[str] = field(default_factory=list)    # Lineage, Qualidade, Compliance de dados
    strategy_rag: List[str] = field(default_factory=list)     # Objetivos, OKRs, Metas corporativas
    governance_rag: List[str] = field(default_factory=list)   # Governança, Permissões, Auditoria
    enterprise_rag: List[str] = field(default_factory=list)   # Grafos da empresa, Relações sistêmicas
    signals_rag: List[str] = field(default_factory=list)      # Sazonalidade, Eventos, Ciclos macroeconômicos
    
    # Traditional context
    chat_history: List[Dict[str, str]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for logging/debugging"""
        return {
            "schema_rag_count": len(self.schema_rag),
            "metrics_rag_count": len(self.metrics_rag),
            "questions_rag_count": len(self.questions_rag),
            "comments_rag_count": len(self.comments_rag),
            "glossary_rag_count": len(self.glossary_rag),
            "catalog_rag_count": len(self.catalog_rag),
            "analytics_rag_count": len(self.analytics_rag),
            "strategy_rag_count": len(self.strategy_rag),
            "governance_rag_count": len(self.governance_rag),
            "enterprise_rag_count": len(self.enterprise_rag),
            "signals_rag_count": len(self.signals_rag),
            "chat_history_count": len(self.chat_history),
        }
    
    def total_chunks(self) -> int:
        """Total number of RAG chunks across all layers"""
        return (
            len(self.schema_rag) +
            len(self.metrics_rag) +
            len(self.questions_rag) +
            len(self.comments_rag) +
            len(self.glossary_rag) +
            len(self.catalog_rag) +
            len(self.analytics_rag) +
            len(self.strategy_rag) +
            len(self.governance_rag) +
            len(self.enterprise_rag) +
            len(self.signals_rag)
        )


@dataclass
class ContextBundle:
    """
    Aggregates all context layers into a single bundle.
    
    Built once per request and reused by all agents (orchestrator, specialist, formatter).
    Includes token estimation and truncation metadata.
    """
    user: UserContext
    crew: CrewContext
    query: QueryContext
    data: DataContext
    historical: HistoricalContext
    
    # CPU-specific optimizations
    total_tokens_estimate: int = 0
    is_truncated: bool = False
    truncation_details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize to dict for logging/debugging.
        
        Useful for telemetry and debugging context issues.
        """
        return {
            "user": self.user.to_dict(),
            "crew": self.crew.to_dict(),
            "query": self.query.to_dict(),
            "data": self.data.to_dict(),
            "historical": self.historical.to_dict(),
            "total_tokens_estimate": self.total_tokens_estimate,
            "is_truncated": self.is_truncated,
            "truncation_details": self.truncation_details,
        }
    
    def summary(self) -> str:
        """
        One-line summary for logging.
        
        Example: "ContextBundle(user=admin, tables=5, rag_chunks=13, tokens=2847, truncated=False)"
        """
        return (
            f"ContextBundle("
            f"user={self.user.platform_role}, "
            f"tables={self.data.total_tables}, "
            f"rag_chunks={self.historical.total_chunks()}, "
            f"tokens={self.total_tokens_estimate}, "
            f"truncated={self.is_truncated})"
        )
