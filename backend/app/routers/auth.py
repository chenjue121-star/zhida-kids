import hashlib

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import create_access_token
from ..config import settings
from ..database import get_db
from ..models import User
from ..schemas import LoginOut, WechatLoginIn

router = APIRouter(prefix="/auth", tags=["auth"])


async def exchange_code_for_session(code: str) -> dict[str, str]:
    if settings.dev_wechat_mock:
        mock_openid = "dev_" + hashlib.sha256(code.encode("utf-8")).hexdigest()[:24]
        return {"openid": mock_openid, "session_key": "dev-session-key"}

    if not settings.wechat_appid or not settings.wechat_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="缺少 WECHAT_APPID 或 WECHAT_SECRET",
        )

    params = {
        "appid": settings.wechat_appid,
        "secret": settings.wechat_secret,
        "js_code": code,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get("https://api.weixin.qq.com/sns/jscode2session", params=params)
        resp.raise_for_status()
        data = resp.json()

    if "openid" not in data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=data.get("errmsg", "微信登录失败"))
    return data


@router.post("/wechat-login", response_model=LoginOut)
async def wechat_login(payload: WechatLoginIn, db: Session = Depends(get_db)) -> LoginOut:
    session = await exchange_code_for_session(payload.code)
    openid = session["openid"]

    user = db.scalar(select(User).where(User.openid == openid))
    if user is None:
        user = User(
            openid=openid,
            session_key=session.get("session_key"),
            nickname=payload.nickname or "智搭用户",
            avatar=payload.avatar or "",
        )
        db.add(user)
    else:
        user.session_key = session.get("session_key")
        if payload.nickname:
            user.nickname = payload.nickname
        if payload.avatar:
            user.avatar = payload.avatar

    db.commit()
    db.refresh(user)

    return LoginOut(
        token=create_access_token(user.id),
        user=user,
        onboarding_complete=bool(user.role and user.city and len(user.children) > 0),
    )
