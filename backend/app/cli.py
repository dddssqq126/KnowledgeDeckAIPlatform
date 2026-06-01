import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select

from app.db.base import async_session_factory
from app.db.models import KnowledgeFile, User
from app.features.knowledge_bases.services.object_storage import get_storage_client
from app.features.rag.services import alias_suggester, document_parser

app = typer.Typer(help="KnowledgeDeck admin CLI", no_args_is_help=True)


# Typer collapses single-command apps unless an explicit callback is registered;
# without this, `python -m app.cli create-user <name>` fails because the
# subcommand name becomes implicit. Registering a no-op callback keeps the
# multi-command group behavior so the subcommand name is required.
@app.callback()
def _main() -> None:
    """KnowledgeDeck admin CLI."""


async def _create_user(username: str, password: str) -> None:
    async with async_session_factory()() as session:
        existing = await session.scalar(select(User).where(User.username == username))
        if existing is not None:
            raise typer.BadParameter(f"user already exists: {username}")
        session.add(User(username=username, password=password))
        await session.commit()


@app.command("create-user")
def create_user(
    username: str,
    password: Annotated[
        str,
        typer.Option(
            prompt=True,
            hide_input=True,
            confirmation_prompt=True,
            help="Password for the new user. Will be prompted if omitted.",
        ),
    ],
) -> None:
    asyncio.run(_create_user(username, password))
    typer.echo(f"created user: {username}")


async def _suggest_tag_aliases(
    *, min_count: int, sample_chars: int, limit_files: int | None
) -> list[dict[str, object]]:
    observations: list[alias_suggester.AliasObservation] = []
    storage = get_storage_client()
    async with async_session_factory()() as session:
        stmt = (
            select(KnowledgeFile)
            .where(KnowledgeFile.deleted_at.is_(None))
            .order_by(KnowledgeFile.id)
        )
        if limit_files is not None:
            stmt = stmt.limit(limit_files)
        rows = (await session.scalars(stmt)).all()

    for row in rows:
        text = ""
        try:
            data = await storage.get_object(row.storage_key)
            segments = document_parser.parse(row.extension, data)
            text = "\n".join(segment.text for segment in segments)[:sample_chars]
        except Exception:
            # Alias suggestions are advisory; keep scanning metadata for this row
            # even when source bytes are missing or parsing fails.
            text = ""
        observations.extend(
            alias_suggester.observations_from_file(
                filename=row.filename,
                text=text,
                vendor=row.tag_vendor,
                platform=row.tag_platform,
                knowledge_type=row.tag_knowledge_type,
                max_text_chars=sample_chars,
            )
        )

    return [
        suggestion.as_dict()
        for suggestion in alias_suggester.suggest_aliases(
            observations, min_count=min_count
        )
    ]


@app.command("suggest-tag-aliases")
def suggest_tag_aliases(
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Optional JSON file path. Defaults to stdout.",
        ),
    ] = None,
    min_count: Annotated[
        int,
        typer.Option(
            min=1,
            help="Minimum observations required before suggesting a canonical alias.",
        ),
    ] = 2,
    sample_chars: Annotated[
        int,
        typer.Option(help="Maximum parsed text characters to scan per file."),
    ] = 6000,
    limit_files: Annotated[
        int | None,
        typer.Option(help="Optional limit for testing on only the first N files."),
    ] = None,
) -> None:
    """Scan stored files and suggest canonical tag aliases as JSON."""
    suggestions = asyncio.run(
        _suggest_tag_aliases(
            min_count=min_count, sample_chars=sample_chars, limit_files=limit_files
        )
    )
    payload = json.dumps({"suggestions": suggestions}, ensure_ascii=False, indent=2)
    if output is not None:
        output.write_text(payload + "\n", encoding="utf-8")
        typer.echo(f"wrote {len(suggestions)} suggestions to {output}")
    else:
        typer.echo(payload)


if __name__ == "__main__":
    app()
