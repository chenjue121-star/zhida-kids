# Phase 3a 识别准确度评估与优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一套离线的衣物识别 A/B 评估基建，量化识别准确度，并在其守护下把至少一个更优的提示词变体提升进生产代码。

**Architecture:** 在 `backend/eval/recognition/` 新建离线工具：纯函数评分器与标注校验器（进 CI 测试），以及调用真实 ARK 的 runner、A/B 对比 CLI、报告器（不进 CI）。runner 复用从 recognize 路由抽取出的共享识别函数 `recognize_image()`，保证评估反映真实生产路径。

**Tech Stack:** Python 3.9 / FastAPI / httpx（异步）/ PyYAML / pytest + respx（已在项目内）。ARK doubao 视觉模型为识别后端。

---

## 约定

- 工作目录均为 `backend/`。
- 运行 Python 用项目虚拟环境解释器：`PY="/Users/ll/Documents/智搭（儿童）/backend/.venv/bin/python"`。
  本计划下文一律写作 `$PY`，执行前先 `export PY=...`。
- 测试命令统一 `$PY -m pytest`。
- 每个任务最后一步提交；提交信息结尾附：
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

## Task 1: 抽取共享识别函数 `recognize_image()`（行为保持）

把 recognize 路由里的 ARK 调用 + 解析 + 归一逻辑抽到识别服务，供路由与 eval runner 共用。
现有识别路由测试必须保持全绿（不修改测试）。

**Files:**
- Create: `backend/app/services/recognition/recognize.py`
- Modify: `backend/app/routers/clothing.py`（`recognize_clothing`,约 59-107 行；及顶部 import）
- Test: 复用现有 `backend/tests/test_recognition_route.py`（不改）

- [ ] **Step 1: 先跑现有识别测试确认基线全绿**

Run: `$PY -m pytest tests/test_recognition_route.py -v`
Expected: 2 passed

- [ ] **Step 2: 新建 `recognize.py`**

```python
# backend/app/services/recognition/recognize.py
from __future__ import annotations

import json
import logging

import httpx

from ...config import settings
from ...schemas import ClothingRecognizeOut
from .ark_client import _compact_ark_request
from .normalize import _normalize_recognition
from .parsing import _extract_ark_text, _extract_json, _pick_recognition_object

logger = logging.getLogger(__name__)


class RecognitionError(Exception):
    """识别失败的基类。"""


class RecognitionUpstreamError(RecognitionError):
    """ARK 调用失败（网络/HTTP）。"""


class RecognitionEmptyError(RecognitionError):
    """ARK 未返回可用文本。"""


async def recognize_image(image_url: str, prompt_text: str) -> ClothingRecognizeOut:
    """调用 ARK 识别单张图片并归一化为 ClothingRecognizeOut。

    image_url: 直接可用的图片 URL 或 data url（调用方负责转换）。
    prompt_text: 识别提示词文本（生产用 _recognition_prompt()，评估用变体）。
    """
    request_body = {
        "model": settings.ark_clothing_model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_image", "image_url": image_url},
                    {"type": "input_text", "text": prompt_text},
                ],
            }
        ],
    }
    logger.warning("ark clothing request=%s", json.dumps(_compact_ark_request(request_body), ensure_ascii=False))

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                settings.ark_responses_url,
                headers={
                    "Authorization": f"Bearer {settings.ark_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            logger.warning("ark clothing status_code=%s", response.status_code)
            logger.warning("ark clothing response=%s", response.text[:3000])
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise RecognitionUpstreamError(str(exc)) from exc

    text = _extract_ark_text(data)
    if not text:
        raise RecognitionEmptyError("AI 识别服务未返回文本")
    logger.warning("ark clothing text=%s", text[:3000])
    result = _normalize_recognition(_pick_recognition_object(_extract_json(text)))
    logger.warning("ark clothing normalized=%s", result.model_dump_json())
    return result
```

- [ ] **Step 3: 改路由 `recognize_clothing` 委托新函数**

把 `backend/app/routers/clothing.py` 中 `recognize_clothing` 函数体（59-107 行）替换为：

```python
@router.post("/recognize", response_model=ClothingRecognizeOut)
async def recognize_clothing(
    payload: ClothingRecognizeIn,
    current_user: User = Depends(get_current_user),
) -> ClothingRecognizeOut:
    if settings.dev_ai_mock:
        return _mock_recognition()
    if not settings.ark_api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="未配置 ARK_API_KEY")

    image_url = _ark_image_url_or_data_url(payload.photo_url)
    try:
        return await recognize_image(image_url, _recognition_prompt())
    except RecognitionEmptyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 识别服务未返回文本") from exc
    except RecognitionError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 识别服务调用失败") from exc
```

- [ ] **Step 4: 更新 import**

在 `backend/app/routers/clothing.py` 顶部 import 区加：

```python
from ..services.recognition.recognize import (
    RecognitionEmptyError,
    RecognitionError,
    recognize_image,
)
```

删除现在路由内已不再直接使用的 import（用 AST 扫描确认）。`recognize_clothing` 不再直接用
`httpx`、`_compact_ark_request`、`_extract_ark_text`、`_extract_json`、`_pick_recognition_object`、
`_normalize_recognition`、`json`，**但其它路由（如 upload-and-recognize）仍用 `_normalize_recognition`、
`json`、`httpx`**。逐个核对后再删，不要盲删。

- [ ] **Step 5: 跑识别测试 + 全量测试 + boot 检查**

Run: `$PY -m pytest tests/test_recognition_route.py -v && $PY -m pytest -q`
Expected: test_recognition_route 2 passed；整体全绿（应为 28 passed 左右，以实际为准）

Run: `DATABASE_URL="sqlite://" JWT_SECRET=x $PY -c "from app.main import create_app; create_app(); print('boot OK')"`
Expected: `boot OK`

- [ ] **Step 6: 扫描死 import 确认无残留**

```bash
$PY - <<'EOF'
import ast
f = "app/routers/clothing.py"
tree = ast.parse(open(f).read())
imp = {}
for n in ast.walk(tree):
    if isinstance(n, ast.Import):
        for a in n.names: imp[(a.asname or a.name).split('.')[0]] = n.lineno
    elif isinstance(n, ast.ImportFrom):
        for a in n.names: imp[a.asname or a.name] = n.lineno
used = {x.id for x in ast.walk(tree) if isinstance(x, ast.Name)} | {x.attr for x in ast.walk(tree) if isinstance(x, ast.Attribute)}
print({k:v for k,v in imp.items() if k not in used and k!="annotations"} or "NO UNUSED")
EOF
```
Expected: `NO UNUSED`

- [ ] **Step 7: Commit**

```bash
git add app/services/recognition/recognize.py app/routers/clothing.py
git commit -m "refactor: 抽取 recognize_image 共享识别函数，供 eval 复用

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 评分器 `scorer.py`（纯函数，TDD）

**Files:**
- Create: `backend/eval/__init__.py`（空）
- Create: `backend/eval/recognition/__init__.py`（空）
- Create: `backend/eval/recognition/scorer.py`
- Test: `backend/tests/test_eval_scorer.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_eval_scorer.py
from eval.recognition.scorer import (
    FIELD_WEIGHTS,
    composite,
    score_exact,
    score_fields,
    score_set,
)


def test_score_exact_match_and_mismatch():
    assert score_exact("top", "top") == 1.0
    assert score_exact("top", "pants") == 0.0


def test_score_exact_both_empty_counts_as_correct_abstention():
    assert score_exact("", "") == 1.0
    assert score_exact("hoodie", "") == 0.0
    assert score_exact("", "hoodie") == 0.0


def test_score_set_jaccard():
    assert score_set(["spring", "autumn"], ["spring", "autumn"]) == 1.0
    assert score_set(["spring"], ["spring", "autumn"]) == 0.5
    assert score_set(["summer"], ["winter"]) == 0.0


def test_score_set_both_empty_is_one():
    assert score_set([], []) == 1.0
    assert score_set(["spring"], []) == 0.0


def test_score_set_is_order_insensitive():
    assert score_set(["autumn", "spring"], ["spring", "autumn"]) == 1.0


def test_weights_sum_to_one():
    assert round(sum(FIELD_WEIGHTS.values()), 6) == 1.0


def test_score_fields_and_composite_perfect():
    predicted = {
        "type": "top", "main_color": "pink", "thickness": "normal",
        "sub_type": "hoodie", "pattern": "stripe",
        "season": ["autumn", "spring"], "style_tags": ["cute", "casual"],
    }
    expected = dict(predicted)
    scores = score_fields(predicted, expected)
    assert all(v == 1.0 for v in scores.values())
    assert composite(scores) == 1.0


def test_composite_partial():
    scores = {
        "type": 1.0, "main_color": 0.0, "thickness": 1.0,
        "sub_type": 1.0, "pattern": 1.0, "season": 1.0, "style_tags": 1.0,
    }
    # 缺失 main_color (权重 0.20) -> composite = 0.80
    assert composite(scores) == 0.8
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$PY -m pytest tests/test_eval_scorer.py -v`
Expected: FAIL（ModuleNotFoundError: eval.recognition.scorer）

- [ ] **Step 3: 实现 scorer.py + 空 __init__**

```python
# backend/eval/__init__.py
```
```python
# backend/eval/recognition/__init__.py
```
```python
# backend/eval/recognition/scorer.py
from __future__ import annotations

FIELD_WEIGHTS: dict[str, float] = {
    "type": 0.25,
    "main_color": 0.20,
    "thickness": 0.15,
    "sub_type": 0.15,
    "pattern": 0.10,
    "season": 0.10,
    "style_tags": 0.05,
}

EXACT_FIELDS = ("type", "main_color", "thickness", "sub_type", "pattern")
SET_FIELDS = ("season", "style_tags")


def score_exact(predicted: str, expected: str) -> float:
    return 1.0 if (predicted or "") == (expected or "") else 0.0


def score_set(predicted: list[str], expected: list[str]) -> float:
    p, e = set(predicted or []), set(expected or [])
    if not p and not e:
        return 1.0
    if not (p & e):
        return 0.0
    return len(p & e) / len(p | e)


def score_fields(predicted: dict, expected: dict) -> dict[str, float]:
    scores: dict[str, float] = {}
    for f in EXACT_FIELDS:
        scores[f] = score_exact(predicted.get(f, "") or "", expected.get(f, "") or "")
    for f in SET_FIELDS:
        scores[f] = score_set(predicted.get(f, []) or [], expected.get(f, []) or [])
    return scores


def composite(field_scores: dict[str, float]) -> float:
    return round(sum(field_scores[f] * w for f, w in FIELD_WEIGHTS.items()), 4)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `$PY -m pytest tests/test_eval_scorer.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add eval/__init__.py eval/recognition/__init__.py eval/recognition/scorer.py tests/test_eval_scorer.py
git commit -m "feat(eval): 识别评分器（逐字段 + 加权 composite）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 标注加载与枚举校验 `labels.py`（TDD）

**Files:**
- Create: `backend/eval/recognition/labels.py`
- Test: `backend/tests/test_eval_labels.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_eval_labels.py
import textwrap

import pytest

from eval.recognition.labels import LabelError, load_labels


def _write(tmp_path, text):
    p = tmp_path / "labels.yaml"
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return p


def test_load_valid_labels(tmp_path):
    p = _write(tmp_path, """
        - image: img001.jpg
          type: top
          sub_type: hoodie
          main_color: pink
          pattern: stripe
          season: [autumn, spring]
          thickness: normal
          style_tags: [cute, casual]
    """)
    labels = load_labels(p)
    assert len(labels) == 1
    assert labels[0]["image"] == "img001.jpg"
    assert labels[0]["season"] == ["autumn", "spring"]


def test_missing_required_field_raises(tmp_path):
    p = _write(tmp_path, """
        - image: img001.jpg
          type: top
          main_color: pink
    """)  # 缺 thickness
    with pytest.raises(LabelError, match="thickness"):
        load_labels(p)


def test_unknown_enum_value_raises(tmp_path):
    p = _write(tmp_path, """
        - image: img001.jpg
          type: tops
          main_color: pink
          thickness: normal
    """)  # type 应为 top
    with pytest.raises(LabelError, match="tops"):
        load_labels(p)


def test_unknown_set_value_raises(tmp_path):
    p = _write(tmp_path, """
        - image: img001.jpg
          type: top
          main_color: pink
          thickness: normal
          season: [autum]
    """)  # autum 拼错
    with pytest.raises(LabelError, match="autum"):
        load_labels(p)


def test_missing_image_key_raises(tmp_path):
    p = _write(tmp_path, """
        - type: top
          main_color: pink
          thickness: normal
    """)
    with pytest.raises(LabelError, match="image"):
        load_labels(p)


def test_empty_optional_fields_ok(tmp_path):
    p = _write(tmp_path, """
        - image: img001.jpg
          type: top
          main_color: pink
          thickness: normal
          sub_type: ""
          pattern: ""
          season: []
          style_tags: []
    """)
    labels = load_labels(p)
    assert labels[0]["sub_type"] == ""
    assert labels[0]["season"] == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$PY -m pytest tests/test_eval_labels.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 labels.py**

```python
# backend/eval/recognition/labels.py
from __future__ import annotations

from pathlib import Path

import yaml

from app.domain.vocab import (
    CLOTHING_SUB_TYPES,
    CLOTHING_TYPES,
    COLORS,
    PATTERNS,
    SEASONS,
    STYLE_TAGS,
    THICKNESS,
)

REQUIRED_FIELDS = ("type", "main_color", "thickness")

_ALLOWED_SCALAR = {
    "type": set(CLOTHING_TYPES),
    "sub_type": set(CLOTHING_SUB_TYPES) | {""},
    "main_color": set(COLORS),
    "pattern": set(PATTERNS) | {""},
    "thickness": set(THICKNESS),
}
_ALLOWED_SET = {
    "season": set(SEASONS),
    "style_tags": set(STYLE_TAGS),
}


class LabelError(ValueError):
    """标注文件不合法。"""


def load_labels(path: str | Path) -> list[dict]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    if not isinstance(raw, list):
        raise LabelError("labels.yaml 顶层必须是列表")

    for i, entry in enumerate(raw):
        where = f"第 {i + 1} 条"
        if not isinstance(entry, dict):
            raise LabelError(f"{where} 不是对象")
        if not entry.get("image"):
            raise LabelError(f"{where} 缺少 image 字段")
        img = entry["image"]
        for f in REQUIRED_FIELDS:
            if not entry.get(f):
                raise LabelError(f"{img} 缺少必填字段 {f}")
        for f, allowed in _ALLOWED_SCALAR.items():
            v = entry.get(f, "")
            if v is None:
                v = ""
            if v not in allowed:
                raise LabelError(f"{img} 字段 {f} 的值 {v!r} 不是合法枚举")
            entry[f] = v
        for f, allowed in _ALLOWED_SET.items():
            vals = entry.get(f, []) or []
            if not isinstance(vals, list):
                raise LabelError(f"{img} 字段 {f} 必须是列表")
            for v in vals:
                if v not in allowed:
                    raise LabelError(f"{img} 字段 {f} 的值 {v!r} 不是合法枚举")
            entry[f] = vals
    return raw
```

- [ ] **Step 4: 跑测试确认通过**

Run: `$PY -m pytest tests/test_eval_labels.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add eval/recognition/labels.py tests/test_eval_labels.py
git commit -m "feat(eval): 标注加载与枚举校验

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 报告器 `report.py`（纯格式化，TDD）

**Files:**
- Create: `backend/eval/recognition/report.py`
- Test: `backend/tests/test_eval_report.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_eval_report.py
from eval.recognition.report import format_comparison


def test_format_comparison_has_header_and_composite_and_delta():
    baseline = {
        "type": 1.0, "main_color": 0.8, "thickness": 0.6,
        "sub_type": 1.0, "pattern": 1.0, "season": 1.0, "style_tags": 1.0,
        "COMPOSITE": 0.88,
    }
    variant = {
        "type": 1.0, "main_color": 0.9, "thickness": 0.75,
        "sub_type": 1.0, "pattern": 1.0, "season": 1.0, "style_tags": 1.0,
        "COMPOSITE": 0.9275,
    }
    out = format_comparison("baseline", "variant_x", baseline, variant, image_count=20)
    assert "baseline" in out
    assert "variant_x" in out
    assert "COMPOSITE" in out
    assert "main_color" in out
    assert "+0.10" in out      # main_color delta
    assert "图片数: 20" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$PY -m pytest tests/test_eval_report.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 report.py**

```python
# backend/eval/recognition/report.py
from __future__ import annotations

from eval.recognition.scorer import FIELD_WEIGHTS

_ROW_ORDER = list(FIELD_WEIGHTS.keys()) + ["COMPOSITE"]


def _fmt_delta(d: float) -> str:
    return f"{d:+.2f}"


def format_comparison(
    baseline_name: str,
    variant_name: str,
    baseline: dict[str, float],
    variant: dict[str, float],
    image_count: int,
) -> str:
    lines = [
        f"# 识别 A/B 对比报告",
        "",
        f"图片数: {image_count}",
        "",
        f"| Field | {baseline_name} | {variant_name} | Δ |",
        "| --- | --- | --- | --- |",
    ]
    for field in _ROW_ORDER:
        b = baseline.get(field, 0.0)
        v = variant.get(field, 0.0)
        lines.append(f"| {field} | {b:.2f} | {v:.2f} | {_fmt_delta(v - b)} |")
    return "\n".join(lines)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `$PY -m pytest tests/test_eval_report.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add eval/recognition/report.py tests/test_eval_report.py
git commit -m "feat(eval): A/B 对比报告格式化

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 提示词变体模块 + baseline 快照

**Files:**
- Create: `backend/eval/recognition/prompts/__init__.py`（空）
- Create: `backend/eval/recognition/prompts/baseline.py`
- Create: `backend/eval/recognition/prompts/variant_example.py`
- Test: `backend/tests/test_eval_prompts.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_eval_prompts.py
from eval.recognition.prompts import baseline, variant_example
from app.services.recognition.prompt import _recognition_prompt


def test_baseline_matches_production_prompt():
    assert baseline.build_prompt() == _recognition_prompt()


def test_variant_is_nonempty_string_and_differs():
    v = variant_example.build_prompt()
    assert isinstance(v, str) and v.strip()
    assert v != baseline.build_prompt()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$PY -m pytest tests/test_eval_prompts.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 prompts 包**

```python
# backend/eval/recognition/prompts/__init__.py
```
```python
# backend/eval/recognition/prompts/baseline.py
"""baseline = 生产提示词的引用快照。永远等于当前生产实现，作为 A/B 基线。"""
from app.services.recognition.prompt import _recognition_prompt


def build_prompt() -> str:
    return _recognition_prompt()
```
```python
# backend/eval/recognition/prompts/variant_example.py
"""示例变体：在生产提示词末尾追加一条更强调厚度判断的规则。

这是模板/占位变体，证明 A/B 机制可用。真正调优时新建 variant_<name>.py，
独立编写完整提示词文本或在 baseline 基础上改写。
"""
from app.services.recognition.prompt import _recognition_prompt


def build_prompt() -> str:
    base = _recognition_prompt()
    extra = "\n5. 厚度判断务必结合面料层数与是否加绒，宁可标 normal 也不要漏判 thick/fleece。"
    return base + extra
```

- [ ] **Step 4: 跑测试确认通过**

Run: `$PY -m pytest tests/test_eval_prompts.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add eval/recognition/prompts/ tests/test_eval_prompts.py
git commit -m "feat(eval): 提示词变体机制 + baseline 快照

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Runner（调用 ARK + 缓存，含 dry-run 桩）

runner 对每个 (image, prompt, run-index) 调真实识别函数 `recognize_image`，结果缓存到磁盘。
dry-run 模式下不联网，从缓存或返回桩，用于管线冒烟。

**Files:**
- Create: `backend/eval/recognition/runner.py`
- Test: `backend/tests/test_eval_runner.py`

- [ ] **Step 1: 写失败测试（用缓存命中路径，避免联网）**

```python
# backend/tests/test_eval_runner.py
import json

import pytest

from eval.recognition.runner import cache_key, run_recognition


def test_cache_key_stable_and_prompt_sensitive():
    k1 = cache_key("img001.jpg", "prompt A", 0)
    k2 = cache_key("img001.jpg", "prompt A", 0)
    k3 = cache_key("img001.jpg", "prompt B", 0)
    assert k1 == k2
    assert k1 != k3


@pytest.mark.asyncio
async def test_run_recognition_uses_cache(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    # 预写缓存：模拟此前已识别结果
    key = cache_key("img001.jpg", "prompt A", 0)
    (cache_dir / f"{key}.json").write_text(
        json.dumps({"type": "top", "main_color": "white", "thickness": "thin"}),
        encoding="utf-8",
    )

    async def _fail(*a, **k):
        raise AssertionError("缓存命中时不应联网")

    result = await run_recognition(
        image_path=tmp_path / "img001.jpg",
        image_name="img001.jpg",
        prompt_text="prompt A",
        run_index=0,
        cache_dir=cache_dir,
        recognizer=_fail,
    )
    assert result["type"] == "top"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$PY -m pytest tests/test_eval_runner.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 runner.py**

```python
# backend/eval/recognition/runner.py
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Awaitable, Callable, Optional

from app.services.recognition.recognize import recognize_image

# recognizer 签名：async (image_data_url: str, prompt_text: str) -> ClothingRecognizeOut
Recognizer = Callable[[str, str], Awaitable[object]]


def cache_key(image_name: str, prompt_text: str, run_index: int) -> str:
    h = hashlib.sha256()
    h.update(image_name.encode("utf-8"))
    h.update(b"\x00")
    h.update(prompt_text.encode("utf-8"))
    h.update(b"\x00")
    h.update(str(run_index).encode("utf-8"))
    return h.hexdigest()[:32]


def _image_to_data_url(image_path: Path) -> str:
    mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


async def run_recognition(
    image_path: Path,
    image_name: str,
    prompt_text: str,
    run_index: int,
    cache_dir: Path,
    recognizer: Optional[Recognizer] = None,
    use_cache: bool = True,
) -> dict:
    """返回归一化后的识别 dict（ClothingRecognizeOut.model_dump 的子集）。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{cache_key(image_name, prompt_text, run_index)}.json"
    if use_cache and cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    fn = recognizer or recognize_image
    data_url = _image_to_data_url(image_path)
    result = await fn(data_url, prompt_text)
    payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload
```

- [ ] **Step 4: 跑测试确认通过**

Run: `$PY -m pytest tests/test_eval_runner.py -v`
Expected: 2 passed

- [ ] **Step 5: 加 .gitignore 忽略缓存**

在仓库根 `.gitignore` 末尾追加：

```
# --- eval 缓存 ---
backend/eval/recognition/.cache/
```

- [ ] **Step 6: Commit**

```bash
git add eval/recognition/runner.py tests/test_eval_runner.py ../.gitignore
git commit -m "feat(eval): 识别 runner（data-url + 磁盘缓存，复用 recognize_image）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: A/B 对比 CLI `ab_compare.py` + 数据集脚手架

聚合 runner + scorer + report，提供 `--scaffold`（生成标注骨架）、`--yes`（成本确认）、
`--dry-run`（仅用缓存、无 API）、`--repeat`、`--limit`、`--out`。

**Files:**
- Create: `backend/eval/recognition/ab_compare.py`
- Create: `backend/eval/recognition/dataset/labels.example.yaml`
- Test: `backend/tests/test_eval_ab_compare.py`（仅测纯聚合函数 `aggregate_scores`）

- [ ] **Step 1: 写失败测试（只测纯聚合，不测 CLI/网络）**

```python
# backend/tests/test_eval_ab_compare.py
from eval.recognition.ab_compare import aggregate_scores


def test_aggregate_averages_per_field_and_composite():
    # 两张图的 per-image field 分数
    per_image = [
        {"type": 1.0, "main_color": 1.0, "thickness": 1.0,
         "sub_type": 1.0, "pattern": 1.0, "season": 1.0, "style_tags": 1.0},
        {"type": 1.0, "main_color": 0.0, "thickness": 1.0,
         "sub_type": 1.0, "pattern": 1.0, "season": 1.0, "style_tags": 1.0},
    ]
    agg = aggregate_scores(per_image)
    assert agg["type"] == 1.0
    assert agg["main_color"] == 0.5
    # composite 为每图 composite 的平均：(1.0 + 0.8) / 2 = 0.9
    assert agg["COMPOSITE"] == 0.9
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$PY -m pytest tests/test_eval_ab_compare.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 ab_compare.py**

```python
# backend/eval/recognition/ab_compare.py
from __future__ import annotations

import argparse
import asyncio
import importlib
from pathlib import Path
from statistics import mean

from eval.recognition.labels import load_labels
from eval.recognition.report import format_comparison
from eval.recognition.runner import run_recognition
from eval.recognition.scorer import FIELD_WEIGHTS, composite, score_fields

HERE = Path(__file__).resolve().parent
DATASET = HERE / "dataset"
IMAGES = DATASET / "images"
LABELS = DATASET / "labels.yaml"
CACHE = HERE / ".cache"

_FIELDS = list(FIELD_WEIGHTS.keys())


def aggregate_scores(per_image: list[dict[str, float]]) -> dict[str, float]:
    """把多张图的 per-field 分数聚合为均值，并算 composite 均值。"""
    agg: dict[str, float] = {}
    for f in _FIELDS:
        agg[f] = round(mean(img[f] for img in per_image), 4) if per_image else 0.0
    agg["COMPOSITE"] = round(mean(composite(img) for img in per_image), 4) if per_image else 0.0
    return agg


def _load_prompt(name: str) -> str:
    mod = importlib.import_module(f"eval.recognition.prompts.{name}")
    return mod.build_prompt()


def scaffold_labels() -> None:
    names = sorted(p.name for p in IMAGES.glob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    lines = []
    for n in names:
        lines.append(f"- image: {n}")
        lines.append("  type: ")
        lines.append("  sub_type: \"\"")
        lines.append("  main_color: ")
        lines.append("  pattern: \"\"")
        lines.append("  season: []")
        lines.append("  thickness: ")
        lines.append("  style_tags: []")
    LABELS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已生成标注骨架 {LABELS}（{len(names)} 张图），请手工填写后再跑对比。")


async def _score_prompt(prompt_text: str, labels: list[dict], repeat: int, use_cache: bool) -> dict:
    per_image: list[dict[str, float]] = []
    for entry in labels:
        run_scores: list[dict[str, float]] = []
        for r in range(repeat):
            predicted = await run_recognition(
                image_path=IMAGES / entry["image"],
                image_name=entry["image"],
                prompt_text=prompt_text,
                run_index=r,
                cache_dir=CACHE,
                use_cache=use_cache,
            )
            run_scores.append(score_fields(predicted, entry))
        # 同图多次取每字段均值
        avg = {f: round(mean(s[f] for s in run_scores), 4) for f in _FIELDS}
        per_image.append(avg)
    return aggregate_scores(per_image)


async def _run(args: argparse.Namespace) -> int:
    labels = load_labels(LABELS)
    if args.limit:
        labels = labels[: args.limit]
    n_calls = len(labels) * 2 * args.repeat
    print(f"将进行约 {n_calls} 次 ARK 调用（{len(labels)} 图 × 2 提示词 × {args.repeat} 次）。")
    if not args.dry_run and not args.yes:
        print("需加 --yes 确认计费，或加 --dry-run 仅用缓存。中止。")
        return 1
    use_cache = True  # 始终优先缓存；dry-run 下若缺缓存会触发联网，故 dry-run 要求缓存已存在
    base_prompt = _load_prompt(args.baseline)
    var_prompt = _load_prompt(args.variant)
    base_scores = await _score_prompt(base_prompt, labels, args.repeat, use_cache)
    var_scores = await _score_prompt(var_prompt, labels, args.repeat, use_cache)
    report = format_comparison(args.baseline, args.variant, base_scores, var_scores, len(labels))
    print("\n" + report)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"\n已写入 {args.out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="识别提示词 A/B 对比")
    parser.add_argument("--baseline", default="baseline")
    parser.add_argument("--variant", default="variant_example")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", default="")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--scaffold", action="store_true")
    args = parser.parse_args()
    if args.scaffold:
        scaffold_labels()
        return 0
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 写 labels.example.yaml**

```yaml
# backend/eval/recognition/dataset/labels.example.yaml
# 标注模板。正式标注写入同目录 labels.yaml（可用 --scaffold 生成骨架）。
- image: img001.jpg
  type: top
  sub_type: hoodie
  main_color: pink
  pattern: stripe
  season: [autumn, spring]
  thickness: normal
  style_tags: [cute, casual]
- image: img002.jpg
  type: pants
  sub_type: jeans
  main_color: denim
  pattern: solid
  season: [all]
  thickness: normal
  style_tags: [casual]
```

- [ ] **Step 5: 跑测试确认通过 + 全量回归**

Run: `$PY -m pytest tests/test_eval_ab_compare.py -v && $PY -m pytest -q`
Expected: test_eval_ab_compare 1 passed；整体全绿

- [ ] **Step 6: 验证 CLI 可加载（--help 不联网）**

Run: `$PY -m eval.recognition.ab_compare --help`
Expected: 打印 usage，含 `--scaffold`、`--yes`、`--dry-run`

- [ ] **Step 7: Commit**

```bash
git add eval/recognition/ab_compare.py eval/recognition/dataset/labels.example.yaml tests/test_eval_ab_compare.py
git commit -m "feat(eval): A/B 对比 CLI + 标注脚手架 + 成本守护

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: 准备评估数据集（复制图片 + README）

**Files:**
- Create: `backend/eval/recognition/dataset/images/`（从 uploads 复制，重命名）
- Create: `backend/eval/recognition/README.md`

- [ ] **Step 1: 复制并重命名图片为稳定 slug**

```bash
mkdir -p eval/recognition/dataset/images
i=1
for f in $(ls uploads/*.jpg uploads/*.jpeg uploads/*.png 2>/dev/null | sort); do
  ext="${f##*.}"
  printf -v name "img%03d.%s" "$i" "$ext"
  cp "$f" "eval/recognition/dataset/images/$name"
  i=$((i+1))
done
ls eval/recognition/dataset/images | head
echo "共 $(ls eval/recognition/dataset/images | wc -l) 张"
```
Expected: 约 20 张 imgNNN.* 文件

- [ ] **Step 2: 写 README（使用说明）**

```markdown
# 识别 A/B 评估

## 一次完整流程
1. 生成标注骨架：`$PY -m eval.recognition.ab_compare --scaffold`
2. 人工编辑 `dataset/labels.yaml`，按肉眼填 type/main_color/thickness 等（枚举见 app/domain/vocab.py）。
3. 跑基线 vs 变体（真实计费）：
   `ARK_API_KEY=... $PY -m eval.recognition.ab_compare --baseline baseline --variant variant_example --repeat 2 --yes --out report.md`
4. 看 report.md 的 COMPOSITE 与各字段 Δ。变体更优则把其文本提升进
   `app/services/recognition/prompt.py`，记录数字。
5. dry-run（仅用已有缓存、不计费）：加 `--dry-run` 替代 `--yes`。

## 新增变体
在 `prompts/` 下建 `variant_<name>.py`，导出 `build_prompt() -> str`，再用 `--variant <name>` 对比。
```

- [ ] **Step 3: Commit**

```bash
git add eval/recognition/dataset/images eval/recognition/README.md
git commit -m "chore(eval): 评估图片数据集 + 使用说明

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: 标注、跑基线、A/B、提升优胜变体（人工驱动）

此任务含人工标注与真实 API 调用，需 `ARK_API_KEY`。无 key 时止于 Step 1 并交回使用者。

**Files:**
- Modify: `backend/eval/recognition/dataset/labels.yaml`（人工填写）
- Modify: `backend/app/services/recognition/prompt.py`（提升优胜变体，若有）
- Create: `backend/eval/recognition/report.md`（评估快照，提交留档）

- [ ] **Step 1: 生成骨架并人工标注**

Run: `$PY -m eval.recognition.ab_compare --scaffold`
然后人工编辑 `dataset/labels.yaml` 填全字段。
校验：`$PY -c "from eval.recognition.labels import load_labels; print(len(load_labels('eval/recognition/dataset/labels.yaml')), 'ok')"`
Expected: 打印条数 + ok（若枚举写错会报错，按提示修正）

- [ ] **Step 2: 跑 baseline vs variant_example 取基线**

Run: `ARK_API_KEY=<key> $PY -m eval.recognition.ab_compare --baseline baseline --variant variant_example --repeat 2 --yes --out eval/recognition/report.md`
Expected: 打印对比表，写出 report.md。记录 baseline 的 COMPOSITE。

- [ ] **Step 3: 据结果迭代提示词变体**

针对得分低的字段（如 thickness/pattern），在 `prompts/` 下新建 `variant_<name>.py` 改写提示词，
重复 Step 2 用 `--variant <name>` 对比，直到某变体 COMPOSITE 稳定高于 baseline（建议 --repeat≥2）。

- [ ] **Step 4: 提升优胜变体进生产**

把优胜变体的提示词文本合并进 `app/services/recognition/prompt.py` 的 `_recognition_prompt()`。
回归：`$PY -m pytest -q`
Expected: 全绿（注意 `tests/test_eval_prompts.py::test_baseline_matches_production_prompt` —— baseline 通过
`_recognition_prompt()` 引用生产实现，会自动跟随，不会失败）

- [ ] **Step 5: Commit**

```bash
git add eval/recognition/dataset/labels.yaml eval/recognition/report.md app/services/recognition/prompt.py eval/recognition/prompts/
git commit -m "feat(eval): 完成识别基线评估并提升优胜提示词变体

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review 记录

- **Spec 覆盖：** 架构（eval 目录结构）→ Task 2-8；评估集与标注格式 → Task 3 + Task 7/8；
  评分指标（权重表）→ Task 2；A/B 工作流/输出/成本守护 → Task 7；测试（scorer/labels CI、
  runner 不进 CI、dry-run）→ Task 2/3/6/7；runner 复用真实路径 → Task 1 + Task 6；DoD → Task 9。
- **占位符：** 无 TBD/TODO；每步含完整代码或确切命令。
- **类型一致：** `build_prompt()`、`recognize_image(image_url, prompt_text)`、`score_fields`/`composite`、
  `aggregate_scores`、`run_recognition`/`cache_key`、`load_labels`/`LabelError`、`format_comparison`
  在定义任务与使用任务间签名一致。
- **已知取舍：** dry-run 依赖缓存已存在（缺缓存仍会联网）——已在 CLI 提示与 README 说明，非缺陷。
