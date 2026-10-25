"""The sole declarative registry shared by every platform domain and Alembic."""
from typing import Any
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON().with_variant(JSONB(), "postgresql")}
