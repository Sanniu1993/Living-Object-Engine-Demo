# CHANGELOG

只记录"改了什么"。为什么改、有没有效，看 [`docs/experiments/`](docs/experiments/)。

---

## v0.9 — 权威术语种子

### 新增
- `seed_glossary.json`：62 条按 Naruto 社区通行译法策划的权威术语表（人名/地名/组织/术语/忍术）
- `MemoryStore.seed_glossary()`：权威覆盖语义（区别于 Extractor 的"只增不改"）
- `main.py --seed-glossary`：跑前把种子注入 Memory 作为 canonical 译名，默认读 `seed_glossary.json`

### 原因
- Extractor 首次遇到术语时随手猜的英文会被 Memory 冻结、一致地传播下去（如 `火影辅佐`→`Hokage Assistant`）；
  QA 只查一致性、查不出"一致地错"。根子在缺一个高质量的初始术语表。

### 结果
- `火影辅佐` 全章统一为 `Hokage Advisor`（原 `Assistant`）；`警卫部`→`Military Police Force`、
  `软体改造`→`Soft Physique Modification`、忍术统一为 `X Release` 等
- 种子生效后 QA 更易一次通过（术语从源头就一致，无需事后修订）
- 详见 EXP-003

---

## v0.1 — 基础 Demo

### 新增
- Extractor（Memory 抽取）
- Memory（单一 `memory.json`，只增长不覆盖）
- Translator（只消费 Memory，不重新分析全文）
- QA（术语/称呼一致性、设定冲突检查）
- main.py 主循环（for 循环走完四步，不用 LangGraph、不用 Agent 类）

### 结果
- Demo 跑通，可翻译章节

---

## v0.2 — 接入便宜模型 + 适配真实语料

### 修改
- `llm_client.py` 支持 DeepSeek（OpenAI 兼容格式），调试阶段用它省钱
- `splitter.py` 支持"分隔线 + 编号标题"格式（`------------` 换行 `001 标题`）
- 翻译方向暂定 中文→英文

### 结果
- 能在真实小说语料（火影同人，`chapters/1-5.text`）上跑通

---

## v0.3 — QA 正确性修复

### 修改
- QA Prompt 讲清 Memory 的 key 是中文原文、value 才是英文译法
- QA Prompt 禁止输出"一致 / 不报告"之类确认性条目

### 原因
- 之前 QA 把"译文是英文、Memory key 是中文"误判为不一致，报出大量"应该用中文"的假问题

### 结果
- 假阳性噪音大幅下降（详见 EXP-002）

---

## v0.4 — A/B 实验骨架

### 新增
- `--ab-test`：每章同时跑"关闭 Memory / 开启 Memory"两版翻译 + QA，输出对比报告
- Translator 支持 `memory=None`（关闭 Memory 的对照臂）

### 原因
- 需要可复现地量化"Memory 到底有没有用"

### 结果
- 可产出 `ab_test_report.json`（详见 EXP-001）

---

## v0.5 — QA 健壮性（防炸）

### 修改
- Memory 按当前章节裁剪后再喂 QA（`relevant_context_string`）
- QA 调用收紧 `max_tokens`；最多返回 20 条 issue（代码兜底截断）
- QA 解析失败自动用更短 prompt 重试一次
- A/B 报告逐章落盘，单章失败不再拖垮整轮

### 原因
- 第 4 章 Memory 膨胀后，DeepSeek 陷入重复退化、输出被截断，导致 QA JSON 解析失败、整轮崩溃

### 结果
- 第 4 章不再崩溃；QA 成功率 100%（详见 EXP-002）

---

## v0.6 — QA 类别硬约束

### 修改
- QA Prompt 明令"只能查三类、禁止评价剧情/动机、禁止新增类别"
- 代码兜底 `ALLOWED_TYPES` 过滤：非三类的 issue 直接丢弃

### 原因
- DeepSeek 自创"逻辑矛盾"类别，跑去点评剧情合理性，污染指标

### 结果
- 不再出现"逻辑矛盾"等越界条目，QA 噪音进一步下降（详见 EXP-002）

---

## v0.7 — QA 判官模型可插拔

### 修改
- `get_client(role)` 支持按角色分别配模型：翻译/抽取用 DeepSeek，QA 可单独换更强模型
- `.env` 加 `QA_LLM_PROVIDER` / `QA_LLM_MODEL`（不配则 QA 回退用 DeepSeek）

### 原因
- DeepSeek 做 QA 判官噪音大、指令遵循弱；接口先留好，后续换强判官

### 结果
- 当前仍用 DeepSeek 做 QA；换判官只改 `.env`，业务代码不动

---

## v0.8 — 定稿闭环（QA→修订）

### 新增
- `workflow_reviser.py`：按 QA 问题清单修订译文，只改点名问题、不重译不润色
- `--revise`：QA 发现问题后自动修订，QA→修订→复检最多 2 轮，输出定稿

### 原因
- 之前 QA 只发现问题不修复，需要人工改；现在要闭环拿定稿

### 结果
- 第 1 章定稿跑通，2 轮内 QA 通过（人名统一到 Memory 标准写法）
