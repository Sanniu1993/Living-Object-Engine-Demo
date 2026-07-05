# CHANGELOG

只记录"改了什么"。为什么改、有没有效，看 [`docs/experiments/`](docs/experiments/)。

---

## v1.6 — 漏译闸（确定性补译）

### 修改
- `workflow_reviser.py` 新增 `find_untranslated_cjk()`：正则扫译文里残留的中文片段
- `main.py` 每章定稿后过"漏译闸"：扫到中文就让 reviser 补译（最多2次），保证成品无中文残留

### 原因
- 30 章切片发现 DeepSeek 偶发漏译：25 章里 5 章残留未翻中文（如 "默契"、"波风水门"整句）；
  GPT-5 mini 判官只查一致性、抓不到这类。漏译是随机偶发，重跑解决不了，需确定性兜底。

### 结果（EXP-007）
- 检测免费（正则），只有真漏译才花一次 DeepSeek 修复调用
- 重译验证：新译文照样会漏（且漏在不同位置），闸门每次兜住；最终 6-30 零中文残留
- 模式复用：能确定性判的别用 LLM——判官管语义，正则管漏译

---

## v1.5 — 省判官：默认关掉复查

### 修改
- 定稿默认流程改为 `QA→修复` 收尾，不再复查（re-QA）；每章判官调用从最多2次降到恒定1次
- 新增 `--recheck` 开关，想要"修复后再复查一遍"的更稳流程时再开

### 原因
- 种子术语表已让绝大多数章 QA 一次通过，复查基本是浪费；长篇跑 100+ 章时，砍掉复查明显省强判官成本

---

## v1.4 — 断点续跑 / 幂等（长篇抗崩）

### 修改
- Memory 记录 `extracted_chapters`；`extract_memory` 幂等：已抽取的章直接跳过（防重复 append / state_log 重复计数）
- 主循环：一章"已完成"=已抽取且译文文件存在 → 跳过（省钱）
- QA 报告改为加载已有 + 增量合并 + 每章落盘（中途崩不丢、跳过的章不丢）

### 原因
- 100 章 × 4 次调用 = 400+ 次，中途必崩；原来重跑会从头再翻（白烧）且往 Memory 重复 append（污染）

### 结果（两段式验证）
- Run A 跑 ch1-2 → Run B resume 到 ch3：正确跳过 1、2（零 API），只跑 3
- 幂等确认：ch1 的 timeline 重入后仍为 3 条（无重复 append）
- QA 报告 [1,2,3] 完整（跳过章保留 + 新章合并）

---

## v1.3 — 长篇成本：上下文有界化（O(N²)→O(N)）

### 修改
- `memory_store.py` 新增 `compact_context_string()`：只给当前属性 + glossary + 封顶摘要，
  **丢掉无限增长的 timeline/state_log/state_history**；extract/translate 改用它（原来全量 dump）
- `relevant_context_string()`（QA 用）给 timeline/state_log 加"最近 N 条"上界，summary 封顶
- 常量 `CONTEXT_SUMMARY_CHARS=600`、`CONTEXT_RECENT_EVENTS=20`

### 原因
- 原来 extract/translate 每章都全量 dump 整个 Memory，Memory 只增不减 → 每章成本随章数线性涨，
  总成本 O(N²)，且约第 50~80 章就撞上下文窗口。长篇（100 万字 / 数百章）跑不动。

### 结果（合成规模测试 + 真实第1章验证）
- 每章上下文：全量 dump 在 ~100 章约 25 万字符且每章重发；紧凑视图约 1.5 万、QA 视图钉死在 ~1.2 万
- 每章成本从"随章数涨"变"基本恒定" → 总成本 O(N)
- 第1章重跑质量无回归（术语一致、QA 通过，原身/叼着还译得更准）
- 完整历史仍存在 memory.json 里，只是不塞进每章 prompt
- 备注：长篇跑全本还差"resume 断点续跑"（中途崩不重来、不重复 append）

---

## v1.2 — 压 QA 判官误报

### 修改
- QA prompt（prompts/qa/v2.txt）新增"不算不一致"白名单：用角色名/称谓/大小写差异不算误报；
  但明确"截断单名（Orochimaru→Orochi）算不一致"，避免规则过宽误伤召回

### 结果（EXP-006）
- 误报清零（用名/称谓那 4 条 + 大小写噪音全没），召回一点没丢（植入仍 3/3，真错误全在）
- 教训：白名单第一版太宽把 "Orochi" 误当简称放过了（2/3）——收窄边界后恢复 3/3
- 局限：判官有 run-to-run 随机性，单次结果有噪音，严谨结论需多跑取平均

---

## v1.1 — 接入 AIHubMix 判官 + 定稿流程调整

### 修改
- `llm_client.py` 新增 `aihubmix` provider（OpenAI 兼容聚合平台）；QA 判官换成 AIHubMix 的 GPT-5 mini
- 定稿闭环改为"以修复收尾"：译文→QA→修复→复查→最后修复（末轮不再复查）
- QA `max_tokens` 2048→8192：GPT-5 mini 是推理模型，2048 会被推理吃光导致返回空

### 结果（EXP-005：受控对比两个判官）
- 命中：植入 3 个已知错误，GPT-5 mini **3/3**，DeepSeek **0/3**
- GPT-5 mini 还额外抓到 DeepSeek 全漏的真错误（含一个人物关系语义错）
- 教训：为压 DeepSeek 噪音而过度收紧 prompt，把它的检测力也一起阉割了 → DeepSeek 判官已基本失效
- GPT-5 mini 代价：对"用名/称谓"过度严格（可用 prompt 规则修，候选 EXP-006）

---

## v1.0 — 译法规范规则

### 修改
- Translator prompt 新增"译法规范"段（prompts/translator/v2.txt）：
  成语不字面直译（举例 背黑锅→take the blame）、"火影"指动漫时译 Naruto、"原身"不译 predecessor

### 原因
- 人工复核发现成语直译、专名误译等必修错误，这些不是一致性问题、QA 抓不到

### 结果
- 第 1 章：3 个必修错误修好 2.5 个（背黑锅、原身修好；火影/Naruto 半修），无新增错误
- 结论：prompt 规则能治"死记硬背"型错误，治不了"需要语境推理"型错误（详见 EXP-004）

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
