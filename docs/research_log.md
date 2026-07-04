# Research Log（研究日记）

> 每天一两句。记"发现了什么 / 猜测 / 下一步"。半年后会感谢今天的自己。

---

## 2026-07-04

- 接入 DeepSeek 跑通全流程；发现 QA 会把中英原文/译文的对应关系弄反，报一堆假问题。
- 猜测：Prompt 没讲清 Memory 的 key 是中文、要比的是英文译法。
- 计划：改 QA Prompt 讲清这层关系。

---

## 2026-07-05

- 发现 DeepSeek 做判官问题很多：会把"一致"当问题报、会自创"逻辑矛盾"去点评剧情、
  Memory 变大后还会重复退化把 JSON 撑爆导致崩溃。
- 猜测：便宜模型 Instruction Following 不足，做判官不靠谱。
- 已做：Prompt 硬约束 + 代码兜底（类别过滤、max_tokens、重试、逐章落盘）把噪音和崩溃压下去。
- 发现：Memory 效果方向上像是有用（减少术语/人名漂移），但两次 A/B 方向相反，判官噪音 + 小样本让结论不稳。
- 下一步：换 GPT/Claude 判官验证（接口已留好），同配置多跑几轮看方差。
- 另注意到一个真实译文缺陷：DeepSeek 翻日本人名时姓/名顺序不稳定（Hiruzen Sarutobi ↔ Sarutobi Hiruzen）——
  候选下个实验：给 Translator 加 Style Guide 看能否降低 name drift。
- 用户拿 ChatGPT 复核译文，最大发现：DeepSeek 几乎不加/删/改剧情（保真度好），最大短板是"小说味"。
  → 把问题分成 A 类（术语选得不够好）和 B 类（LLM 腔）。A 类不是一致性问题、是 canonical 译名本身差。
- 做了 EXP-003（种子术语表）：预置 62 条权威译名后，A 类从源头修好，5 章 QA 全部一次通过、零修订。
  收获：修 glossary 初始质量 >> 事后 QA 兜底。B 类（小说味）种子解决不了，留给 EXP-004。
