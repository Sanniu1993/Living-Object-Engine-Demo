# Living Object Engine — MVP

验证目标只有一个：**Memory能否跨越多次调用递增成长，并被下一次调用真正复用（而不是每次重新生成）**。翻译只是验证载体，不是产品本身。

## 架构对应关系

| 文件 | 对应角色 |
|---|---|
| `llm_client.py` | 模型调用层，可插拔。现在只实现OpenAI，换provider只改这一个文件 |
| `memory_store.py` | Living Object的核心：单一`memory.json`，只增长不覆盖，State作为跨行业通用记录结构 |
| `splitter.py` | Workflow 1: Chapter Reader |
| `workflow_extractor.py` | Workflow 2: Memory Extractor（只理解，不翻译） |
| `workflow_translator.py` | Workflow 3: Translator（只消费Memory，不重新分析全文） |
| `workflow_qa.py` | Workflow 4: QA（检查术语/称呼一致性、设定冲突） |
| `workflow_reviser.py` | Workflow 5: Reviser（按QA清单修订译文，产出定稿，仅`--revise`时启用） |
| `main.py` | 主循环，一个for循环走完四步；额外支持 `--ab-test` 对照实验和 `--revise` 定稿闭环 |
| `verify.py` | 验证脚本，直接检验上面那句"验证目标" |

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填入你的 DEEPSEEK_API_KEY（调试阶段默认用DeepSeek）
```

把你的小说原文（单个txt，按"第一章/第1章/Chapter 1"，或"分隔线+编号"如 `------------` 换行 `001 标题` 分章）放进 `chapters/` 目录，比如 `chapters/my_novel.txt`。

```bash
python main.py --input chapters/my_novel.txt
```

调试时只想跑前2章，加 `--limit 2`。

跑完后会生成：
- `memory.json` —— 逐章成长的Memory
- `translations/chapter_01.txt` ... —— 译文
- `qa_report.json` —— 每章的QA报告

### 定稿模式（`--revise`）

默认流程 QA 只**发现**问题、留在报告里等你自己改。加 `--revise` 后进入闭环：QA 挑错 → 按清单修订 → 复检，最多 2 轮，直接产出定稿。

```bash
python main.py --input chapters/my_novel.txt --limit 1 --revise
```

- 只修 QA 点名的问题（术语/称呼不一致、设定冲突），不重译、不润色、不动没被点名的句子
- `translations/chapter_01.txt` 是**改过的定稿**；`qa_report.json` 存的是**最终**那次 QA 状态
- 有界（2 轮）是为了防止 QA 判官噪音导致死循环；2 轮后仍有残留会输出当前最好结果并保留残留

不想污染项目现有文件时，可把输出重定向到临时路径：

```bash
python main.py --input chapters/my_novel.txt --limit 1 --revise \
  --memory-path /tmp/ch1_memory.json --output-dir /tmp/ch1_out --qa-report /tmp/ch1_qa.json
```

### 对照实验（`--ab-test`）

验证"Memory 到底有没有用"：每章同时跑**关闭 Memory** 和 **开启 Memory** 两版翻译 + QA，两版共用同一份 Memory 做判定基准，输出对比报告。

```bash
python main.py --input chapters/my_novel.txt --ab-test
```

- 译文分别写到 `translations/no_memory/` 和 `translations/with_memory/`
- 对比报告写到 `ab_test_report.json`（`--ab-report` 可改路径）
- 注意：对照实验**不做**自动修订（否则两版都被洗干净就无法比较），`--revise` 只在普通模式生效

## 多语言（`--target-lang`）

默认译成英文。加 `--target-lang` 可换目标语言，目前已登记 **en（英）/ ar（阿拉伯）/ es（西班牙）**：

```bash
python main.py --input chapters/my_novel.txt --target-lang ar
```

为什么这个架构适合多语言：Extractor「**只理解，不翻译**」，所以 Memory 里
`characters/locations/organizations/timeline/state_log/summary` 都是**语言无关**的，一份就够所有语言用、不用重跑理解。真正跟语言绑定的只有 `glossary`（术语译名）和译文本身。因此：

- **一份语言无关的理解 + 每个目标语言各一份 glossary**。跑第二种语言时，理解直接复用（`state_log` 不会被重复计数），只为新语言补 glossary + 出译文。
- 译文按语言分目录：`translations/<lang>/chapter_XX.txt`；QA 报告 `qa_report_<lang>.json`。
- `memory.json` 里 `glossary` 变成 `{lang: {术语: 译文}}`。旧的单语言 `memory.json` **首次运行时自动迁移**（老的扁平 glossary 归入 `"en"`），无需手动改。

### 加一门新语言（插口在 `languages.py`）

新增语言只动一个文件：在 `languages.py` 的 `LANGUAGES` 里加一条 `Language`，声明语言名、章节标题词（Chapter/الفصل/Capítulo）、输出归一化（拉丁字母目标去罗马字长音符，其他用 identity）等。**可选**再放一份 `seed_glossary_<code>.json` 权威术语种子（没有也能跑，靠 Extractor 自动提议译名）。

西班牙语插口已登记好，直接 `--target-lang es` 即可跑；想要更稳的术语一致性，补一份 `seed_glossary_es.json`。阿拉伯语已附带 `seed_glossary_ar.json`（核心人名/地名/组织）。

> 注意：残留检测目前按"译文里是否残留中文"判漏译（源语言固定中文，目标 en/ar/es 都不是 CJK，成立）。若将来要加日语/韩语这类 CJK 目标，需在 `languages.py` 里换成按"源文特有片段"检测——那里留了说明。

## 验证核心假设

```bash
python verify.py --lang ar          # 验证某个目标语言（默认 en）
```

会直接告诉你两件事：
1. State变化历史是否被完整保留（比如某人物境界变化两次，历史里是否真的有两条记录，而不是只剩最后一次）
2. 第一章出现的术语，是否在最后一章的译文里被正确复用（证明Translator真的没有"重新理解全文"，而是依赖Memory）

## 刻意没做的事（对应架构讨论的共识）

- 没有拆成六个Memory文件 —— 现在没有数据支撑拆分，一个`memory.json`够用
- 没有用LangGraph —— 这是纯顺序流程，for循环足够诚实
- 没有把四步包装成Agent类 —— 它们是函数，没有自主决策能力
- 没有用Pydantic锁死Memory schema —— 先看真实数据长什么样
- 没有做State迁移合法性校验（比如"死亡后不能复活"这类规则）—— 这是第二阶段的问题

如果你发现自己想往这些方向加东西，先问一句：现在有具体的、跑出来的问题需要它解决吗？还是"觉得以后可能用得上"？后者是过早优化的信号。

## 换模型

调试阶段默认用DeepSeek（便宜，API兼容OpenAI格式）。`.env`里改`LLM_PROVIDER`/`LLM_MODEL`即可，不用改代码。以后要接入OpenRouter或Azure，在`llm_client.py`里新增一个实现`LLMClient`接口的类，然后在`get_client()`里切换分支。

**翻译和 QA 可以用不同模型。** 翻译/抽取走便宜的 DeepSeek，QA 判官可单独换更强的模型（DeepSeek 做判官噪音大、易跑偏）。在 `.env` 里加：

```bash
QA_LLM_PROVIDER=openai
QA_LLM_MODEL=gpt-4o
```

不配 `QA_LLM_PROVIDER` 时，QA 自动回退用和翻译一样的 DeepSeek。接口已留好，业务代码不用动。

## 文档 / 实验记录

这个项目从"写 Demo"转向"做实验"，所以记录方式也变了——比起"今天写了多少代码"，更重要的是"今天验证了哪个假设"。

| 位置 | 作用 |
|---|---|
| `CHANGELOG.md` | 只记**改了什么**（v0.1 → …）。为什么改、有没有效看实验记录 |
| `docs/experiments/EXP-XXX-*.md` | **最重要的目录**。每个实验一份：目的/假设/修改/结果/结论。用 `_TEMPLATE.md` 起草 |
| `docs/research_log.md` | 研究日记，每天一两句：发现了什么、猜测、下一步 |
| `benchmark/benchmark.md` | 固定基准（章节/模型/指标），**冻结不改**，实验之间才可比 |
| `prompts/<角色>/vN.txt` | prompt 版本快照。改 prompt 时新建 `vN+1.txt`，**不覆盖**旧版本 |

约定：每次只做一个实验、一份记录、编号递增；诚实记录（包括"方向相反""样本太小不能下结论"——反例最值钱）；基准不要为了让数字好看而改。
