# """Router for analytics endpoints.

# Each endpoint performs SQL aggregation queries on the interaction data
# populated by the ETL pipeline. All endpoints require a `lab` query
# parameter to filter results by lab (e.g., "lab-01").
# """

# from fastapi import APIRouter, Depends, Query
# from sqlmodel.ext.asyncio.session import AsyncSession

# from app.database import get_session

# router = APIRouter()


# @router.get("/scores")
# async def get_scores(
#     lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
#     session: AsyncSession = Depends(get_session),
# ):
#     """Score distribution histogram for a given lab.

#     TODO: Implement this endpoint.
#     - Find the lab item by matching title (e.g. "lab-04" → title contains "Lab 04")
#     - Find all tasks that belong to this lab (parent_id = lab.id)
#     - Query interactions for these items that have a score
#     - Group scores into buckets: "0-25", "26-50", "51-75", "76-100"
#       using CASE WHEN expressions
#     - Return a JSON array:
#       [{"bucket": "0-25", "count": 12}, {"bucket": "26-50", "count": 8}, ...]
#     - Always return all four buckets, even if count is 0
#     """
#     raise NotImplementedError


# @router.get("/pass-rates")
# async def get_pass_rates(
#     lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
#     session: AsyncSession = Depends(get_session),
# ):
#     """Per-task pass rates for a given lab.

#     TODO: Implement this endpoint.
#     - Find the lab item and its child task items
#     - For each task, compute:
#       - avg_score: average of interaction scores (round to 1 decimal)
#       - attempts: total number of interactions
#     - Return a JSON array:
#       [{"task": "Repository Setup", "avg_score": 92.3, "attempts": 150}, ...]
#     - Order by task title
#     """
#     raise NotImplementedError


# @router.get("/timeline")
# async def get_timeline(
#     lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
#     session: AsyncSession = Depends(get_session),
# ):
#     """Submissions per day for a given lab.

#     TODO: Implement this endpoint.
#     - Find the lab item and its child task items
#     - Group interactions by date (use func.date(created_at))
#     - Count the number of submissions per day
#     - Return a JSON array:
#       [{"date": "2026-02-28", "submissions": 45}, ...]
#     - Order by date ascending
#     """
    
#     item_ids = db.query(Item.id).filter(
#         (Item.id == item_id) | (Item.parent_id == item_id)
#     ).subquery()

#     timeline_data = (
#         db.query(
#             func.date(Interaction.created_at).label("date"),
#             func.count(Interaction.id).label("submissions")
#         )
#         .filter(Interaction.item_id.in_(item_ids))
#         .group_by(func.date(Interaction.created_at))
#         .order_by(func.date(Interaction.created_at).asc())
#         .all()
#     )

#     return [
#         {"date": str(row.date), "submissions": row.submissions} 
#         for row in timeline_data
#     ]


# @router.get("/groups")
# async def get_groups(
#     lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
#     session: AsyncSession = Depends(get_session),
# ):
#     """Per-group performance for a given lab.

#     TODO: Implement this endpoint.
#     - Find the lab item and its child task items
#     - Join interactions with learners to get student_group
#     - For each group, compute:
#       - avg_score: average score (round to 1 decimal)
#       - students: count of distinct learners
#     - Return a JSON array:
#       [{"group": "B23-CS-01", "avg_score": 78.5, "students": 25}, ...]
#     - Order by group name
#     """
#     raise NotImplementedError


from fastapi import APIRouter, Depends, Query, HTTPException
from sqlmodel import select, func, case, col, and_
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import List, Dict, Any

from app.database import get_session
from app.models import Item, Interaction, Learner
from app.auth import get_current_user  # Важно для получения ошибки 401

router = APIRouter(prefix="/analytics", tags=["analytics"])

async def get_lab_item_ids(lab_slug: str, session: AsyncSession) -> List[int]:
    """Вспомогательная функция для поиска ID лабы и её подзадач."""
    # Преобразуем "lab-01" в "Lab 01" для поиска по заголовку
    formatted_title = lab_slug.replace("-", " ").title()
    
    # Ищем саму лабу
    lab_statement = select(Item).where(col(Item.title).contains(formatted_title))
    result = await session.exec(lab_statement)
    lab_item = result.first()
    
    if not lab_item:
        return []
    
    # Ищем все подзадачи (tasks) этой лабы
    tasks_statement = select(Item.id).where((Item.parent_id == lab_item.id) | (Item.id == lab_item.id))
    tasks_result = await session.exec(tasks_statement)
    return tasks_result.all()

@router.get("/scores")
async def get_scores(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
    current_user: Any = Depends(get_current_user), # Защита эндпоинта
):
    ids = await get_lab_item_ids(lab, session)
    
    # Группировка по бакетам через CASE
    bucket_expr = case(
        (and_(Interaction.score >= 0, Interaction.score <= 25), "0-25"),
        (and_(Interaction.score > 25, Interaction.score <= 50), "26-50"),
        (and_(Interaction.score > 50, Interaction.score <= 75), "51-75"),
        else_="76-100"
    ).label("bucket")

    statement = (
        select(bucket_expr, func.count(Interaction.id).label("count"))
        .where(Interaction.item_id.in_(ids))
        .where(Interaction.score != None)
        .group_by("bucket")
    )
    
    results = await session.exec(statement)
    found_buckets = {row.bucket: row.count for row in results.all()}
    
    # Гарантируем наличие всех 4 бакетов, даже если там 0
    all_buckets = ["0-25", "26-50", "51-75", "76-100"]
    return [{"bucket": b, "count": found_buckets.get(b, 0)} for b in all_buckets]

@router.get("/pass-rates")
async def get_pass_rates(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
    current_user: Any = Depends(get_current_user),
):
    # Ищем ID задач этой лабы (исключая саму лабу-родителя для этого отчета)
    formatted_title = lab.replace("-", " ").title()
    lab_res = await session.exec(select(Item.id).where(col(Item.title).contains(formatted_title)))
    parent_id = lab_res.first()
    
    if not parent_id:
        return []

    statement = (
        select(
            Item.title.label("task"),
            func.round(func.avg(Interaction.score), 1).label("avg_score"),
            func.count(Interaction.id).label("attempts")
        )
        .join(Interaction, Interaction.item_id == Item.id)
        .where(Item.parent_id == parent_id)
        .group_by(Item.id)
        .order_by(Item.title)
    )
    
    results = await session.exec(statement)
    return [row._asdict() for row in results.all()]

@router.get("/timeline")
async def get_timeline(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
    current_user: Any = Depends(get_current_user),
):
    ids = await get_lab_item_ids(lab, session)
    
    statement = (
        select(
            func.date(Interaction.created_at).label("date"),
            func.count(Interaction.id).label("submissions")
        )
        .where(Interaction.item_id.in_(ids))
        .group_by(func.date(Interaction.created_at))
        .order_by(func.date(Interaction.created_at).asc())
    )
    
    results = await session.exec(statement)
    return [{"date": str(row.date), "submissions": row.submissions} for row in results.all()]

@router.get("/groups")
async def get_groups(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
    current_user: Any = Depends(get_current_user),
):
    ids = await get_lab_item_ids(lab, session)
    
    statement = (
        select(
            Learner.student_group.label("group"),
            func.round(func.avg(Interaction.score), 1).label("avg_score"),
            func.count(func.distinct(Interaction.learner_id)).label("students")
        )
        .join(Learner, Interaction.learner_id == Learner.id)
        .where(Interaction.item_id.in_(ids))
        .group_by(Learner.student_group)
        .order_by(Learner.student_group)
    )
    
    results = await session.exec(statement)
    return [row._asdict() for row in results.all()]