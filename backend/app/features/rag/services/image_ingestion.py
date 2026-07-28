"""Extract, name, persist, and index embedded PPTX pictures."""

from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import KnowledgeFile, KnowledgeImage
from app.features.knowledge_bases.services.object_storage import get_storage_client
from app.features.rag.services import document_parser, image_store, sparse_embed
from app.features.rag.services.model_clients import ChatModelClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImageLabel:
    name: str
    description: str


def _fallback_label(file_row: KnowledgeFile, image: document_parser.ParsedImage) -> ImageLabel:
    name = f"{file_row.filename}－第 {image.page_number} 頁－圖片 {image.image_index}"
    description = image.page_text.strip()[:1000] or name
    return ImageLabel(name=name, description=description)


async def generate_label(
    file_row: KnowledgeFile, image: document_parser.ParsedImage
) -> ImageLabel:
    fallback = _fallback_label(file_row, image)
    settings = get_settings()
    client = ChatModelClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )
    prompt = (
        "Name an embedded presentation image using only its slide context. "
        "Use the same language as the slide. Return strict JSON with string "
        'fields "name" (concise, <=80 chars) and "description" (<=300 chars). '
        "Do not claim visual details that are not supported by the slide text.\n"
        f"File: {file_row.filename}\nSlide: {image.page_number}\n"
        f"Image position: {image.image_index}\nSlide text:\n{image.page_text[:5000]}"
    )
    try:
        response = await client.create_chat_completion(
            [{"role": "user", "content": prompt}],
            stream=False,
            temperature=0,
            max_tokens=220,
        )
        raw = response["choices"][0]["message"]["content"].strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        parsed = json.loads(raw)
        name = str(parsed.get("name") or "").strip()[:80]
        description = str(parsed.get("description") or "").strip()[:300]
        if not name or not description:
            return fallback
        return ImageLabel(name=name, description=description)
    except Exception:
        logger.exception(
            "pptx_image_label_failed file_id=%s page=%s image=%s",
            file_row.id,
            image.page_number,
            image.image_index,
        )
        return fallback


async def cleanup_file_images(
    *, session: AsyncSession, file_id: int, commit: bool = True
) -> None:
    rows = (
        await session.scalars(
            select(KnowledgeImage).where(KnowledgeImage.file_id == file_id)
        )
    ).all()
    storage = get_storage_client()
    for row in rows:
        try:
            await storage.delete_object(row.storage_key)
        except Exception:
            logger.exception("image_object_cleanup_failed image_id=%s", row.id)
    try:
        await image_store.delete_by_file(file_id=file_id)
    except Exception:
        logger.exception("image_vector_cleanup_failed file_id=%s", file_id)
    await session.execute(delete(KnowledgeImage).where(KnowledgeImage.file_id == file_id))
    if commit:
        await session.commit()


async def ingest_pptx_images(
    *, session: AsyncSession, file_row: KnowledgeFile, data: bytes
) -> None:
    from app.features.rag.services import ingestion

    await cleanup_file_images(session=session, file_id=file_row.id, commit=False)
    images = document_parser.extract_pptx_images(data)
    if not images:
        await session.commit()
        return
    await image_store.ensure_collection()
    storage = get_storage_client()
    for image in images:
        label = await generate_label(file_row, image)
        row = KnowledgeImage(
            file_id=file_row.id,
            owner_user_id=file_row.owner_user_id,
            knowledge_base_id=file_row.knowledge_base_id,
            page_number=image.page_number,
            image_index=image.image_index,
            name=label.name,
            description=label.description,
            page_text=image.page_text,
            content_sha256=image.content_sha256,
            extension=image.extension,
            content_type=image.content_type,
            size_bytes=len(image.data),
            width_emu=image.width_emu,
            height_emu=image.height_emu,
            storage_key="",
            indexed=False,
        )
        session.add(row)
        await session.flush()
        row.storage_key = (
            f"kb/{file_row.knowledge_base_id}/files/{file_row.id}/images/"
            f"{row.id}.{image.extension}"
        )
        await storage.put_object(
            row.storage_key,
            io.BytesIO(image.data),
            len(image.data),
            image.content_type,
        )
        index_text = (
            f"{label.name}\n{label.description}\n"
            f"Source: {file_row.filename}, slide {image.page_number}\n"
            f"{image.page_text}"
        )
        dense = (await ingestion._embed([index_text]))[0]
        sparse = (await sparse_embed.embed_passages([index_text]))[0]
        await image_store.upsert_image(
            image_id=row.id,
            user_id=file_row.owner_user_id,
            kb_id=file_row.knowledge_base_id,
            file_id=file_row.id,
            filename=file_row.filename,
            name=label.name,
            description=label.description,
            page_text=image.page_text,
            page_number=image.page_number,
            project_id=file_row.project_id,
            dense_vector=dense,
            sparse_vector=sparse,
        )
        row.indexed = True
    await session.commit()
