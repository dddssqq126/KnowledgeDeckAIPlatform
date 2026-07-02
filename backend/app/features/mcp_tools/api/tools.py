from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.db.models import McpTool, User
from app.features.mcp_tools.services import tool_service
from app.shared.api.deps import get_current_user

router = APIRouter(prefix="/mcp-tools", tags=["mcp-tools"])

McpToolStatus = Literal["enabled", "disabled"]
McpTransport = Literal["in-process", "stdio", "http"]
McpMethod = Literal["GET", "POST"]


class McpToolOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str
    query_name: str = Field(alias="queryName")
    server_name: str = Field(alias="serverName")
    description: str
    transport: McpTransport
    method: McpMethod
    endpoint: str
    template_id: str = Field(alias="templateId")
    timeout_sec: int = Field(alias="timeoutSec")
    status: McpToolStatus
    input_schema: dict[str, str] = Field(alias="inputSchema")
    output_schema: dict[str, str] = Field(alias="outputSchema")
    built_in: bool = Field(alias="builtIn")
    handler_key: str = Field(alias="handlerKey")
    updated_at: str = Field(alias="updatedAt")


class McpToolCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1)
    query_name: str = Field(alias="queryName", min_length=1)
    server_name: str = Field(alias="serverName", min_length=1)
    description: str = ""
    transport: McpTransport = "in-process"
    method: McpMethod = "POST"
    endpoint: str = ""
    template_id: str = Field(default="", alias="templateId")
    timeout_sec: int = Field(default=10, alias="timeoutSec", gt=0)
    input_schema: dict[str, Any] = Field(default_factory=dict, alias="inputSchema")
    output_schema: dict[str, Any] = Field(default_factory=dict, alias="outputSchema")


class McpToolStatusUpdate(BaseModel):
    status: McpToolStatus


def _out(tool: McpTool) -> McpToolOut:
    updated = tool.updated_at
    if not isinstance(updated, datetime):
        updated_at = str(updated)
    else:
        updated_at = updated.isoformat()
    return McpToolOut(
        id=tool.id,
        name=tool.name,
        queryName=tool.query_name,
        serverName=tool.server_name,
        description=tool.description,
        transport=tool.transport,
        method=tool.method,
        endpoint=tool.endpoint,
        templateId=tool.template_id,
        timeoutSec=tool.timeout_sec,
        status=tool.status,
        inputSchema={str(k): str(v) for k, v in (tool.input_schema or {}).items()},
        outputSchema={str(k): str(v) for k, v in (tool.output_schema or {}).items()},
        builtIn=tool.built_in,
        handlerKey=tool.handler_key,
        updatedAt=updated_at,
    )


@router.get("", response_model=list[McpToolOut])
async def list_mcp_tools(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[McpToolOut]:
    tools = await tool_service.list_visible_tools(session, owner_user_id=user.id)
    return [_out(tool) for tool in tools]


@router.post("", response_model=McpToolOut, status_code=status.HTTP_201_CREATED)
async def create_mcp_tool(
    body: McpToolCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> McpToolOut:
    try:
        tool = await tool_service.create_custom_tool(
            session,
            owner_user_id=user.id,
            name=body.name,
            query_name=body.query_name,
            server_name=body.server_name,
            description=body.description,
            transport=body.transport,
            method=body.method,
            endpoint=body.endpoint,
            template_id=body.template_id,
            timeout_sec=body.timeout_sec,
            input_schema=body.input_schema,
            output_schema=body.output_schema,
        )
        await session.commit()
        await session.refresh(tool)
    except tool_service.ToolRegistrationError as exc:
        await session.rollback()
        code = status.HTTP_409_CONFLICT if exc.code == "duplicate_query_name" else 422
        raise HTTPException(code, detail=exc.code) from exc
    return _out(tool)


@router.patch("/{tool_id}/status", response_model=McpToolOut)
async def update_mcp_tool_status(
    tool_id: int,
    body: McpToolStatusUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> McpToolOut:
    tool = await tool_service.get_owned_or_global_tool(
        session, owner_user_id=user.id, tool_id=tool_id
    )
    if tool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tool_not_found")
    try:
        await tool_service.set_tool_status(session, tool=tool, status=body.status)
        await session.commit()
        await session.refresh(tool)
    except tool_service.ToolRegistrationError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.code) from exc
    return _out(tool)


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_tool(
    tool_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    tool = await tool_service.get_owned_or_global_tool(
        session, owner_user_id=user.id, tool_id=tool_id
    )
    if tool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tool_not_found")
    if tool.built_in or tool.owner_user_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="built_in_tool")
    await session.delete(tool)
    await session.commit()
