import enum
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

ID_TYPE = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True)
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FileStatus(enum.Enum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    EMBEDDING = "embedding"
    INDEXED = "indexed"
    FAILED = "failed"


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("users.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    files: Mapped[list["KnowledgeFile"]] = relationship(
        back_populates="knowledge_base"
    )

    __table_args__ = (
        Index(
            "uq_kb_owner_name_active",
            "owner_user_id",
            "name",
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
        ),
    )


class KnowledgeFile(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("knowledge_bases.id"), nullable=False
    )
    # Denormalized from knowledge_bases.owner_user_id for direct
    # ownership filtering on file queries without a join. Used by
    # Sub-projects C/D for retrieval permission filtering.
    owner_user_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("users.id"), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    extension: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(ID_TYPE, nullable=False)
    content_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[FileStatus] = mapped_column(
        SAEnum(
            FileStatus,
            name="file_status",
            create_type=False,  # the migration owns the type
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=FileStatus.UPLOADED,
    )
    status_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="files")

    __table_args__ = (
        Index(
            "uq_files_kb_filename_active",
            "knowledge_base_id",
            "filename",
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
        ),
    )


class ChatRole(enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("users.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, default="New Chat")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", order_by="ChatMessage.id"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("chat_sessions.id"), nullable=False
    )
    role: Mapped[ChatRole] = mapped_column(
        SAEnum(
            ChatRole,
            name="chat_role",
            create_type=False,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # List of {"file_id": int, "filename": str} dicts. NULL on user messages.
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    session: Mapped[ChatSession] = relationship(back_populates="messages")


class SlideStatus(enum.Enum):
    OUTLINING = "outlining"
    RENDERING = "rendering"
    RENDERED = "rendered"
    FAILED = "failed"


class SlideRole(enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class SlideSession(Base):
    __tablename__ = "slide_sessions"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("users.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, default="New deck")
    status: Mapped[SlideStatus] = mapped_column(
        SAEnum(
            SlideStatus,
            name="slide_status",
            create_type=False,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=SlideStatus.OUTLINING,
    )
    # MinIO object key for the most recently rendered PPTX, NULL until first
    # successful render. New renders overwrite the key.
    generated_pptx_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional visual template authored in Presenton's UI. When set, render
    # passes this id as the `template` field to Presenton's /generate; when
    # NULL, falls back to the marker / request-body / default chain.
    custom_template_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_template_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    messages: Mapped[list["SlideMessage"]] = relationship(
        back_populates="session", order_by="SlideMessage.id"
    )


class SlideMessage(Base):
    __tablename__ = "slide_messages"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("slide_sessions.id"), nullable=False
    )
    role: Mapped[SlideRole] = mapped_column(
        SAEnum(
            SlideRole,
            name="slide_role",
            create_type=False,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    session: Mapped[SlideSession] = relationship(back_populates="messages")
