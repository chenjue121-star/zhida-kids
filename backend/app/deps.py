from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Child, Clothing, User


def ensure_child_owned(db: Session, user: User, child_id: int) -> Child:
    child = db.scalar(select(Child).where(Child.id == child_id, Child.user_id == user.id))
    if child is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="宝贝不存在")
    return child


def get_owned_clothing(db: Session, user: User, clothing_id: int) -> Clothing:
    item = db.scalar(
        select(Clothing)
        .join(Child, Clothing.child_id == Child.id)
        .where(Clothing.id == clothing_id, Child.user_id == user.id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="衣物不存在")
    return item
