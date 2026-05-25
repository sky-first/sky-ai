"""Table name resolver - handles logical vs physical table names."""

from typing import Dict, Optional
from sqlalchemy.orm import Session
from db.models import TableMetadata


def resolve_logical_to_physical(
    db: Session, logical_name: str, connection_id: Optional[str] = None
) -> Optional[str]:
    """
    Resolve logical table name to physical table name.

    Args:
        db: Database session
        logical_name: Logical (user-friendly) table name
        connection_id: Optional connection ID to filter

    Returns:
        Physical table name or None if not found
    """
    query = db.query(TableMetadata).filter(TableMetadata.logical_name == logical_name)

    if connection_id:
        query = query.filter(TableMetadata.connection_id == connection_id)

    metadata = query.first()
    if metadata:
        return metadata.table_name

    return None


def resolve_physical_to_logical(
    db: Session, physical_name: str, connection_id: Optional[str] = None
) -> Optional[str]:
    """
    Resolve physical table name to logical table name.

    Args:
        db: Database session
        physical_name: Physical table name
        connection_id: Optional connection ID to filter

    Returns:
        Logical table name or None if not found
    """
    query = db.query(TableMetadata).filter(TableMetadata.table_name == physical_name)

    if connection_id:
        query = query.filter(TableMetadata.connection_id == connection_id)

    metadata = query.first()
    if metadata:
        return metadata.logical_name or metadata.table_name

    return None


def get_table_mapping(
    db: Session, connection_id: Optional[str] = None
) -> Dict[str, str]:
    """
    Get mapping of logical to physical table names.

    Args:
        db: Database session
        connection_id: Optional connection ID to filter

    Returns:
        Dictionary mapping logical names to physical names
    """
    query = db.query(TableMetadata)

    if connection_id:
        query = query.filter(TableMetadata.connection_id == connection_id)

    metadata_list = query.all()

    mapping = {}
    for metadata in metadata_list:
        logical = metadata.logical_name or metadata.table_name
        mapping[logical] = metadata.table_name

    return mapping
