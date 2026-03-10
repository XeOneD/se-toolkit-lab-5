"""Router for analytics endpoints.

Each endpoint performs SQL aggregation queries on the interaction data
populated by the ETL pipeline. All endpoints require a `lab` query
parameter to filter results by lab (e.g., "lab-01").
"""

from fastapi import APIRouter, Depends, Query, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import select, func, case, col, and_
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import List, Optional

from app.database import get_session
from app.models.item import ItemRecord
from app.models.interaction import InteractionLog
from app.models.learner import Learner
from app.settings import settings

router = APIRouter(tags=["analytics"])

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    """Verify API key from Authorization header."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials.credentials != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return credentials.credentials


async def get_lab_item_ids(lab_slug: str, session: AsyncSession) -> List[int]:
    """Helper function to find lab and its child task IDs."""
    # Convert "lab-01" to "Lab 01" for title matching
    formatted_title = lab_slug.replace("-", " ").title()

    # Find the lab item
    lab_statement = select(ItemRecord).where(col(ItemRecord.title).contains(formatted_title))
    result = await session.exec(lab_statement)
    lab_item = result.first()

    if not lab_item:
        return []

    # Find all child tasks of this lab
    tasks_statement = select(ItemRecord.id).where(
        (ItemRecord.parent_id == lab_item.id) | (ItemRecord.id == lab_item.id)
    )
    tasks_result = await session.exec(tasks_statement)
    return tasks_result.all()


@router.get("/scores")
async def get_scores(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """Score distribution histogram for a given lab."""
    ids = await get_lab_item_ids(lab, session)

    if not ids:
        return [{"bucket": "0-25", "count": 0}, {"bucket": "26-50", "count": 0},
                {"bucket": "51-75", "count": 0}, {"bucket": "76-100", "count": 0}]

    # Group scores into buckets using CASE
    bucket_expr = case(
        (and_(InteractionLog.score >= 0, InteractionLog.score <= 25), "0-25"),
        (and_(InteractionLog.score > 25, InteractionLog.score <= 50), "26-50"),
        (and_(InteractionLog.score > 50, InteractionLog.score <= 75), "51-75"),
        else_="76-100"
    ).label("bucket")

    statement = (
        select(bucket_expr, func.count(InteractionLog.id).label("count"))
        .where(InteractionLog.item_id.in_(ids))
        .where(InteractionLog.score != None)
        .group_by("bucket")
    )

    results = await session.exec(statement)
    found_buckets = {row.bucket: row.count for row in results.all()}

    # Always return all 4 buckets, even if count is 0
    all_buckets = ["0-25", "26-50", "51-75", "76-100"]
    return [{"bucket": b, "count": found_buckets.get(b, 0)} for b in all_buckets]


@router.get("/pass-rates")
async def get_pass_rates(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """Per-task pass rates for a given lab."""
    # Find lab ID
    formatted_title = lab.replace("-", " ").title()
    lab_result = await session.exec(
        select(ItemRecord.id).where(col(ItemRecord.title).contains(formatted_title))
    )
    parent_id = lab_result.first()

    if not parent_id:
        return []

    statement = (
        select(
            ItemRecord.title.label("task"),
            func.round(func.avg(InteractionLog.score), 1).label("avg_score"),
            func.count(InteractionLog.id).label("attempts")
        )
        .join(InteractionLog, InteractionLog.item_id == ItemRecord.id)
        .where(ItemRecord.parent_id == parent_id)
        .group_by(ItemRecord.id)
        .order_by(ItemRecord.title)
    )

    results = await session.exec(statement)
    return [row._asdict() for row in results.all()]


@router.get("/timeline")
async def get_timeline(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """Submissions per day for a given lab."""
    ids = await get_lab_item_ids(lab, session)

    if not ids:
        return []

    statement = (
        select(
            func.date(InteractionLog.created_at).label("date"),
            func.count(InteractionLog.id).label("submissions")
        )
        .where(InteractionLog.item_id.in_(ids))
        .group_by(func.date(InteractionLog.created_at))
        .order_by(func.date(InteractionLog.created_at).asc())
    )

    results = await session.exec(statement)
    return [{"date": str(row.date), "submissions": row.submissions} for row in results.all()]


@router.get("/groups")
async def get_groups(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """Per-group performance for a given lab."""
    ids = await get_lab_item_ids(lab, session)

    if not ids:
        return []

    statement = (
        select(
            Learner.student_group.label("group"),
            func.round(func.avg(InteractionLog.score), 1).label("avg_score"),
            func.count(func.distinct(InteractionLog.learner_id)).label("students")
        )
        .join(Learner, InteractionLog.learner_id == Learner.id)
        .where(InteractionLog.item_id.in_(ids))
        .group_by(Learner.student_group)
        .order_by(Learner.student_group)
    )

    results = await session.exec(statement)
    return [row._asdict() for row in results.all()]
