from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import extract, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..deps import ensure_child_owned
from ..models import Child, OutfitDiary, User
from ..schemas import DiaryCreate, DiaryOut, DiaryUpdate

router = APIRouter(prefix="/diaries", tags=["diaries"])


def get_owned_diary(db: Session, user: User, diary_id: int) -> OutfitDiary:
    diary = db.scalar(
        select(OutfitDiary)
        .join(Child, OutfitDiary.child_id == Child.id)
        .where(OutfitDiary.id == diary_id, Child.user_id == user.id)
    )
    if diary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="日记不存在")
    return diary


@router.get("", response_model=list[DiaryOut])
def list_diaries(
    child_id: int = Query(...),
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[OutfitDiary]:
    ensure_child_owned(db, current_user, child_id)
    query = select(OutfitDiary).where(OutfitDiary.child_id == child_id)
    if year is not None:
        query = query.where(extract("year", OutfitDiary.date) == year)
    if month is not None:
        query = query.where(extract("month", OutfitDiary.date) == month)
    return list(db.scalars(query.order_by(OutfitDiary.date.desc())))


@router.get("/by-date", response_model=Optional[DiaryOut])
def get_diary_by_date(
    child_id: int = Query(...),
    diary_date: date = Query(..., alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Optional[OutfitDiary]:
    ensure_child_owned(db, current_user, child_id)
    return db.scalar(select(OutfitDiary).where(OutfitDiary.child_id == child_id, OutfitDiary.date == diary_date))


@router.post("", response_model=DiaryOut, status_code=status.HTTP_201_CREATED)
def create_diary(
    payload: DiaryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutfitDiary:
    ensure_child_owned(db, current_user, payload.child_id)
    existing = db.scalar(
        select(OutfitDiary).where(OutfitDiary.child_id == payload.child_id, OutfitDiary.date == payload.date)
    )
    if existing is not None:
        for field, value in payload.model_dump().items():
            setattr(existing, field, value)
        db.commit()
        db.refresh(existing)
        return existing
    diary = OutfitDiary(**payload.model_dump())
    db.add(diary)
    db.commit()
    db.refresh(diary)
    return diary


@router.put("/{diary_id}", response_model=DiaryOut)
def update_diary(
    diary_id: int,
    payload: DiaryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutfitDiary:
    diary = get_owned_diary(db, current_user, diary_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(diary, field, value)
    db.commit()
    db.refresh(diary)
    return diary


@router.delete("/{diary_id}")
def delete_diary(
    diary_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    diary = get_owned_diary(db, current_user, diary_id)
    db.delete(diary)
    db.commit()
    return {"deleted": True}
