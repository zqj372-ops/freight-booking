"""Agent - 订舱代理 CRUD"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.models.agent import Agent
from app.schemas.agent import AgentCreate, AgentRead, AgentUpdate

router = APIRouter()


@router.get("/", response_model=list[AgentRead])
async def list_agents(
    is_active: bool | None = None,
    search: str | None = Query(None, description="按 name/code 模糊"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(db_session),
) -> list[AgentRead]:
    stmt = select(Agent)
    if is_active is not None:
        stmt = stmt.where(Agent.is_active == is_active)
    if search:
        like = f"%{search}%"
        stmt = stmt.where((Agent.name.like(like)) | (Agent.code.like(like)))
    stmt = stmt.order_by(Agent.name.asc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [AgentRead.model_validate(r) for r in rows]


@router.post("/", response_model=AgentRead, status_code=201)
async def create_agent(
    payload: AgentCreate,
    db: AsyncSession = Depends(db_session),
) -> AgentRead:
    a = Agent(**payload.model_dump())
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return AgentRead.model_validate(a)


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(agent_id: str, db: AsyncSession = Depends(db_session)) -> AgentRead:
    a = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="agent not found")
    return AgentRead.model_validate(a)


@router.patch("/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    db: AsyncSession = Depends(db_session),
) -> AgentRead:
    a = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="agent not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    await db.commit()
    await db.refresh(a)
    return AgentRead.model_validate(a)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, db: AsyncSession = Depends(db_session)) -> None:
    a = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="agent not found")
    await db.delete(a)
    await db.commit()
