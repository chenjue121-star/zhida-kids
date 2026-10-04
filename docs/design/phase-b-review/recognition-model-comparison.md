# B 阶段识别模型汇总、评测分析与选型建议

核对日期：2026-10-02。本文是选型分析，尚未批准为实施规格；没有调用收费模型 API、测出儿童衣物准确率或修改供应商配置。第五组产品与 UI 仍待确认。

**建议优先用固定版本 `qwen3.7-plus-2026-05-26` 做主模型试点，同时对测豆包 Seed 2.1 Lite/Pro。**这是基于国内服务、图像与结构化能力、版本可复现性及公开价格的预选，不是已经实测出的准确率冠军。若豆包在独立测试中达到同样的质量要求且人工纠正负担没有显著增加，沿用现有 ARK 接入可能更合适。

现阶段更适合先用较强模型建立质量基线，再判断 Flash/Lite 能否替代常规单件任务。不能先认定 Mini 足够准确，再依赖它自己的 confidence 决定哪些图片需要复核。

## 1. 智搭真正需要测的能力

| 能力 | B 阶段具体要求 | 主要错误 |
| --- | --- | --- |
| 单件属性 | 类别、子类、颜色、图案使用统一中文枚举 | 连体衣认成普通上衣；背景色认成衣物色 |
| 多件候选 | 识别可见实物、保留逐件属性和原图对应 | 漏裤子、重复候选、把外套颜色写给内搭 |
| 定位 | 可选候选框；不可靠时保留整图核对 | 框错物体；坐标缩放后未映射回原图 |
| 未知处理 | 看不清允许 unknown/null，不用默认值填满 | 隐藏衣标却输出尺码；厚薄、材质凭外观猜测 |
| 可用输出 | 多候选 JSON、合法枚举、明确失败 | JSON 正确但内容错误；截断后被解析成成功 |
| 用户负担 | 家长容易核对、只改例外 | 模型分数较高，但每件仍需改多个字段 |

是否拥有、归属哪个孩子、合身、可穿／待洗是用户事实，不能作为模型“识别准确率”。品牌和尺码只在清楚可见的衣标中作为可核对建议；照片通常不能证明真实材质、适穿季节或保暖能力。

## 2. 国内商用 API 候选

价格为人民币／百万 token，列“输入／输出”，采用常规实时、未命中缓存的相应输入区间。实际费用还取决于图片 token、思考输出和重试。火山按系列发布价格，下表不把系列价描述为单个快照的专属报价。

| 模型 | 应记录的 API ID | 标准单价与区间 | 本项目用途 |
| --- | --- | --- | --- |
| 通义千问 3.7 Plus | `qwen3.7-plus-2026-05-26` | **¥2／¥8**，输入 ≤256K | **主模型试点首选**；可固定版本，图像＋结构化输出，建立质量基线 |
| 豆包 Seed 2.1 Lite | `doubao-seed-2-1-lite-260915` | **¥0.8／¥2.7**，输入 ≤1024K，非音频 | 现有 ARK 路线的常规识别竞争者 |
| 豆包 Seed 2.1 Pro | `doubao-seed-2-1-pro-260915` | **¥6／¥30**，输入 ≤1024K | ARK 强模型基线及困难场景复核候选 |
| 通义千问 3.7 Flash | `qwen3.7-flash-2026-07-15` | **¥0.2／¥0.8**，输入 ≤32K | 低成本候选；质量达到门槛后再考虑常规单件使用 |
| 通义千问 3.8 Max | `qwen3.8-max-0902` | **¥12／¥36**，输入 ≤1M | 小规模强模型参考，衡量 Plus 还有多少质量差距 |
| 通义千问 3.8 Flash | `qwen3.8-flash` | **¥0.8／¥2.7**，输入 ≤1M | 更新的轻量候选；本次文档未列固定快照，先记录返回版本，不能自行拼日期 |
| Seed 2.0 Mini 当前替换版 | `doubao-seed-2-0-mini-260428` | **¥0.2／¥2**，输入 ≤32K，系列价 | 低成本迁移对照；不能只因是替换版就认定质量已过关 |
| 项目旧默认：Seed 2.0 Mini | `doubao-seed-2-0-mini-260215` | **¥0.2／¥2**，输入 ≤32K，系列价 | 历史基线；2026-10-22 14:00（UTC+8）下线，部署是否覆盖默认尚未核实 |

千问型号、图像输入及结构化支持见[百炼视觉理解文档](https://help.aliyun.com/zh/model-studio/vision-model)，北京区价格见[百炼官方价格表](https://help.aliyun.com/zh/model-studio/model-pricing)。固定 Plus 的价格行是 ¥2／¥8，不能把动态别名的限时折扣套到固定版本。

豆包 0915 型号见[火山官方模型发布记录](https://docs.volcengine.com/docs/ark/model-release-announcement?lang=en)，接口特性需对照[模型参数支持表](https://docs.volcengine.com/docs/ark/model-parameter-support?lang=zh)；价格见[火山官方价格表](https://docs.volcengine.com/docs/ark/model-pricing?lang=zh)。价格网页依赖 JavaScript，本次通过该文档的[公开只读文档接口](https://www.volcengine.com/api/doc/getDocDetail?LibraryID=82379&DocumentID=1544106)复核，文档更新时间为 2026-09-28。

旧 Mini 0215 的下线时间及推荐替换版见[官方下线公告](https://docs.volcengine.com/docs/ark/model-deprecation-notice?lang=zh)。这是供应商生命周期的明确变化，不代表部署环境已经自动迁移。

最新 0915 Lite/Pro 的模型列表确认多模态理解和结构化输出，但未单列“视觉定位”标签。[Grounding 教程](https://docs.volcengine.com/docs/ark/grounding?lang=zh)的多目标示例使用的是 Pro 0628。不能把该示例直接当成 0915 已通过定位验收，也不能因为标签缺失就判定不支持；本项目应专门测框及属性对应。

以上模型都需验证本项目的多件输出、unknown 行为、候选定位和中文枚举。厂商列出图像或 JSON 支持，只证明接口能力，不能证明会主动保留未知、识别全部衣物或正确分配属性。

## 3. 海外模型汇总

以下为各自官方直接 API 的美元／百万 token 标准实时输入／输出价格，不做未经核实的汇率换算，也不把其他云平台合同等同于直接 API。

| 模型 | API ID | 输入／输出 | 本项目定位 |
| --- | --- | --- | --- |
| Gemini 3.8 Flash | `gemini-3.8-flash` | **$0.75／$3.75**，截至 2026-12-31 | 图像、结构化与 bbox 的海外对照 |
| Gemini 3.5 Flash-Lite | `gemini-3.5-flash-lite` | **$0.30／$2.50** | 轻量成本对照 |
| GPT-6.1 Sol | `gpt-6.1-sol` | **$2／$10**，短上下文档 | OpenAI 质量与成本平衡候选 |
| GPT-6 Luna | `gpt-6-luna` | **$0.10／$0.50**，短上下文档 | OpenAI 低成本视觉候选 |
| GPT-6 Astra | `gpt-6-astra` | **$10／$50**，短上下文档 | 高能力参考；能否显著改善衣物任务需要对测 |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | **$2／$10** | 多语言视觉和细节歧义处理的另一家对照 |
| Claude Haiku 4.5 | `claude-haiku-4-5-20251001` | **$1／$5** | Claude 轻量基线；使用前复核生命周期 |

Google 型号见[Gemini 模型目录](https://ai.google.dev/gemini-api/docs/models)，价格见[官方定价](https://ai.google.dev/gemini-api/docs/pricing)。3.8 Flash 从 2027-01-01 起为 $1.50／$7.50，预算不能永久采用优惠价。Google 给出的 bbox 采用 `[ymin,xmin,ymax,xmax]`、0–1000 坐标，接入需转换；见[图像理解](https://ai.google.dev/gemini-api/docs/image-understanding)。

OpenAI Docs 的[当前模型对照](https://developers.openai.com/api/docs/models/compare)确认以上三款支持图像输入和结构化输出，[价格表](https://developers.openai.com/api/docs/pricing)给出对应标准档位。[图像指南](https://developers.openai.com/api/docs/guides/images-vision)仍指出计数和精确定位可能出错，所以不能用旗舰定位替代实际检测验证。

Claude 型号与版本见[官方模型目录](https://platform.claude.com/docs/en/models/overview)，价格见[官方定价](https://platform.claude.com/docs/en/about-claude/pricing)。5.5 无日期 ID 是固定 snapshot；4.5 则固定日期版本。Claude 的定位要求与 Gemini 不同，应参照[坐标指南](https://platform.claude.com/docs/en/build-with-claude/vision-coordinates)处理像素坐标及缩放。

**国内首发不以这些海外直接 API 为依赖。**OpenAI 的[支持地区](https://developers.openai.com/api/docs/supported-countries)、Google 的[可用地区](https://ai.google.dev/gemini-api/docs/available-regions)、Anthropic 的[支持地区](https://www.anthropic.com/supported-countries)均未列中国大陆。Google 的[API 条款](https://ai.google.dev/gemini-api/terms)还要求客户端提供给可用地区内的用户；海外后端本身不能解决这一资格问题。海外对测仅在提供方允许的账户、主体和使用环境中开展；另一个云平台的资格需按其实际合同单独确认。

## 4. 开源与专用视觉模型

| 路线 | 代表 | 合适用途 | 首期判断 |
| --- | --- | --- | --- |
| 开源视觉语言模型 | [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B)、[Qwen3.6-27B](https://huggingface.co/Qwen/Qwen3.6-27B)、[InternVL3.5-8B](https://huggingface.co/OpenGVLab/InternVL3_5-8B) | 自托管分类、属性和候选描述；后续可做领域适配 | 中后期备选，需计算 GPU、运维、并发及回归成本 |
| 开放词汇检测 | [GroundingDINO](https://github.com/IDEA-Research/GroundingDINO) | 按类别文字找候选框，辅助减少漏件 | 只有证明候选召回有增益后才加入 |
| 分割 | [SAM 2](https://github.com/facebookresearch/sam2) | 根据点／框切分区域，辅助缩略图 | 不独立完成类别和中文属性识别；B 不承诺自动抠图 |

开源检查点、托管商 API SKU 与商用服务版本必须分开记录。“模型权重免费”不等于在线推理总成本更低。旧代码里已有阿里 ClassifyClothing／SegmentCloth 封装，但其响应解析、字段映射和失败处理尚未验证，不能把封装存在视为能力已验收；详见上一份[代码与数据分析](/Users/ll/Documents/智搭（儿童）/.worktrees/phase-a/docs/design/phase-b-review/recognition-accuracy-analysis.md)。

## 5. 公开评测能说明什么

候选商业家族的公开证据：

| 作者报告中的模型名 | 公开视觉分值 | 适用边界 |
| --- | --- | --- |
| Seed2.1 Pro | BabyVision 73.7；ERQA 72.0 | 官网未将这些结果明确映射到 0915 快照 |
| Qwen3.7-Plus | BabyVision 无 CI 64.7／有 CI 70.4；ERQA 69.8；RealWorldQA 86.9 | 作者报告未在该表映射到具体 API 日期快照；CI 工具条件必须保留 |

分别来自[Seed2.1 官方评测](https://seed.bytedance.com/zh/seed2_1)和[Qwen 作者官方视觉结果表](https://huggingface.co/Qwen/Qwen3.8-27B-FP8/blob/main/README.md)。两家未确认相同评测实现、提示词、工具和思考预算，**不能据此把 72.0 与 69.8 的差值解释为豆包更适合儿童衣物**。BabyVision 的名称也不代表儿童服装数据集。这些数字证明候选有公开视觉评测依据，但项目中的类别、颜色与多件召回仍未测。

以下是 Qwen 作者在同一官方模型卡发布的分值，**不是本次跑分，也不是儿童服装准确率**：

| 公开指标 | Qwen3-VL-30B-A3B | Qwen3.5-9B | Qwen3.5-4B |
| --- | ---: | ---: | ---: |
| CountBench | 90.0 | 97.2 | 96.3 |
| RefCOCO(avg) | 89.3 | 89.7 | 88.1 |
| ERQA | 45.3 | 55.5 | 54.0 |

来源：[Qwen3.5-9B 官方模型卡的视觉评测表](https://huggingface.co/Qwen/Qwen3.5-9B#vision-language)。该表没有逐项说明这几行基线属于作者复测还是转引。因此，它只能作为小模型也值得进入候选的线索，不能外推为 Qwen 商用 Plus 的成绩，更不能把 CountBench 97.2 写成衣物识别准确率 97.2%。

MMMU 主要考察跨学科图文推理，DocVQA／OCRBench 偏文字与文档；RefCOCO、CountBench 更接近定位和计数，仍与家庭照片中的儿童服装不同。将不同厂商、不同工具使用和思考预算的数字拼成总榜，会制造不存在的统一排名。

[DeepFashion2](https://github.com/switchablenorms/DeepFashion2)更适合参考服装检测与分割标注，但其 13 类不包含鞋袜和婴幼儿连体衣，也没有智搭所需的中文颜色与厚薄真值。[Fashionpedia](https://github.com/cvdfoundation/fashionpedia)可参考逐实例属性体系。两者都需要补充本项目家庭实拍数据，不能直接作为完整产品验收集。

本次没有找到覆盖本项目候选商业版本、使用同一协议的儿童衣物公开测评。当前只能给出工程选型优先级，准确率排名仍待项目实测。

## 6. 如何做可信的项目对测

### 先区分模型问题与流程问题

当前旧提示词只选最显著的一件，解析器还会丢弃数组其余对象；后处理会把未知补为 top／white／normal，空输出也能得到约 0.72 的 confidence。直接把这些流程套在新模型上，会错把流程损失算成模型差异。现有 20 个文件仅有 4 个有效独立图像场景，标签冲突，不能产出可信选型排名；证据见[准确率分析](/Users/ll/Documents/智搭（儿童）/.worktrees/phase-a/docs/design/phase-b-review/recognition-accuracy-analysis.md)。

先冻结多候选字段、类别关系、配对物品计数与未知规则；保留原始输出，记录每次模型 ID、图片内容哈希、提示词与解析版本。修复当前评测命令的 dry-run 会在缓存缺失时调用真实 API 的问题后，才能把它作为离线检查入口。

### 两种评测分别报告

1. **原图端到端**：同一张图换模型，测多件发现、候选重复、属性串件及定位。候选与人工真值一对一匹配，定位用固定 IoU 规则；框缺失应报告定位失败，不能悄悄删掉对应失败样本。
2. **人工框裁切的属性评测**：给所有模型相同已标注区域，测类别、子类、主色、图案和 unknown，帮助判断错误来自定位还是属性识别。

检测器＋分割器＋VLM 的组合另算整条流程。不能将带专用检测器的方案与只看原图的单模型结果混成“模型准确率”。

### 样本、控制项与首轮候选

先整理 100 个独立诊断场景：60 单件、30 多件、10 无衣物／无法判断场景；覆盖平铺、穿着、悬挂、深浅色、遮挡、连体衣、背带裤、鞋袜和同款多件。这批用于排除明显不合适的候选，不作为正式可靠率承诺。

再建立 300–500 个去重且按家庭／实物／拍摄批次分组的数据集，按先前提案区分开发、校准和盲测；双人标注、分歧裁决，测试真值不交给模型改写。已有四个有效场景可保留作调试案例，不占独立盲测样本。

主对测先跑 Plus、Seed 2.1 Lite、Seed 2.1 Pro；保留旧 Mini 基线。Max 在独立、预先确定且覆盖各分层的子集上测质量差距。Flash 在相同协议下加入成本优化对照。使用同一源图、枚举、未知规则、候选上限、重试与超时；允许供应商必要的请求格式转换。图像预算和思考模式必须公开记录，分别比较同流程结果和各方案在预设成本预算内的结果，避免把更大的推理预算误归因于模型。

### 面向入库的指标

| 指标 | 计分要求 |
| --- | --- |
| 类别与子类 | 正确率及类别宏平均 F1，单独看稀少类别 |
| 可见颜色、图案 | 逐字段正确率；可见真值却返回 unknown 算未完成 |
| 整件可直接接受 | 真值可见的类别／颜色／图案同时正确；未知覆盖率单列 |
| 多件候选 | precision、recall、件数正确率、重复与串件率 |
| 弃答与幻觉 | 不可判断时是否保留未知；编造隐藏字段的比例 |
| 输出稳定性 | 原始 JSON／枚举合法率、截断、解析失败、请求失败 |
| 家长负担 | 每件修改字段数、漏件补录次数、确认时间；修正前后分别统计 |
| 性能与费用 | 端到端 P50／P95、超时率，每张图和每件合格候选的全调用成本 |

沿用上一份提案的候选门槛：单件类别／颜色 ≥95%，可见关键字段整件通过 ≥90%；多件 precision ≥95%、recall ≥90%。这些数值尚未达成，也不是已确认的产品承诺。需同时检查关键字段完成覆盖率、困难分层和分组置信区间，不能让“全部 unknown”通过验收。

300–500 个总样本只是选型起点。若另要证明无需额外提示的错误率低于 1%，需另外设计足够大的独立审计样本；不能把多个字段、同图多件或重复调用当成独立样本凑数。

## 7. 费用推演与最终选择规则

通用计算：`调用费用 = (实际输入 token × 输入单价 + 实际计费输出 token × 输出单价) / 1,000,000`。按实际账单口径包含图片和思考 token，累加复核与重试；存储、网络和人工成本另列。

图片预算不能跨模型直接照搬：火山 Seed 2.0 及以后默认 `detail=high` 单图 1280 token，`image_pixel_limit` 会改变处理规则，见[图片理解文档](https://docs.volcengine.com/docs/ark/image-understanding?lang=zh)；千问新视觉系列按缩放后的图片面积估算，见[阿里图像理解与计费规则](https://help.aliyun.com/zh/model-studio/vision)。对测必须记录各次实际 usage，不能把某家默认预算当成所有模型的统一计费结果。

**只为理解数量级的假设**：每次计费输入 3,000 token、计费输出 700 token，无缓存、无重试。Plus 为 ¥0.0116／次，3.7 Flash 为 ¥0.00116／次；1,000 次分别为 ¥11.60 与 ¥1.16。这不是同一批图片的成本测量，不代表图片 token 预算相同。Plus 相对 Flash 的单价差不能直接当成十倍每张图片费用。

若 Flash 首识别、20% 请求再用 Plus，且两次调用都满足上述假设，平均为 ¥0.00348／次、1,000 次 ¥3.48。实际复核率、复核收益、触发漏检与尾延迟均待测。路由信号不能只取模型自评分；未知、异常候选、字段冲突、图像质量和随机审计都应参加验证。还须保留明确的人工核对入口。

最终顺序：

1. **服务可用与输出契约先过关**，不能用价格抵消无法正式提供服务或持续解析失败。
2. **质量门槛和家长负担先过关**，先看漏件、整件通过与困难类别，随后看单字段均值。
3. **在质量可接受的方案间比较实际成本和 P95**。同批图片做成对分析、按家庭／实物分组估计不确定性；小差距不能写成确定胜出。若要以“质量相当”为依据沿用现有接入，应事先规定允许的差距，并取得足够样本验证，而不是仅因未检出显著差异就宣称相当。
4. **先选一个主模型，再验证复核路由**。另一家模型用于容灾或复核要分别测效果；它不是因为不同厂商就天然更可靠的裁判。

当前预选是 **Qwen 3.7 Plus 主模型试点，Seed 2.1 Lite/Pro 对测，Qwen 3.7 Flash 后续成本优化，3.8 Max 小规模强模型参考**。是否最终切换供应商，取决于上述项目实测。实施仍按原约定，在 B 产品与 UI 全部确认并形成书面规格后展开。
