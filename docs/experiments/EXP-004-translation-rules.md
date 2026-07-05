# EXP-004 — Translator 译法规范规则

**日期：** 2026-07-05

## 目的
验证：在 Translator prompt 里加"译法规范"硬规则，能否自动修好人工复核发现的几类必修翻译错误。

## 假设
成语直译、专名误译这类错误，靠 prompt 里的明确规则 + 举例就能防住。

## 背景
用户用 ChatGPT 复核第 1 章译文，发现 3 类必修错误（非一致性问题，QA 抓不到）：
1. `背黑锅` 直译成 "bear that black pot"（成语字面直译）
2. `原身` 译成 "predecessor"（穿越梗误读，且误导）
3. `以火影喻历史` 的"火影"译成 "Hokage"，应为 "Naruto"（专名指代：动漫 vs 职位）

## 修改
- Translator prompt 新增"译法规范"段（prompts/translator/**v2**.txt）：
  - 成语/惯用语不字面直译，举例 背黑锅→take the blame 等
  - "火影"指动漫时译 Naruto，指职位才译 Hokage
  - "原身"译 the body's original owner，不译 predecessor
- 单变量：只改 Translator prompt，Memory 用同一份种子版（其余同 benchmark）

## 结果（第 1 章重跑）
| 错误 | v1（旧） | v2（加规则） | 结果 |
|---|---|---|---|
| 背黑锅 | bear that black pot | take the blame | ✅ 修好 |
| 原身 | his predecessor | the body's original owner | ✅ 修好 |
| 火影→Naruto | Hokage as a metaphor | 一句对(never watched Naruto)、一句仍错(Hokage as an allegory) | ⚠️ 半修 |

**净结果：3 个错误修好 2.5 个，无新增错误，QA 仍一次通过。**

## 结论
**假设部分成立。** 有明确对应关系的错误（成语、专名误读）靠 prompt 规则能有效修好；
但"火影何时指动漫、何时指职位"需要**语境判断**——便宜模型（DeepSeek）加了规则也只是概率性改善，
同一段里一句对一句错，不是根治。

**贯穿性结论**（与 EXP-002 判官噪音一致）：**prompt 规则能治"死记硬背"型错误，治不了"需要语境推理"型错误。**
后者是便宜模型的能力边界，要根治得靠更强的模型。

## 局限
- 单次、单章、temperature=0.3，火影/Naruto 那半个残留也可能受随机性影响；多跑几轮更稳。
- QA 全程抓不到这三类错（都不是一致性问题）——再次说明"QA passed ≠ 翻译对"。

## 下一步
- v2 规则净收益为正，转正为默认（CHANGELOG v1.0）。
- 语境类残留 + B 类"小说味"留给强模型（换强翻译模型 / 强判官后再评）。
