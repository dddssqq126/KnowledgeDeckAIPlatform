from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.api.deps import get_current_user
from app.db.base import get_db
from app.db.models import User
from app.shared.services.auth_service import (
    authenticate,
    create_login_record,
    get_or_create_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class ExternalLoginRequest(BaseModel):
    username: str = Field(min_length=1)


class LoginRecordRequest(BaseModel):
    DeptName: str | None = Field(default=None, max_length=255)
    Chinesename: str | None = Field(default=None, max_length=255)
    DeptID: str | None = Field(default=None, max_length=255)
    EmpId: str | None = Field(default=None, max_length=255)
    UserAccountName: str = Field(min_length=1, max_length=255)


class UserSummary(BaseModel):
    id: int
    username: str


class LoginResponse(BaseModel):
    token: str
    user: UserSummary


class MeResponse(BaseModel):
    id: int
    username: str
    created_at: str


class LoginRecordResponse(BaseModel):
    id: int
    DeptName: str | None
    Chinesename: str | None
    DeptID: str | None
    EmpId: str | None
    UserAccountName: str
    created_at: str


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_db)) -> LoginResponse:
    user = await authenticate(session, body.username, body.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")
    return LoginResponse(
        token=f"u_{user.id}",
        user=UserSummary(id=user.id, username=user.username),
    )


@router.post("/external", response_model=LoginResponse)
async def external_login(
    body: ExternalLoginRequest, session: AsyncSession = Depends(get_db)
) -> LoginResponse:
    """Passwordless login: provision (or reuse) a user by username and issue
    its token. Intended for embedded/SSO use where identity arrives via the
    URL — see the frontend login page + resolveExternalUsername()."""
    user = await get_or_create_user(session, body.username)
    return LoginResponse(
        token=f"u_{user.id}",
        user=UserSummary(id=user.id, username=user.username),
    )


@router.post(
    "/login-records",
    response_model=LoginRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_login(
    body: LoginRecordRequest, session: AsyncSession = Depends(get_db)
) -> LoginRecordResponse:
    record = await create_login_record(
        session,
        dept_name=body.DeptName,
        chinese_name=body.Chinesename,
        dept_id=body.DeptID,
        emp_id=body.EmpId,
        user_account_name=body.UserAccountName,
    )
    return LoginRecordResponse(
        id=record.id,
        DeptName=record.dept_name,
        Chinesename=record.chinese_name,
        DeptID=record.dept_id,
        EmpId=record.emp_id,
        UserAccountName=record.user_account_name,
        created_at=record.created_at.isoformat(),
    )


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        id=user.id,
        username=user.username,
        created_at=user.created_at.isoformat(),
    )
