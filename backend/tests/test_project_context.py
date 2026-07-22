import pytest

from app.db.models import ProjectInfo
from app.features.chat.services import project_context


def test_parse_entities_accepts_json_code_fence() -> None:
    entities = project_context._parse_entities(
        '```json\n{"customer":"Acme", "project":"Falcon", "model_id":"X-10"}\n```'
    )

    assert entities == project_context.ProjectEntities(
        customer="Acme", project="Falcon", model_id="X-10"
    )


@pytest.mark.asyncio
async def test_customer_only_lookup_returns_five_newest(db_session) -> None:
    db_session.add_all(
        [
            ProjectInfo(
                customer_code="111",
                customer_name="Acme",
                project_name=f"Project {number}",
                model_id=f"M-{number}",
                project_data={"sequence": number},
            )
            for number in range(1, 8)
        ]
    )
    await db_session.commit()

    rows = await project_context.find_project_info(
        db_session, project_context.ProjectEntities(customer="acme")
    )

    assert [row.project_name for row in rows] == [
        "Project 7",
        "Project 6",
        "Project 5",
        "Project 4",
        "Project 3",
    ]


@pytest.mark.asyncio
async def test_project_or_model_lookup_returns_one_row(db_session) -> None:
    db_session.add_all(
        [
            ProjectInfo(
                customer_code="111",
                customer_name="Acme",
                project_name="Falcon",
                model_id="X-10",
                project_data={"region": "TW"},
            ),
            ProjectInfo(
                customer_code="222",
                customer_name="Acme",
                project_name="Other",
                model_id="X-20",
                project_data=None,
            ),
        ]
    )
    await db_session.commit()

    by_project = await project_context.find_project_info(
        db_session, project_context.ProjectEntities(project="falcon")
    )
    by_model = await project_context.find_project_info(
        db_session, project_context.ProjectEntities(model_id="x-20")
    )

    assert len(by_project) == 1
    assert by_project[0].model_id == "X-10"
    assert len(by_model) == 1
    assert by_model[0].project_name == "Other"


@pytest.mark.asyncio
async def test_unlabelled_customer_code_returns_five_projects(db_session) -> None:
    db_session.add_all(
        [
            ProjectInfo(
                customer_code="111",
                customer_name="Acme",
                project_name=f"Product {number}",
                model_id=f"A-{number}",
            )
            for number in range(1, 7)
        ]
    )
    await db_session.commit()

    context = await project_context.load_project_context(
        db_session, "給我111的產品資訊"
    )

    assert '"customer_code": "111"' in context
    assert context.count('"project":') == 5
    assert '"project": "Product 6"' in context
    assert '"project": "Product 1"' not in context
    assert (
        await project_context.resolve_entities_from_catalog(
            db_session, "給我1112的產品資訊"
        )
        is None
    )


@pytest.mark.asyncio
async def test_catalog_maps_unlabelled_project_and_model_before_llm(
    db_session, monkeypatch
) -> None:
    db_session.add_all(
        [
            ProjectInfo(
                customer_code="111",
                customer_name="Acme",
                project_name="Falcon",
                model_id="FX-100",
                project_data={"matched": "falcon"},
            ),
            ProjectInfo(
                customer_code="222",
                customer_name="Beta",
                project_name="Falcon Pro",
                model_id="FP-200",
                project_data={"matched": "falcon-pro"},
            ),
        ]
    )
    await db_session.commit()

    async def llm_must_not_run(_query: str) -> project_context.ProjectEntities:
        raise AssertionError("catalog match should happen before LLM extraction")

    monkeypatch.setattr(project_context, "extract_project_entities", llm_must_not_run)

    project_result = await project_context.load_project_context(
        db_session, "給我 Falcon Pro 的產品資訊"
    )
    model_result = await project_context.load_project_context(
        db_session, "請列出 fp－200 的資訊"
    )

    assert '"project": "Falcon Pro"' in project_result
    assert '"project": "Falcon"' not in project_result
    assert '"model_id": "FP-200"' in model_result


@pytest.mark.asyncio
async def test_ambiguous_catalog_match_falls_back_to_llm(
    db_session, monkeypatch
) -> None:
    db_session.add_all(
        [
            ProjectInfo(
                customer_name="Acme",
                project_name="Alpha",
                model_id="A-1",
            ),
            ProjectInfo(
                customer_name="Beta",
                project_name="Bravo",
                model_id="B-1",
            ),
        ]
    )
    await db_session.commit()
    called = False

    async def disambiguate(_query: str) -> project_context.ProjectEntities:
        nonlocal called
        called = True
        return project_context.ProjectEntities(project="Bravo", customer="Beta")

    monkeypatch.setattr(project_context, "extract_project_entities", disambiguate)

    context = await project_context.load_project_context(
        db_session, "比較 Alpha 和 Bravo project"
    )

    assert called is True
    assert '"customer": "Beta"' in context


@pytest.mark.asyncio
async def test_load_project_context_skips_database_without_entities(
    db_session, monkeypatch
) -> None:
    async def no_entities(_query: str) -> project_context.ProjectEntities:
        return project_context.ProjectEntities()

    monkeypatch.setattr(project_context, "extract_project_entities", no_entities)

    assert await project_context.load_project_context(db_session, "hello") == ""
