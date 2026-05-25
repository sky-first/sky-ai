from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class ColumnFeatures:
    name: str
    dtype: str
    is_numeric: bool
    is_text: bool
    is_time: bool
    is_key_candidate: bool
    # Only if available, else None
    cardinality: Optional[int] = None


@dataclass
class TableFeatures:
    """
    Raw structural features extracted from table metadata.
    Independent of specific scoring logic.
    """

    name: str
    row_count: int
    col_count: int
    numeric_col_count: int
    text_col_count: int
    time_col_count: int
    # Heuristic: columns that look like keys (id, user_id, etc)
    key_like_col_count: int

    # Detailed extracted columns
    columns: List[ColumnFeatures] = field(default_factory=list)

    @property
    def numeric_ratio(self) -> float:
        return self.numeric_col_count / max(1, self.col_count)

    @property
    def text_ratio(self) -> float:
        return self.text_col_count / max(1, self.col_count)

    @property
    def key_ratio(self) -> float:
        # Avoid identifying small tables purely as key-heavy if they just have 1 ID and 1 col
        return self.key_like_col_count / max(1, self.col_count)


class SchemaScorer:
    """
    Probabilistic scoring model to determine table roles (Fact vs Dimension).
    Uses weighted structural signals instead of hard rules.
    """

    # --- Scoring Weights (Configurable) ---
    # FACT Score Weights
    W_FACT_VOLUME = 0.4
    W_FACT_NUMERIC = 0.3
    W_FACT_TIME = 0.2
    W_FACT_KEYS = 0.1

    # DIMENSION Score Weights
    W_DIM_LOW_VOLUME = 0.4
    W_DIM_TEXT = 0.4
    W_DIM_KEYS = 0.2

    # Normalization Constants
    LOG_ROW_CEILING = math.log10(10_000_000)
    LOG_ROW_FLOOR = math.log10(100)

    @classmethod
    def _normalize_volume(cls, row_count: int) -> float:
        """Log-scale normalization of row count to 0.0-1.0 range."""
        if row_count <= 0:
            return 0.0
        try:
            log_val = math.log10(max(1, row_count))
        except ValueError:
            return 0.0
        if log_val <= cls.LOG_ROW_FLOOR:
            return 0.0
        if log_val >= cls.LOG_ROW_CEILING:
            return 1.0
        return (log_val - cls.LOG_ROW_FLOOR) / (cls.LOG_ROW_CEILING - cls.LOG_ROW_FLOOR)

    @classmethod
    def extract_features(
        cls, table_name: str, columns: List[Dict[str, Any]], row_count: int
    ) -> TableFeatures:
        """Extracts agnostic features from metadata."""
        col_count = len(columns)
        numeric = 0
        text_cols = 0
        time_cols = 0
        keys = 0

        for col in columns:
            ctype = str(col.get("type", "")).upper()
            cname = str(col.get("name", "")).lower()

            # Numeric (Measures)
            if any(
                t in ctype
                for t in ["INT", "FLOAT", "NUMERIC", "DECIMAL", "DOUBLE", "REAL"]
            ):
                if not (cname.endswith("id") or cname == "id"):
                    numeric += 1

            # Text (Descriptors)
            if any(t in ctype for t in ["CHAR", "TEXT", "STRING"]):
                text_cols += 1

            # Time (Events)
            if any(t in ctype for t in ["DATE", "TIME", "TIMESTAMP"]):
                time_cols += 1

            # Keys (Connectivity)
            if cname == "id" or cname.endswith("_id") or cname.endswith("id"):
                keys += 1

        # Extract strict column features
        col_features_list = []
        for col in columns:
            cname = str(col.get("name", "")).lower()
            ctype = str(col.get("type", "")).upper()

            is_num = any(
                t in ctype
                for t in ["INT", "FLOAT", "NUMERIC", "DECIMAL", "DOUBLE", "REAL"]
            )
            is_txt = any(t in ctype for t in ["CHAR", "TEXT", "STRING"])
            is_time = any(t in ctype for t in ["DATE", "TIME", "TIMESTAMP"])
            is_key = cname == "id" or cname.endswith("_id") or cname.endswith("id")

            # Try to get cardinality if available in stats
            card = col.get("stats", {}).get("distinct_count")

            col_features_list.append(
                ColumnFeatures(
                    name=cname,
                    dtype=ctype,
                    is_numeric=is_num,
                    is_text=is_txt,
                    is_time=is_time,
                    is_key_candidate=is_key,
                    cardinality=card,
                )
            )

        return TableFeatures(
            name=table_name,
            row_count=row_count,
            col_count=col_count,
            numeric_col_count=numeric,
            text_col_count=text_cols,
            time_col_count=time_cols,
            key_like_col_count=keys,
            columns=col_features_list,
        )

    @classmethod
    def score_table(cls, features: TableFeatures) -> Dict[str, Any]:
        """
        Calculates Fact and Dimension scores based on features.
        Returns detailed scoring breakdown and explainability components.
        """
        # 1. Volume Score
        vol_score = cls._normalize_volume(features.row_count)

        # 2. Fact Score Calculation
        s_fact_vol = vol_score * cls.W_FACT_VOLUME
        s_fact_num = features.numeric_ratio * cls.W_FACT_NUMERIC
        s_fact_time = min(1.0, features.time_col_count) * cls.W_FACT_TIME
        s_fact_keys = features.key_ratio * cls.W_FACT_KEYS

        fact_score = s_fact_vol + s_fact_num + s_fact_time + s_fact_keys

        # 3. Dimension Score Calculation
        s_dim_vol = (1.0 - vol_score) * cls.W_DIM_LOW_VOLUME
        s_dim_text = features.text_ratio * cls.W_DIM_TEXT
        s_dim_keys = features.key_ratio * cls.W_DIM_KEYS

        dim_score = s_dim_vol + s_dim_text + s_dim_keys

        # 4. Role Decision with Ambiguity
        primary_role = "unknown"

        diff = abs(fact_score - dim_score)
        AMBIGUITY_THRESHOLD = 0.15

        if diff < AMBIGUITY_THRESHOLD:
            primary_role = "ambiguous"
            # In ambiguous cases, confidence is low regarding a specific role
            confidence = max(fact_score, dim_score)
        elif fact_score > dim_score:
            primary_role = "fact"
            confidence = fact_score
        else:
            primary_role = "dimension"
            confidence = dim_score

        return {
            "role": primary_role,
            "confidence": round(confidence, 2),
            "scores": {"fact": round(fact_score, 2), "dimension": round(dim_score, 2)},
            "signals": {
                "volume_norm": round(vol_score, 2),
                "numeric_ratio": round(features.numeric_ratio, 2),
                "text_ratio": round(features.text_ratio, 2),
            },
            "explanation": {
                "fact_components": {
                    "volume_signal": round(s_fact_vol, 2),
                    "numeric_signal": round(s_fact_num, 2),
                    "time_signal": round(s_fact_time, 2),
                    "keys_signal": round(s_fact_keys, 2),
                },
                "dim_components": {
                    "low_volume_signal": round(s_dim_vol, 2),
                    "text_signal": round(s_dim_text, 2),
                    "keys_signal": round(s_dim_keys, 2),
                },
            },
        }


class ColumnScorer:
    """
    Determines the semantic role of a column (Metric, Attribute, Key, Time).
    """

    @staticmethod
    def classify_column(col: ColumnFeatures, table_row_count: int) -> str:
        """
        Returns: 'metric', 'attribute', 'key', 'time', 'unknown'
        Strictly agnostic logic based on Dtype and Cardinality.
        """
        if col.is_time:
            return "time"

        # KEY Logic
        # If it looks like a key (name ends in id) OR high cardinality text/int
        if col.is_key_candidate:
            return "key"

        if col.is_text:
            if col.cardinality is not None and table_row_count > 100:
                # If unique values > 90% of rows -> Likely Key/ID (e.g. UUID, Email, SSO)
                if col.cardinality > (table_row_count * 0.9):
                    return "key"
            # Default text is attribute
            return "attribute"

        if col.is_numeric:
            # Check cardinality if available
            if col.cardinality is not None:
                # Low cardinality numeric -> Attribute (e.g. status_id=1..5, year=2023..2025)
                # Hard threshold < 50 distinct values usually means dimension/code
                if col.cardinality < 50:
                    return "attribute"

            # If no cardinality, we must assume metric for float/decimal
            # For integers, it's ambiguous without cardinality, but default to metric
            # unless it's a small integer type (which we don't detect yet).

            return "metric"

        return "unknown"


class AnalyticTableFilter:
    """
    Filters out tables that are likely system noise, logs, or technically irrelevant.
    """

    SYSTEM_PREFIXES = {
        "django_",
        "auth_",
        "knex_",
        "alembic_",
        "audit_",
        "celery_",
        "pg_",
        "sql_",
        "ar_internal_",
    }

    SYSTEM_SUFFIXES = {
        "_migration",
        "_migrations",
        "_audit",
        "_log",
        "_backup",
        "_tmp",
        "_temp",
    }

    @classmethod
    def should_exclude(
        cls, table_name: str, row_count: int = 1, allow_logs: bool = False
    ) -> bool:
        name = table_name.lower()

        # 1. Name Blacklist
        # If allow_logs is True, we don't block based on 'log' or 'audit'
        if any(name.startswith(p) for p in cls.SYSTEM_PREFIXES):
            # Exception: if allow_logs, maybe we allow 'audit_'? But prefixes like 'django_' are usually system.
            # Let's keep system prefixes blocked for now.
            return True

        if any(name.endswith(s) for s in cls.SYSTEM_SUFFIXES):
            # If we matched a suffix, we check if it's one of the log/audit suffixes
            # and if we allow logs. If so, we DON'T exclude it.
            if allow_logs and any(
                name.endswith(s)
                for s in cls.SYSTEM_SUFFIXES
                if "log" in s or "audit" in s
            ):
                return False
            return True

        # 2. Empty Tables
        # We NO LONGER exclude based on row_count == 0 here, because metadata might be stale
        # (especially in BigQuery) and we don't want to hide valid business tables.
        # Filtering empty tables should be handled at the reranking/selection layer if needed.

        return False


class JoinScorer:
    """
    Evaluates the strength of a potential join between two tables.
    """

    @staticmethod
    def score_join(t1_name: str, c1_name: str, t2_name: str, c2_name: str) -> float:
        """
        Returns 0.0 to 1.0 representing likelihood of a valid join.
        """
        c1 = c1_name.lower()
        c2 = c2_name.lower()
        t1 = t1_name.lower()
        t2 = t2_name.lower()

        # 1. Exact Match on ID (generic) - risky but common
        # e.g. customer_id == customer_id
        if c1 == c2 and c1.endswith("_id"):
            return 0.9

        # 2. Foreign Key Pattern: table_id == id
        # e.g. orders.user_id JOIN users.id
        if c1 == "id" and c2 == f"{t1}_id":
            return 1.0
        if c2 == "id" and c1 == f"{t2}_id":
            return 1.0

        # 3. Fuzzy Foreign Key Pattern: table_id == id (singularized)
        # e.g. orders.user_id JOIN users.id
        # Simple plural removal
        t1_single = t1[:-1] if t1.endswith("s") else t1
        t2_single = t2[:-1] if t2.endswith("s") else t2

        if c1 == "id" and c2 == f"{t1_single}_id":
            return 0.95
        if c2 == "id" and c1 == f"{t2_single}_id":
            return 0.95

        return 0.0
