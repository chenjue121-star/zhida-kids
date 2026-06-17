from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import ValidationError

from ..auth import get_current_user
from ..models import User
from ..style_rules import (
    get_current_ruleset,
    parse_ruleset_content,
    safe_import_filename,
    summarize_ruleset,
    validation_error_to_dict,
)

router = APIRouter(prefix="/style-rules", tags=["style-rules"])


@router.get("/current")
def current_style_rules(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    del current_user
    try:
        ruleset = get_current_ruleset()
    except (FileNotFoundError, ValueError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"当前审美策略加载失败: {exc}",
        ) from exc
    return summarize_ruleset(ruleset)


@router.post("/validate")
async def validate_style_rules(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    del current_user
    content = await file.read()
    try:
        ruleset = parse_ruleset_content(content, file.filename or "ruleset.yaml")
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=validation_error_to_dict(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"valid": True, "summary": summarize_ruleset(ruleset)}


@router.post("/import")
async def import_style_rules(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    del current_user
    content = await file.read()
    try:
        ruleset = parse_ruleset_content(content, file.filename or "ruleset.yaml")
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=validation_error_to_dict(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    import_dir = Path(__file__).resolve().parents[1] / "style_profiles" / "imported"
    import_dir.mkdir(parents=True, exist_ok=True)
    target = import_dir / safe_import_filename(ruleset, file.filename or "ruleset.yaml")
    if target.exists():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"策略包版本已存在: {target.name}")
    target.write_bytes(content)
    return {
        "imported": True,
        "path": str(target),
        "summary": summarize_ruleset(ruleset),
        "activation_hint": "如需启用该版本，请将 STYLE_RULESET_PATH 指向该文件并重启服务。",
    }
