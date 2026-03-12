"""Database layer for service mode (PostgreSQL + SQLAlchemy async).

These modules require SQLAlchemy/asyncpg (service mode dependencies).
Import them directly when needed:
    from attocode.code_intel.db.engine import init_engine, dispose_engine, get_session
    from attocode.code_intel.db.models import Organization, User, ...
"""
