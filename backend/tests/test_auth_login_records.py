import pytest
from sqlalchemy import select

from app.db.models import LoginRecord


@pytest.mark.asyncio
async def test_create_login_record(http_client, db_session) -> None:
    response = await http_client.post(
        "/auth/login-records",
        json={
            "DeptName": "IT",
            "Chinesename": "王小明",
            "DeptID": "D001",
            "EmpId": "E123",
            "UserAccountName": "ming.wang",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 1
    assert body["DeptName"] == "IT"
    assert body["Chinesename"] == "王小明"
    assert body["DeptID"] == "D001"
    assert body["EmpId"] == "E123"
    assert body["UserAccountName"] == "ming.wang"
    assert body["created_at"]

    record = await db_session.scalar(
        select(LoginRecord).where(LoginRecord.user_account_name == "ming.wang")
    )
    assert record is not None
    assert record.dept_name == "IT"
    assert record.chinese_name == "王小明"
    assert record.dept_id == "D001"
    assert record.emp_id == "E123"


@pytest.mark.asyncio
async def test_create_login_record_requires_user_account_name(http_client) -> None:
    response = await http_client.post(
        "/auth/login-records",
        json={"DeptName": "IT", "UserAccountName": ""},
    )

    assert response.status_code == 422
