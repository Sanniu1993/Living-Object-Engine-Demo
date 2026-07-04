# EXP-003 — 权威术语种子（Seed Glossary）

**日期：** 2026-07-05

## 目的
验证：给 Memory 预置一份权威术语表，能否从源头修好"术语选得不够好/不一致"的问题（A 类问题）。

## 假设
Extractor 首次遇到术语时随手猜的英文会被 Memory 冻结、一致地传播下去（如 `火影辅佐`→`Hokage Assistant`）。
QA 只查一致性、查不出"一致地错"。若在跑之前先注入人工策划的权威译名，
Translator 就不用猜、也猜不错 —— 术语从源头就对且一致。

## 修改
- 新增 `seed_glossary.json`（62 条，按 Naruto 社区通行译法）
- 新增 `MemoryStore.seed_glossary()`（权威覆盖，区别于 Extractor 的"只增不改"）
- `main.py --seed-glossary` 跑前注入 Memory
- 对应 CHANGELOG v0.9

## 实验设置
- 变量：有种子 vs 无种子（其余相同）
- Benchmark：Chapter 1~5（见 `benchmark/benchmark.md`）
- 翻译/判官：DeepSeek

## 结果

### 术语质量（人工核验用户此前用 ChatGPT 挑出的问题项）
| 术语 | 无种子（旧） | 有种子（新） |
|---|---|---|
| 火影辅佐 | Hokage Assistant（像秘书） | **Hokage Advisor** ×5，Assistant ×0 |
| 警卫部 | Police Force / Konoha Police Force（不一致） | **Military Police Force** ×7，裸 Police Force ×0 |
| 软体改造 | Soft Body Modification | **Soft Physique Modification**（canon）|
| 忍术命名 | Style / Release / Jutsu 混用 | 统一 `X Release` |

### QA 通过率
| | 无种子（EXP-001 各轮） | 有种子（本次 5 章） |
|---|---|---|
| 一次通过章节 | 2~3 / 5，且反复被 flag 术语/顺序不一致 | **5 / 5，全部一次通过，零修订** |

## 结论
**假设成立。** 预置权威术语表把 A 类问题从源头消除：
- 术语不再是"一致地错"，而是"一致地对"。
- 更关键的副产物：**QA 从源头就没得可挑，5 章全部一次通过、无需 QA→修订循环** ——
  证明"修 glossary 初始质量"比"事后让 QA 兜底"更省、更干净，A 类确实是上游问题、不是 QA 的活。

## 局限
- 种子是 **IP 专属**的（靠 Naruto 粉丝译名共识）。换一本没有共识译名的小说就没种子可种；
  通用化需要"Extractor 提议译名 → 强模型审核 → 定稿"，成本更高，暂不做。
- 种子须在**空 Memory** 上跑才完全生效（种子先入、后续抽取只增不改、不会覆盖）。
- 本次是观察性前后对比（非多轮受控 A/B）；术语项是相对客观的，结论可信度较高。

## 下一步
- 剩下的是 B 类"小说味"（LLM 腔、句式重复），种子解决不了 —— 候选 EXP-004（Translator 加 Style Guide）。
- B 类评分偏主观，最好等接了强模型判官后再认真做。
