# 后端重构 Phase 1 实施计划（特征测试 + 结构分层）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `clothing.py` / `outfits.py` 高风险路径建立特征测试安全网，然后把两个巨型路由"迁移式"拆成聚焦的服务/领域模块，对外接口零变更。

**Architecture:** 先写特征测试锁定当前行为（全绿基线），再小步迁移：每步仅"移动函数 + 改 import"，函数体逐字复制，每步后测试全绿。棘手纯函数用 golden-master（捕获当前输出冻结为期望值）。

**Tech Stack:** FastAPI、SQLAlchemy 2.0、pytest、pytest-asyncio、respx（stub httpx）、SQLite（测试库）。

设计依据：[docs/superpowers/specs/2026-06-19-backend-refactor-phase1-design.md](../specs/2026-06-19-backend-refactor-phase1-design.md)

**所有命令均在 `backend/` 目录下执行，并已激活 `.venv`：**
```bash
cd backend && source .venv/bin/activate
```

---

## Task 1: 测试基础设施

**Files:**
- Create: `backend/requirements-dev.txt`
- Create: `backend/pytest.ini`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: 写 dev 依赖文件**

Create `backend/requirements-dev.txt`:
```
-r requirements.txt
pytest==8.3.4
pytest-asyncio==0.25.2
respx==0.22.0
```

- [ ] **Step 2: 安装 dev 依赖**

Run: `pip install -r requirements-dev.txt`
Expected: 成功安装 pytest / pytest-asyncio / respx。

- [ ] **Step 3: 写 pytest 配置**

Create `backend/pytest.ini`:
```ini
[pytest]
testpaths = tests
asyncio_mode = auto
filterwarnings =
    ignore::DeprecationWarning
```

- [ ] **Step 4: 写 conftest（测试库 + 依赖覆盖 + fixtures）**

Create `backend/tests/__init__.py`（空文件）。

Create `backend/tests/conftest.py`。
**关键：必须在 import 任何 `app.*` 模块之前设置环境变量**，否则 `app.config.settings`
会读 `.env`（MySQL）并在 `create_app()` 的 `create_all` 时连真实数据库。

```python
import os
import tempfile

# 必须在导入 app 之前设置：让 database.engine 指向临时 SQLite 文件
_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".sqlite3")
os.close(_DB_FD)
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_DB_PATH}"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["DEV_WECHAT_MOCK"] = "true"

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import Base, SessionLocal, engine, get_db
from app.main import create_app
from app.models import Child, Clothing, User


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def seed(db_session):
    """建一个 user + child + 两件 clothing，返回字典方便断言。"""
    # 清表，保证用例间隔离
    for model in (Clothing, Child, User):
        db_session.query(model).delete()
    db_session.commit()

    user = User(openid="test-openid", nickname="测试家长")
    db_session.add(user)
    db_session.flush()

    child = Child(
        user_id=user.id, nickname="宝宝", gender="boy",
        birthday=date(2022, 1, 1), height=90.0,
    )
    db_session.add(child)
    db_session.flush()

    top = Clothing(
        child_id=child.id, type="top", main_color="white",
        thickness="normal", pattern="solid", season=["all"], style_tags=["casual"],
    )
    pants = Clothing(
        child_id=child.id, type="pants", main_color="navy",
        thickness="normal", pattern="solid", season=["all"], style_tags=["casual"],
    )
    db_session.add_all([top, pants])
    db_session.commit()
    return {"user_id": user.id, "child_id": child.id,
            "top_id": top.id, "pants_id": pants.id}


@pytest.fixture
def client(seed, db_session):
    """已认证 TestClient：覆盖 get_current_user 返回 seed 用户。"""
    app = create_app()

    def _override_user():
        return db_session.get(User, seed["user_id"])

    app.dependency_overrides[get_current_user] = _override_user
    with TestClient(app) as c:
        c.seed = seed  # 方便用例取 id
        yield c
    app.dependency_overrides.clear()
```

- [ ] **Step 5: 冒烟验证基础设施**

Create `backend/tests/test_smoke.py`:
```python
def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

Run: `pytest tests/test_smoke.py -v`
Expected: PASS。若失败多为 import 顺序问题——确认 conftest 顶部 `os.environ` 在所有 `app.*` import 之前。

- [ ] **Step 6: Commit**

```bash
git add backend/requirements-dev.txt backend/pytest.ini backend/tests/
git commit -m "test: 后端测试基础设施（SQLite + 依赖覆盖 + fixtures）"
```

---

## Task 2: CRUD 特征测试（clothing 路由）

锁定 list/create/get/update/wear/delete 与归属 404 的当前行为。

**Files:**
- Create: `backend/tests/test_clothing_crud.py`

- [ ] **Step 1: 写 CRUD 特征测试**

Create `backend/tests/test_clothing_crud.py`:
```python
def test_list_clothing_returns_child_items(client):
    child_id = client.seed["child_id"]
    resp = client.get("/clothing", params={"child_id": child_id})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    assert {i["type"] for i in items} == {"top", "pants"}


def test_list_clothing_unknown_child_404(client):
    resp = client.get("/clothing", params={"child_id": 999999})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "宝贝不存在"


def test_create_clothing(client):
    child_id = client.seed["child_id"]
    payload = {
        "child_id": child_id, "type": "shoes", "main_color": "red",
        "thickness": "normal", "pattern": "solid",
        "season": ["all"], "style_tags": ["sporty"],
    }
    resp = client.post("/clothing", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["type"] == "shoes"
    assert body["main_color"] == "red"


def test_get_clothing(client):
    top_id = client.seed["top_id"]
    resp = client.get(f"/clothing/{top_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == top_id


def test_get_clothing_not_owned_404(client):
    resp = client.get("/clothing/999999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "衣物不存在"


def test_update_clothing_partial(client):
    top_id = client.seed["top_id"]
    resp = client.put(f"/clothing/{top_id}", json={"main_color": "black"})
    assert resp.status_code == 200
    assert resp.json()["main_color"] == "black"


def test_mark_worn_increments_count(client):
    top_id = client.seed["top_id"]
    resp = client.post(f"/clothing/{top_id}/wear")
    assert resp.status_code == 200
    body = resp.json()
    assert body["wear_count"] == 1
    assert body["last_worn_at"] is not None


def test_delete_clothing(client):
    top_id = client.seed["top_id"]
    resp = client.delete(f"/clothing/{top_id}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True}
    assert client.get(f"/clothing/{top_id}").status_code == 404
```

- [ ] **Step 2: 跑测试**

Run: `pytest tests/test_clothing_crud.py -v`
Expected: 全部 PASS。若某断言与实际响应不符，**以当前代码实际行为为准修正断言**（这是特征测试，目的是锁定现状，不是改行为）。

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_clothing_crud.py
git commit -m "test: clothing CRUD 特征测试"
```

---

## Task 3: 识别管线特征测试

覆盖纯解析器（golden-master）+ `/clothing/recognize` 路由（respx stub ARK）。

**Files:**
- Create: `backend/tests/test_recognition_parsing.py`
- Create: `backend/tests/test_recognition_route.py`

- [ ] **Step 1: 写纯解析器测试（针对当前 clothing.py 中的私有函数）**

Create `backend/tests/test_recognition_parsing.py`:
```python
import pytest
from fastapi import HTTPException

from app.routers.clothing import (
    _extract_json,
    _pick_recognition_object,
    _normalize_recognition,
)


def test_extract_json_plain_object():
    assert _extract_json('{"type": "top"}') == {"type": "top"}


def test_extract_json_strips_markdown_fence():
    text = '```json\n{"type": "pants", "main_color": "navy"}\n```'
    assert _extract_json(text) == {"type": "pants", "main_color": "navy"}


def test_extract_json_finds_object_in_prose():
    text = '识别结果如下：{"type": "shoes"} 仅供参考'
    assert _extract_json(text) == {"type": "shoes"}


def test_extract_json_array():
    assert _extract_json('[{"type": "top"}, {"type": "pants"}]') == [
        {"type": "top"}, {"type": "pants"}
    ]


def test_extract_json_empty_raises_502():
    with pytest.raises(HTTPException) as exc:
        _extract_json("   ")
    assert exc.value.status_code == 502


def test_extract_json_no_json_raises_502():
    with pytest.raises(HTTPException) as exc:
        _extract_json("这里没有任何 JSON")
    assert exc.value.status_code == 502


def test_pick_recognition_object_unwraps_result_key():
    parsed = {"result": {"type": "top", "main_color": "white"}}
    assert _pick_recognition_object(parsed) == {"type": "top", "main_color": "white"}


def test_pick_recognition_object_picks_most_complete_from_list():
    parsed = [
        {"type": "top"},
        {"type": "pants", "main_color": "navy", "confidence": 0.9},
    ]
    picked = _pick_recognition_object(parsed)
    assert picked["type"] == "pants"
    assert "识别到多件衣物" in picked["notes"]


def test_normalize_recognition_maps_chinese_aliases():
    # golden-master：记录当前 _normalize_recognition 的实际输出后冻结
    out = _normalize_recognition({
        "type": "上衣", "main_color": "白色", "pattern": "条纹",
        "thickness": "薄", "season": "夏季", "style_tags": ["休闲"],
    })
    assert out.type == "top"
    assert out.main_color == "white"
    assert out.pattern == "stripe"
    assert out.thickness == "thin"
    assert out.season == ["summer"]
    assert out.style_tags == ["casual"]
```

- [ ] **Step 2: 跑解析器测试，确认行为（必要时修正断言为实际输出）**

Run: `pytest tests/test_recognition_parsing.py -v`
Expected: PASS。`test_normalize_recognition_maps_chinese_aliases` 若与实际不符，**先打印实际输出**（`print(out.model_dump())`）再把断言改成实际值——这就是 golden-master 冻结。

- [ ] **Step 3: 写 recognize 路由测试（respx stub ARK）**

Create `backend/tests/test_recognition_route.py`:
```python
import os

import httpx
import respx

ARK_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"


@respx.mock
def test_recognize_clothing_parses_ark_response(client, monkeypatch):
    # 关闭 mock，走真实解析路径
    monkeypatch.setattr("app.routers.clothing.settings.dev_ai_mock", False)
    monkeypatch.setattr("app.routers.clothing.settings.ark_api_key", "test-key")
    # 让图片 URL 直接通过（已是公网 http 且非本地）
    monkeypatch.setattr(
        "app.routers.clothing._ark_image_url_or_data_url",
        lambda photo_url: "https://example.com/a.jpg",
    )

    ark_payload = {
        "output_text": '{"type": "上衣", "main_color": "白色", "thickness": "薄"}'
    }
    route = respx.post(ARK_URL).mock(
        return_value=httpx.Response(200, json=ark_payload)
    )

    resp = client.post("/clothing/recognize", json={"photo_url": "https://example.com/a.jpg"})
    assert route.called
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "top"
    assert body["main_color"] == "white"
    assert body["thickness"] == "thin"


def test_recognize_clothing_mock_mode(client, monkeypatch):
    monkeypatch.setattr("app.routers.clothing.settings.dev_ai_mock", True)
    resp = client.post("/clothing/recognize", json={"photo_url": "x"})
    assert resp.status_code == 200
    assert resp.json()["type"] == "accessory"  # _mock_recognition 当前返回值
```

- [ ] **Step 4: 跑路由测试**

Run: `pytest tests/test_recognition_route.py -v`
Expected: PASS。注意 respx 拦截的 URL 须与 `settings.ark_responses_url` 完全一致；若 .env 改过该值，相应更新 `ARK_URL`。

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_recognition_parsing.py backend/tests/test_recognition_route.py
git commit -m "test: 识别管线特征测试（解析器 golden-master + recognize 路由）"
```

---

## Task 4: 搭配推荐特征测试

覆盖纯评分函数（golden-master）+ `/outfits/recommend` 的缓存命中 / AI 成功 / 兜底三条路径。

**Files:**
- Create: `backend/tests/test_outfit_scoring.py`
- Create: `backend/tests/test_outfit_route.py`

- [ ] **Step 1: 写纯评分函数测试**

Create `backend/tests/test_outfit_scoring.py`:
```python
from app.routers.outfits import (
    child_age_months,
    current_season,
    recommended_thickness,
)


def test_recommended_thickness_buckets():
    # golden-master：以当前实现实际返回值为准冻结
    assert recommended_thickness(30) in {"thin", "normal", "thick", "fleece"}
    assert recommended_thickness(-5) in {"thin", "normal", "thick", "fleece"}


def test_current_season_returns_valid_season():
    assert current_season() in {"spring", "summer", "autumn", "winter"}


def test_child_age_months_positive(seed, db_session):
    from app.models import Child
    child = db_session.get(Child, seed["child_id"])
    assert child_age_months(child) > 0
```

> 注：`score_item` / `choose_style_profile` 签名较复杂（依赖 ruleset、profile scores）。
> 本计划聚焦高风险路径，路由级测试（Step 3）已端到端覆盖它们的组合行为；此处只为
> 易隔离的纯函数加单测。执行时若发现某函数可低成本隔离测试，可补充。

- [ ] **Step 2: 跑评分测试，冻结实际值**

Run: `pytest tests/test_outfit_scoring.py -v`
Expected: PASS。若想精确冻结 `recommended_thickness` 的分桶边界，先 `print` 各温度返回值再写精确断言。

- [ ] **Step 3: 写 recommend 路由三路径测试**

Create `backend/tests/test_outfit_route.py`:
```python
def _recommend_payload(child_id):
    return {"child_id": child_id, "scene": "daily", "temperature": 20}


def test_recommend_fallback_when_ai_unavailable(client, monkeypatch):
    # 强制 AI 返回 None → 走兜底
    async def _no_ai(*args, **kwargs):
        return None
    monkeypatch.setattr("app.routers.outfits.call_ai_recommend", _no_ai)
    monkeypatch.setattr("app.routers.outfits.settings.dev_outfit_mock", False)

    child_id = client.seed["child_id"]
    resp = client.post("/outfits/recommend", json=_recommend_payload(child_id))
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "fallback"
    assert any("兜底" in w for w in body.get("warnings", []))


def test_recommend_empty_wardrobe_400(client, db_session, monkeypatch):
    from app.models import Clothing
    db_session.query(Clothing).delete()
    db_session.commit()
    child_id = client.seed["child_id"]
    resp = client.post("/outfits/recommend", json=_recommend_payload(child_id))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "衣橱暂无可推荐衣物"


def test_recommend_cache_hit_returns_same(client, monkeypatch):
    # 第一次走兜底并写缓存，第二次应命中缓存（不再调用 AI）
    calls = {"n": 0}

    async def _counting_ai(*args, **kwargs):
        calls["n"] += 1
        return None
    monkeypatch.setattr("app.routers.outfits.call_ai_recommend", _counting_ai)
    monkeypatch.setattr("app.routers.outfits.settings.dev_outfit_mock", False)

    child_id = client.seed["child_id"]
    first = client.post("/outfits/recommend", json=_recommend_payload(child_id))
    second = client.post("/outfits/recommend", json=_recommend_payload(child_id))
    assert first.status_code == second.status_code == 200
    # 第二次命中缓存 → AI 调用次数不增加
    assert calls["n"] == 1
```

- [ ] **Step 4: 跑路由测试**

Run: `pytest tests/test_outfit_route.py -v`
Expected: PASS。`_recommend_payload` 的字段须匹配 `OutfitRecommendIn` schema——若字段名/必填项不同，按 `app/schemas.py` 实际定义调整。先看 schema：`grep -n -A15 'class OutfitRecommendIn' app/schemas.py`。

- [ ] **Step 5: 跑全量测试确认绿色基线**

Run: `pytest -v`
Expected: 全绿。**这是重构前的基线，必须全绿才能进入 Task 5。**

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_outfit_scoring.py backend/tests/test_outfit_route.py
git commit -m "test: 搭配推荐特征测试（评分 + recommend 三路径）"
```

---

## Task 5: 抽取 domain/vocab.py 与 deps.py（最低风险首迁）

**Files:**
- Create: `backend/app/domain/__init__.py`
- Create: `backend/app/domain/vocab.py`
- Create: `backend/app/deps.py`
- Modify: `backend/app/routers/clothing.py`
- Modify: `backend/app/routers/outfits.py`

- [ ] **Step 1: 建 domain/vocab.py，迁入词表常量**

Create `backend/app/domain/__init__.py`（空文件）。

把 `clothing.py:34-69` 的常量（`CLOTHING_TYPES`、`CLOTHING_SUB_TYPES`、`COLORS`、
`PATTERNS`、`SEASONS`、`THICKNESS`、`STYLE_TAGS`、`RECOGNITION_FIELD_SCORE_META`）
**逐字剪切**到 `backend/app/domain/vocab.py`，以及 `clothing.py:343-444` 的别名映射
（`_TYPE_ALIAS`、`_COLOR_ALIAS`、`_PATTERN_ALIAS`、`_THICKNESS_ALIAS`、`_SEASON_ALIAS`、
`_STYLE_ALIAS`）。

在 `clothing.py` 顶部加：
```python
from ..domain.vocab import (
    CLOTHING_TYPES, CLOTHING_SUB_TYPES, COLORS, PATTERNS, SEASONS, THICKNESS,
    STYLE_TAGS, RECOGNITION_FIELD_SCORE_META,
    _TYPE_ALIAS, _COLOR_ALIAS, _PATTERN_ALIAS, _THICKNESS_ALIAS,
    _SEASON_ALIAS, _STYLE_ALIAS,
)
```

- [ ] **Step 2: 建 deps.py，去重 ownership 助手**

Create `backend/app/deps.py`，迁入 `ensure_child_owned` 与 `get_owned_clothing`
（取 `clothing.py:71-86` 的版本，确认与 `outfits.py:71-76` 的 `ensure_child_owned` 一致）：
```python
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
```

在 `clothing.py` 删除原两个函数定义，改为 `from ..deps import ensure_child_owned, get_owned_clothing`。
在 `outfits.py` 删除其 `ensure_child_owned`（`outfits.py:71-76`），改为
`from ..deps import ensure_child_owned`。

> 注意：测试 Task 3 从 `app.routers.clothing` import `_normalize_recognition` 等——
> 这些仍在 clothing.py，未受影响。但若测试 import 了已迁出的别名映射，需同步更新 import 路径。

- [ ] **Step 3: 跑全量测试**

Run: `pytest -v`
Expected: 全绿。若报 `ImportError`，多为别名映射或常量遗漏/重复定义——核对 vocab.py 与 clothing.py 无重复定义、无遗漏。

- [ ] **Step 4: 应用可启动检查**

Run: `python -c "from app.main import app; print('ok')"`
Expected: 输出 `ok`，无 import 错误。

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/ backend/app/deps.py backend/app/routers/clothing.py backend/app/routers/outfits.py
git commit -m "refactor: 抽取 domain/vocab 与 deps，去重 ownership 助手"
```

---

## Task 6: 抽取图片服务

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/images/__init__.py`
- Create: `backend/app/services/images/urls.py`
- Create: `backend/app/services/images/storage.py`
- Modify: `backend/app/routers/clothing.py`

- [ ] **Step 1: 迁 URL 助手到 urls.py**

Create `backend/app/services/__init__.py` 与 `backend/app/services/images/__init__.py`（空文件）。

把 `clothing.py` 中 `_is_local_url`、`_public_image_url`、`_local_upload_path`、
`_image_data_url`、`_ark_image_url_or_data_url`（行 103-158）**逐字剪切**到
`backend/app/services/images/urls.py`。这些函数引用 `settings`、`logger`、`HTTPException`、
`status`、`urlparse`、`mimetypes`、`base64`、`Path`——在新文件补齐对应 import：
```python
import base64
import logging
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException, status

from ...config import settings

logger = logging.getLogger(__name__)
```

- [ ] **Step 2: 迁存储助手到 storage.py**

把 `_cos_upload`、`_local_persist`、`_persist_image`、`_build_filename`
（`clothing.py:835-898`）逐字剪切到 `backend/app/services/images/storage.py`，补齐 import：
```python
import logging
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, status

from ...config import settings

logger = logging.getLogger(__name__)
```

- [ ] **Step 3: clothing.py 改为 import 这些函数**

在 `clothing.py` 顶部加：
```python
from ..services.images.urls import (
    _ark_image_url_or_data_url, _image_data_url, _local_upload_path,
    _public_image_url, _is_local_url,
)
from ..services.images.storage import (
    _build_filename, _cos_upload, _local_persist, _persist_image,
)
```
删除 clothing.py 中这些函数的原定义。清理 clothing.py 顶部因迁移而不再使用的 import（如 `base64`、`mimetypes`、`BytesIO`、`uuid4`、`urlparse`——仅删确实不再使用的）。

- [ ] **Step 4: 跑全量测试**

Run: `pytest -v`
Expected: 全绿。`test_recognition_route` 里 monkeypatch 了 `app.routers.clothing._ark_image_url_or_data_url`——因为 clothing.py 仍 `import` 该名进自身命名空间，patch 目标路径不变，应仍有效。

- [ ] **Step 5: 启动检查 + Commit**

```bash
python -c "from app.main import app; print('ok')"
git add backend/app/services/ backend/app/routers/clothing.py
git commit -m "refactor: 抽取图片服务（urls + storage）"
```

---

## Task 7: 抽取识别服务

**Files:**
- Create: `backend/app/services/recognition/__init__.py`
- Create: `backend/app/services/recognition/parsing.py`
- Create: `backend/app/services/recognition/normalize.py`
- Create: `backend/app/services/recognition/prompt.py`
- Create: `backend/app/services/recognition/ark_client.py`
- Modify: `backend/app/routers/clothing.py`
- Modify: `backend/tests/test_recognition_parsing.py`

- [ ] **Step 1: 迁解析器到 parsing.py**

Create `backend/app/services/recognition/__init__.py`（空）。

把 `_extract_json`、`_extract_ark_text`、`_pick_recognition_object`
（`clothing.py:175-340`）逐字剪切到 `parsing.py`，补 import：
```python
import json
import logging
from typing import Any, Union

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)
```

- [ ] **Step 2: 迁 normalize 与 prompt**

把 `_normalize_recognition`（`clothing.py:447` 起至其结束）剪切到 `normalize.py`，
它依赖别名映射与词表（已在 `domain/vocab.py`）和 `ClothingRecognizeOut`：
```python
from typing import Any

from ...domain.vocab import (
    CLOTHING_TYPES, CLOTHING_SUB_TYPES, COLORS, PATTERNS, SEASONS, THICKNESS,
    STYLE_TAGS, _TYPE_ALIAS, _COLOR_ALIAS, _PATTERN_ALIAS, _THICKNESS_ALIAS,
    _SEASON_ALIAS, _STYLE_ALIAS,
)
from ...schemas import ClothingRecognizeOut
```
把 `_mock_recognition`（`clothing.py:89-100`）也迁到 `normalize.py`（同样依赖 schema）。
把 `_recognition_prompt`（行 582-704）剪切到 `prompt.py`。

- [ ] **Step 3: 迁 ARK 调用到 ark_client.py**

把 `_compact_ark_request`（`clothing.py:161-172`）剪切到 `ark_client.py`。
recognize 路由里的 httpx 调用逻辑保留在路由内（路由仍是 async 端点），但 `_compact_ark_request` 从此模块 import。补 import：
```python
import json
from typing import Any
```

- [ ] **Step 4: clothing.py 改 import 并精简**

在 clothing.py 顶部加：
```python
from ..services.recognition.parsing import (
    _extract_json, _extract_ark_text, _pick_recognition_object,
)
from ..services.recognition.normalize import _normalize_recognition, _mock_recognition
from ..services.recognition.prompt import _recognition_prompt
from ..services.recognition.ark_client import _compact_ark_request
```
删除 clothing.py 中这些函数原定义及不再使用的 import。

- [ ] **Step 5: 更新解析器测试的 import 路径**

Modify `backend/tests/test_recognition_parsing.py` 顶部 import 改为：
```python
from app.services.recognition.parsing import _extract_json, _pick_recognition_object
from app.services.recognition.normalize import _normalize_recognition
```
`test_recognition_route.py` 中 monkeypatch 的 `app.routers.clothing._ark_image_url_or_data_url`
保持不变（clothing.py 仍 import 该名）。

- [ ] **Step 6: 跑全量测试 + 启动检查**

Run: `pytest -v` → 全绿。
Run: `python -c "from app.main import app; print('ok')"` → `ok`。

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/recognition/ backend/app/routers/clothing.py backend/tests/test_recognition_parsing.py
git commit -m "refactor: 抽取识别服务（parsing/normalize/prompt/ark_client）"
```

---

## Task 8: 抽取搭配服务（最大一步，逐子模块进行）

**Files:**
- Create: `backend/app/services/outfits/__init__.py`
- Create: `backend/app/services/outfits/profile.py`
- Create: `backend/app/services/outfits/scoring.py`
- Create: `backend/app/services/outfits/fallback.py`
- Create: `backend/app/services/outfits/ai_build.py`
- Create: `backend/app/services/outfits/ai_client.py`
- Create: `backend/app/services/outfits/cache.py`
- Modify: `backend/app/routers/outfits.py`
- Modify: `backend/tests/test_outfit_scoring.py`、`backend/tests/test_outfit_route.py`

> **逐子模块迁移：每抽一个文件就跑一次 `pytest -v`，绿了再抽下一个。** 不要一次性全搬。

- [ ] **Step 1: 抽 cache.py（依赖最少）**

Create `backend/app/services/outfits/__init__.py`（空）。
把 `build_cache_signature`、`upsert_recommendation_cache`、`outfit_to_cache`、
`cache_to_outfit`、`clothing_fingerprint`、`compact_clothing`（`outfits.py` 中对应函数）
剪切到 `cache.py`，补齐它们用到的 import（`date`、`json`、`hashlib`/`select`、
`OutfitRecommendation` 模型、相关 schema）。在 outfits.py 顶部 import 回来。

Run: `pytest -v` → 全绿。

- [ ] **Step 2: 抽 profile.py**

把 `choose_style_profile` 及 `_profile_scores_from_user_tags`、
`_profile_scores_from_wardrobe`、`_profile_scores_from_feedback`、
`_profile_scores_from_scene_and_meta`（`outfits.py:111-308`）剪切到 `profile.py`，
补 import。outfits.py import 回 `choose_style_profile`（及路由直接用到的）。

Run: `pytest -v` → 全绿。

- [ ] **Step 3: 抽 scoring.py**

把 `score_item`、`pick_best`、`enrich_reason`、`recent_clothing_counts`、
`child_age_months`、`current_season`、`recommended_thickness`（`outfits.py:78-110` 与
331-417 区间对应函数）剪切到 `scoring.py`，补 import。outfits.py import 回来。

Run: `pytest -v` → 全绿。

- [ ] **Step 4: 抽 fallback.py**

把 `build_fallback_outfit`（`outfits.py:418-512`）剪切到 `fallback.py`。它依赖 scoring/
profile 的函数——从 `.scoring` / `.profile` import。outfits.py import 回 `build_fallback_outfit`。

Run: `pytest -v` → 全绿。

- [ ] **Step 5: 抽 ai_build.py 与 ai_client.py**

把 `extract_json`、`build_ai_outfit`（`outfits.py:513-895` 区间对应函数）剪切到
`ai_build.py`；把 `call_ai_recommend`、`compact_gptsapi_request` 剪切到 `ai_client.py`。
补齐 httpx / settings / schema 等 import。outfits.py import 回
`call_ai_recommend`、`build_ai_outfit`。

Run: `pytest -v` → 全绿。

- [ ] **Step 6: 更新搭配测试 import 路径**

Modify `test_outfit_scoring.py`：
```python
from app.services.outfits.scoring import (
    child_age_months, current_season, recommended_thickness,
)
```
`test_outfit_route.py` 中 monkeypatch 的 `app.routers.outfits.call_ai_recommend` 保持不变
（outfits.py 仍 import 该名进自身命名空间，patch 路径有效）。

Run: `pytest -v` → 全绿。

- [ ] **Step 7: 启动检查 + Commit**

```bash
python -c "from app.main import app; print('ok')"
git add backend/app/services/outfits/ backend/app/routers/outfits.py backend/tests/
git commit -m "refactor: 抽取搭配服务（profile/scoring/fallback/ai_build/ai_client/cache）"
```

---

## Task 9: 收尾验证（路由变薄）

**Files:**
- Modify: `backend/app/routers/clothing.py`、`backend/app/routers/outfits.py`（仅清理）

- [ ] **Step 1: 核对行数下降**

Run: `wc -l backend/app/routers/clothing.py backend/app/routers/outfits.py`
Expected: 两个文件应显著缩短（路由 + import + 编排为主，目标各 < 300 行）。

- [ ] **Step 2: 清理残留 import 与死代码**

逐一检查两个路由文件顶部 import，删除迁移后不再使用的（如 `base64`、`mimetypes`、
`httpx` 若已移走、`hashlib` 等）。确认无函数定义残留——路由文件应只含 `router = APIRouter(...)`、
端点函数、必要 import。

Run: `python -W error -c "from app.main import app; print('ok')"`
Expected: `ok`，无未使用 import 引发的问题。（如装有 ruff：`ruff check app/routers/` 应无 F401。）

- [ ] **Step 3: 全量测试 + 启动最终确认**

Run: `pytest -v`
Expected: 全绿（与 Task 4 基线同样的用例集，行为未变）。

Run: `python -c "from app.main import app; print(len(app.routes), 'routes')"`
Expected: 路由数量与重构前一致。

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/clothing.py backend/app/routers/outfits.py
git commit -m "refactor: 路由文件收尾清理，去除残留 import"
```

---

## 完成标准

- `clothing.py` / `outfits.py` 变薄，逻辑迁入 `services/` 与 `domain/`，`ensure_child_owned` 去重至 `deps.py`。
- 对外路由、schema、状态码零变更。
- 高风险路径（CRUD / 识别解析 / 推荐三路径）有特征测试覆盖，`pytest -v` 全绿。
- 每步迁移均为"移动 + 重 import"，无函数体重写。
- 性能优化（Phase 2）与 AI 质量（Phase 3）留待独立 spec。
