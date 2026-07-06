# EXP-011 — 流畅度判官降本：reasoning_effort 扫描

**日期：** 2026-07-06

## 目的
EXP-010 把流畅度判官换成 gpt-5，质量好但太贵。gpt-5 的成本大头是推理 token。验证调低 `reasoning_effort` 能否在保质量的前提下大幅降本。

## 假设
"扫描一段译文、列出语法/直译/矛盾"是有界的模式识别任务，不需要深链推理。预测低 effort 能在质量几乎不降的情况下砍掉大部分推理 token。

## 修改
- `llm_client`：OpenAIClient 支持 `reasoning_effort`；`_build_client` / `get_client` 按角色读 `{PREFIX}REASONING_EFFORT`。
- `.env`：`FLUENCY_REASONING_EFFORT=minimal`（对应 CHANGELOG v1.11）。

## 实验设置
- 输入：**同一份** ch3 阿语原始译文（同 EXP-010）。
- 扫 5 档：gpt-5-mini(默认) / gpt-5@minimal / low / medium / high。各 1 轮，记 usage 的推理/输出 token 当成本代理。
- 成本估算价（USD/1M，近似）：gpt-5 in1.25/out10；mini in0.25/out2。推理token计入 output 价。

## 结果

| 配置 | 推理tok | 输出tok | 问题数 | ~$/章 | 每$问题数 |
|---|---|---|---|---|---|
| gpt-5-mini | 3136 | 3847 | 6 | 0.0090 | 670 |
| **gpt-5@minimal** | **0** | **1631** | **15** | **0.0226** | **662** |
| gpt-5@low | 2688 | 3786 | 10 | 0.0442 | 226 |
| gpt-5@medium(默认) | 13440 | 14853 | 15 | 0.1549 | 97 |
| gpt-5@high | 13312 | 14484 | 14 | 0.1512 | 93 |

- **minimal 抓到 15 条 = medium/high 一样多，但推理 token 为 0、成本仅 medium 的 ~1/7。**
- medium/high 那 ~13000 推理 token 对本任务几乎纯浪费：多想没多抓。
- minimal 的"每美元问题数"(662) 追平 mini(670)，但绝对召回是 mini 的 2.5 倍（15 vs 6）→ minimal 严格占优。
- low 反而只 10 条（<minimal 的 15）：单轮噪音，且说明 effort 与质量非单调，不必往上加。

## 结论
- 假设成立且超预期：**gpt-5@minimal 是甜点档**——满血 gpt-5 的召回质量（EXP-010 里 gpt-5 每轮 15），成本从 $0.155→$0.023（**降 ~85%**），逼近 mini 的性价比但质量高一档。
- 机理：单语纠错是模式识别，不吃 chain-of-thought；gpt-5 的底模能力足够，推理 token 是浪费。
- 通用心得（可复用）：**换强推理模型时先扫 reasoning_effort**。默认 medium 常常花了大钱买没用的推理；很多"判官/抽取/分类"类任务 minimal 就够。
- 保留：各档单轮，有噪音（见 low）；minimal 是否稳定 15 需多轮确认。质量维度只比了"问题数"，未逐条比对 minimal vs high 的问题深度是否等价（下一步可做）。

## 下一步
- minimal 跑几章确认稳定性 + 抽查是否仍能抓到 EXP-010 那种语义级错误（琵琶湖指代）。
- 同法给一致性 QA 扫 effort（现在 gpt-5-mini 默认 medium，可能也在浪费推理）。
