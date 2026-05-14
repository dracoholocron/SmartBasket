"""
SQLAlchemy DeclarativeBase compartido por todos los modelos.

Pattern:
    from sports_data_api.db.base import Base

    class Game(Base):
        __tablename__ = "games"
        ...

En S0.3 agregaremos los modelos ORM concretos y los registraremos importándolos
desde `sports_data_api.db.models` para que Alembic los recoja en autogenerate.
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base común para todos los modelos ORM."""

    pass
