"""SQLAlchemy ORM models for service mode."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from attocode.code_intel.db.base import Base, TimestampMixin, generate_uuid


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(Text, nullable=False, server_default="free")
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    memberships: Mapped[list[OrgMembership]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    repositories: Mapped[list[Repository]] = relationship(back_populates="organization", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    auth_provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="email")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    memberships: Mapped[list[OrgMembership]] = relationship(back_populates="user", cascade="all, delete-orphan")
    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="user", cascade="all, delete-orphan")


class OrgMembership(Base):
    __tablename__ = "org_memberships"

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="member")
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default="{}")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="api_keys")
    user: Mapped[User | None] = relationship(back_populates="api_keys")


class Repository(TimestampMixin, Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    clone_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_branch: Mapped[str] = mapped_column(Text, nullable=False, server_default="main")
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    index_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    clone_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    disk_usage_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="repositories")
    credentials: Mapped[list[RepoCredential]] = relationship(back_populates="repository", cascade="all, delete-orphan")
    branches: Mapped[list[Branch]] = relationship(back_populates="repository", cascade="all, delete-orphan")
    webhook_configs: Mapped[list[WebhookConfig]] = relationship(back_populates="repository", cascade="all, delete-orphan")
    indexing_jobs: Mapped[list[IndexingJob]] = relationship(back_populates="repository", cascade="all, delete-orphan")

    __table_args__ = (
        # Unique repo name within an org
        {"schema": None},
    )

    @classmethod
    def __declare_last__(cls) -> None:
        from sqlalchemy import UniqueConstraint
        if not any(isinstance(c, UniqueConstraint) for c in cls.__table__.constraints if hasattr(c, 'columns') and len(c.columns) == 2):
            pass  # UniqueConstraint added via migration


class RepoCredential(Base):
    __tablename__ = "repo_credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    cred_type: Mapped[str] = mapped_column(Text, nullable=False)  # ssh_key|deploy_token|pat
    encrypted_value: Mapped[bytes] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    repository: Mapped[Repository] = relationship(back_populates="credentials")


class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True)
    head_commit: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Monotonic version counter — incremented on every overlay write for consistency checks
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    repository: Mapped[Repository] = relationship(back_populates="branches")
    parent_branch: Mapped[Branch | None] = relationship(remote_side=[id])
    files: Mapped[list[BranchFile]] = relationship(back_populates="branch", cascade="all, delete-orphan")

    __table_args__ = (
        {"schema": None},
    )


class FileContent(Base):
    __tablename__ = "file_contents"

    sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    content: Mapped[bytes] = mapped_column(nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Supports storing summaries alongside code: source|summary_l1|summary_l2
    content_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="source")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BranchFile(Base):
    __tablename__ = "branch_files"

    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True)
    path: Mapped[str] = mapped_column(Text, primary_key=True)
    content_sha: Mapped[str | None] = mapped_column(Text, ForeignKey("file_contents.sha256"), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # added|modified|deleted

    branch: Mapped[Branch] = relationship(back_populates="files")


class Symbol(Base):
    __tablename__ = "symbols"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    content_sha: Mapped[str] = mapped_column(Text, ForeignKey("file_contents.sha256"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    line_start: Mapped[int | None] = mapped_column(nullable=True)
    line_end: Mapped[int | None] = mapped_column(nullable=True)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    exported: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")


class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    # N5 fix: CASCADE on FK so deleting file_contents cleans up embeddings
    content_sha: Mapped[str] = mapped_column(Text, ForeignKey("file_contents.sha256", ondelete="CASCADE"), nullable=False)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    chunk_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="file")
    # vector column added when pgvector extension is available
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # C6 fix: DB-level guarantee of one embedding per (content_sha, model, chunk_type)
    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint(
            "content_sha", "embedding_model", "chunk_type",
            name="uq_embedding_content_model_chunk",
        ),
    )


class Dependency(Base):
    __tablename__ = "dependencies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    source_sha: Mapped[str] = mapped_column(Text, ForeignKey("file_contents.sha256"), nullable=False)
    target_sha: Mapped[str] = mapped_column(Text, ForeignKey("file_contents.sha256"), nullable=False)
    # Types: import, call, type_ref, data_flow (extensible for future call graph)
    dep_type: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float] = mapped_column(nullable=False, server_default="1.0")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")


class IndexingJob(Base):
    __tablename__ = "indexing_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repositories.id"), nullable=False)
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    branch_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    arq_job_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    repository: Mapped[Repository] = relationship(back_populates="indexing_jobs")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    repo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    preferences: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WebhookConfig(Base):
    __tablename__ = "webhook_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repositories.id"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    secret_hash: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default="{push}")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    repository: Mapped[Repository] = relationship(back_populates="webhook_configs")
