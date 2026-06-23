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
