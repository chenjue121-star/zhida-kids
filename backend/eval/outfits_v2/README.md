# 衣物照片参与搭配的对照评测

2026-10-05。按用户对测试集的确认，推进“仅属性”与“属性＋照片”的整套选择对照。此工具独立于生产推荐，不修改真实衣橱、家庭偏好或数据库；默认离线。

## 本轮已准备的内容

- 原 47 张截图、75 个主商品对象全部冻结在 [确认记录](dataset/desktop-2026-10-05/confirmation.json) 与 [搭配库存](dataset/desktop-2026-10-05/garments.json)。原 AI 草稿和原图保持原样。
- 类别 null 3、图案 null 3、厚薄 null 75 均保留。转换到规则副本时，厚薄 null 显式变为 `unknown`；`ready/fit/年龄36月/拥有这些实物`均是模拟条件。
- 首轮选 16 张已检查的单件裁图：上衣6、下装2、外套1、裙5、连体2。先检查了18张；c005因模特下颌及内搭领口，c012因角落页面计数，退出首轮。其他多件图继续保留用于扩展，不算负例。
- 4 种偏好×3种天气上下文形成12个规则场景；其中未知/暖天给模型的输入相同，合并为8个不同输入组。两个AI臂首轮最多16次真实请求。它们仍来自同一development来源组，不是8个独立家庭。
- 五个边界场景均停止：缺鞋、全部待洗、合身未知、固定与排除冲突、全部占用。未造鞋补齐视觉实验。
- [规则基线预览](dataset/desktop-2026-10-05/prepared/baseline-preview.jpg) 展示现有规则输出。它没有模型输出或人工审美评分。

## 三路公平比较

规则基线和两AI臂使用同一批最多20套显示候选。两AI臂采用同一模型与参数，文字块完全相同；照片臂只增加与单件ID绑定的JPEG。规则分、商品描述、价格、源文件名、天气、年龄均不交给模型。返回只能选择显示池中的整套，重复、虚构、缺件、越池都单独计失败。

评测统一关闭思考：Qwen 使用 `enable_thinking=false`，ARK 使用 `thinking={"type":"disabled"}`，两臂均保留 `temperature=0.2`、`max_tokens=500`，避免思考模式干扰固定输出预算下的公平比较。当前生产搭配请求未显式关闭 ARK 思考；此参数区别仅用于评测，不修改生产行为。请求参数已纳入缓存身份，变更思考设置后不会复用旧参数的缓存。

默认 `--output-mode prompt_only` 保持原提示词和请求体。可选 `--output-mode json_object` 额外发送 `response_format={"type":"json_object"}`，并在 system prompt 追加字符串数组与简短中文理由的对象示例；示例使用抽象占位 ID，要求替换为原候选整组的实际 ID，只返回对象、不加代码围栏。两臂使用同一输出模式，仍只有照片不同。此模式用于比较格式约束的影响，不改变生产，也不保证衣物 ID 或组合合法；原有严格解析、选衣校验和失败统计继续执行，不自动修复围栏或降级重试。模式、实际完整提示词哈希与请求参数均进入缓存身份，JSON/Markdown 报告记录输出模式，切换模式须使用独立的新报告目录。

成功、HTTP失败、非法JSON及非法选择均可缓存重放。模型失败的规则兜底单独计数，不能充当模型成功。模型标识不同会阻止主视觉审美对照；缓存历史API耗时 `elapsed_ms` 与本轮返回耗时 `return_ms`分别保留。记录包括选择、合法性、耗时、usage和安全错误码，不保留供应商自由文本理由或整份响应体。

缓存身份绑定场景/候选順序、模型/端点、提示词/参数、臂/重复编号、照片哈希和当前规则/协议/runner源码。缺缓存不联网；未知输入和无候选不调用；实时执行必须显式给调用上限，无自动重试。输出目录须为空，缓存和输出必须放在输入目录之外，实时调用前验证写入能力。

## 离线运行

从本 worktree 的 `backend/` 目录执行。以下模型配置仅用于离线身份示例，没有验证其当前图片能力，也不会加载密钥或联网：

```sh
.venv/bin/python -m eval.outfits_v2 \
  --cases eval/outfits_v2/dataset/desktop-2026-10-05/prepared/cases.json \
  --images eval/outfits_v2/dataset/desktop-2026-10-05/prepared \
  --models eval/recognition_v2/models.example.json \
  --model-name 'Qwen Plus 基线' \
  --cache-dir eval/outfits_v2/dataset/desktop-2026-10-05/cache \
  --output eval/outfits_v2/dataset/desktop-2026-10-05/runs/offline-new
```

退出0表示评测运行和报告生成成功，不能代表模型对测完成。当前首次离线报告为12场景、8输入组、0已覆盖对照、0真实调用；两臂各缺8组响应。没有搭配胜率、识别准确率或更优模型结论。

## 实际模型与盲评

真实运行需另提供已配置且支持图片的准确模型ID及端点，环境变量载入密钥，不把密钥写入JSON或聊天。使用相同命令选择该模型并加 `--live --max-calls 16`，输出改为新的空目录。现有示例不是供应商能力验收。`--run-index`用于之后明确安排的重复运行，重复结果不增加不同输入数。

报告目录有 `report.json/md`、`manual-review.template.json`、`blind-key.json`。模板按固定种子随机左右，显示目标偏好，隐藏来源、理由及分数；主比较为属性对照片，另包含两臂各自对规则基线。只有模型合法结果才填入组合；缺结果仍为空。没有模型结果时的24个成对记录全是待填模板，不能计成人工盲评。相同组合标记无需比较，评审允许left/right/tie/neither。映射文件应与评审材料分开保管。

本轮只能研究冻结候选内的视觉选择收益，未知厚薄不参与保暖正确率。更大衣橱、候选多样性、模型顺序敏感性和真实家庭实穿另行验证。

## 检查命令

```sh
.venv/bin/python -m pytest -c /dev/null -p no:cacheprovider --confcutdir=tests/v2 \
  tests/v2/test_outfit_eval_prepare.py tests/v2/test_outfit_eval_protocol.py \
  tests/v2/test_outfit_eval_runner.py tests/v2/test_outfit_eval_report.py \
  tests/v2/test_outfit_eval_cli.py tests/v2/test_c_rules.py \
  tests/v2/test_eval_v2_dataset.py tests/v2/test_eval_v2_scoring.py \
  tests/v2/test_eval_v2_runner.py tests/v2/test_eval_v2_cli.py
```

`--confcutdir`避免加载旧版应用测试夹具；这些是纯评测与规则检查，不代表整站、数据库或真机验收。
