# 旧版单件识别 A/B 评估

此入口评估旧版 `ClothingRecognizeOut` 的单件字段，只识别图片中最显眼的一件衣物。
它不能评估新版多件候选、漏件、多报、框位置或新版枚举。新版评测请使用
[recognition_v2](../recognition_v2/README.md)，其中包含图片内容审计、人工审核标签和集合隔离检查。

从 `backend/` 执行以下命令，使用项目虚拟环境中的 `.venv/bin/python`。

1. 生成待填骨架：`.venv/bin/python -m eval.recognition.ab_compare --scaffold`。
   已有 `eval/recognition/dataset/labels.yaml` 会被保留；只有显式添加 `--overwrite` 才能覆盖。
2. 人工填写 `type` / `main_color` / `thickness` 等旧版字段。合法枚举见
   `app/domain/vocab.py`，格式见 `dataset/labels.example.yaml`。
3. 仅读取已有缓存：
   `.venv/bin/python -m eval.recognition.ab_compare --dry-run --repeat 1 --out report.md`。
   缺少任何所需缓存会非零退出，不输出部分评分报告，不发起模型调用。
   同时添加 `--yes` 仍保持离线。导入评测入口和读取缓存不会加载真实模型配置。
4. 获准真实调用后，显式使用 `--yes` 并提供旧版 ARK 所需配置：
   `.venv/bin/python -m eval.recognition.ab_compare --baseline baseline --variant variant_example --repeat 2 --yes --out report.md`。
   程序打印调用上限；缓存命中会减少真实调用，缺缓存会调用 ARK 并可能产生费用。

`--repeat` 必须为正整数，`--limit` 为非负整数，`0` 表示读取全部标签。

## 提示词与缓存

提示词变体位于 `prompts/variant_<name>.py`，导出 `build_prompt() -> str`，
通过 `--variant <name>` 选择。`baseline` 引用旧版生产提示词。

为兼容历史结果，缓存仍按图片文件名、提示词、重复编号保存在 `.cache/`。
这个旧缓存键不包含图片内容、供应商、模型或预处理版本；图片或模型配置变更后，
历史缓存不能作为新的评测证据。新版工具使用完整输入版本与内容哈希记录缓存身份。
