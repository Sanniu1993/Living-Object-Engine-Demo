"""
workflow_qa.py

Workflow 4: QA

读取翻译结果 + Memory，检查：
- 专有名词一致性（是否严格遵循glossary）
- 人物称呼一致性
- 明显的设定冲突（比如Memory里显示某人已死，译文却让TA说话）

输出QA报告（dict），不做自动修复 —— MVP阶段只要能"发现"问题即可，
自动修复属于下一阶段的功能。

针对便宜模型（deepseek）做了几处防炸设计（对应第4章QA被撑爆的教训）：
- prompt硬性要求"只报问题、禁止复述一致项、最多20条"，从源头压住输出长度；
- Memory只喂当前章节相关条目（见 MemoryStore.relevant_context_string），
  不再把随章节膨胀的完整Memory全塞进去；
- max_tokens收紧，够20条issue即可；
- 解析失败自动用更短更硬的prompt重试一次，再不行才算失败。
"""

from typing import Optional

from llm_client import LLMClient
from memory_store import MemoryStore


MAX_ISSUES = 20
# 上限放宽：推理模型（如 GPT-5 mini）会先花 token 做内部推理再输出，
# 2048 太小会被推理吃光导致返回空。8192 给推理留足配额，同时仍能兜住 DeepSeek 跑飞。
QA_MAX_TOKENS = 8192
QA_RETRY_MAX_TOKENS = 4096

# QA只允许这三类。便宜模型有时会自创"逻辑矛盾"之类的类别跑去点评剧情，
# prompt已明令禁止，这里再做一次代码兜底：非这三类的issue直接丢弃。
ALLOWED_TYPES = {"术语不一致", "称呼不一致", "设定冲突"}


QA_SYSTEM_PROMPT = """你是一个翻译质量检查员。
你会拿到一章的英文译文和当前的Memory（人物/术语库/时间线/State记录，key是中文原文）。

重要前提，不要弄反：
Memory里的key是中文原文（如"猿飞日斩"），译文本来就该译成英文（如"Hiruzen Sarutobi"），
这不是问题。你要检查的是"译文用的英文译法，是否和该术语/人物在Memory里已确立的英文译法一致"。
第一次出现、还没有历史英文译法可参照的，不算问题。

你只能检查以下三类问题，除此之外一律不报：
1. 术语不一致：同一中文术语的英文译法与Memory已有先例不同。
2. 称呼不一致：同一人物英文称呼前后不一致，或与Memory已确立译名不符。
3. 设定冲突：译文与Memory的State记录矛盾（如某角色已死却仍行动）。

检查范围硬约束（必须遵守）：
- 禁止评价剧情合理性。
- 禁止评价角色动机、行为是否明智、目标是否冲突。
- 禁止新增上述三类之外的任何类别（例如"逻辑矛盾""情节问题"等一律不许出现）。
- 如果一个问题不属于上述三类，直接不要输出它。
- type字段只能是"术语不一致""称呼不一致""设定冲突"三者之一，不得填别的值。

以下属于正常小说写法，不算不一致，不要报（避免误报）：
- 用全名里的一部分（名 或 姓）来称呼，而非每次都用全名（如只写 "Asuma"/"Kakashi"，
  不必是 "Asuma Sarutobi"/"Kakashi Hatake"）——这是正常的。
- 用称谓/头衔指代人物（如把 Hiruzen Sarutobi 称作 "the Third Hokage"、"Lord Hokage"）。
- 仅大小写或单复数差异（如 "Uchiha clan" vs "Uchiha Clan"）。

注意区分：把一个完整的单名截断或改写，不算"简称"，属于不一致，要报
（如 "Orochimaru" 写成 "Orochi"、"Hiruzen" 写成 "Hiru"）。
只有出现"实质冲突"才算不一致：拼写不同、姓名顺序颠倒、用了完全不同的词，或漏词/改词导致术语变样
（如 glossary 是 "Military Police Force" 却写成 "Military Police"）。

严格输出规则（必须遵守）：
- 只输出发现的问题。没有问题就返回空数组。
- 禁止输出任何"一致/正确/无问题/不报告/已检查"之类的说明性条目。
- 不要逐条复述检查过程，不要解释推理过程。
- 最多返回20条issue，按severity从high到low排序，超过只保留最严重的20条。
- 只返回严格JSON，不要markdown代码块，不要JSON之外的任何文字。

输出格式（只有这一种）：
{"issues": [{"type": "术语不一致/称呼不一致/设定冲突", "description": "简短问题描述", "severity": "high/medium/low"}]}

没有发现问题时，返回：
{"issues": []}
"""


QA_RETRY_SYSTEM_PROMPT = """上一次输出无效（不是合法JSON或过长）。
请只返回严格JSON：{"issues":[...]}
最多10条issue，按severity从high到low排序。
每条只含 type / description / severity 三个字段，description一句话。
禁止输出"一致/无问题/不报告"之类说明，不要解释，不要markdown，不要JSON之外的任何文字。
"""


def run_qa(
    client: LLMClient,
    memory: MemoryStore,
    chapter_index: int,
    translated_text: str,
    chapter_text: Optional[str] = None,
) -> dict:
    """
    chapter_text（本章中文原文）用于把Memory裁剪到"本章相关条目"。
    不传则退回喂完整Memory（旧行为），但会更容易触发便宜模型的输出膨胀问题。
    """
    memory_context = (
        memory.relevant_context_string(chapter_text)
        if chapter_text is not None
        else memory.as_context_string()
    )
    user_prompt = f"""Memory（仅本章相关条目）：
{memory_context}

---

第{chapter_index}章译文：
{translated_text}
"""

    try:
        result = client.complete_json(
            QA_SYSTEM_PROMPT, user_prompt, temperature=0.1, max_tokens=QA_MAX_TOKENS
        )
    except ValueError:
        # 第一次输出不是合法JSON（便宜模型偶尔重复退化/被截断），换更短更硬的prompt重试一次。
        result = client.complete_json(
            QA_RETRY_SYSTEM_PROMPT, user_prompt, temperature=0.0, max_tokens=QA_RETRY_MAX_TOKENS
        )

    return _normalize_qa(result)


def _normalize_qa(result: dict) -> dict:
    """
    代码侧兜底：即使模型没排序或超量，也按severity从high到low截断到MAX_ISSUES条；
    passed直接由"issues是否为空"推导，不再依赖模型自报（模型经常报错）。
    """
    issues = result.get("issues", []) or []
    # 丢弃非三类的off-spec条目（如自创的"逻辑矛盾"剧情点评）。
    issues = [i for i in issues if i.get("type") in ALLOWED_TYPES]
    order = {"high": 0, "medium": 1, "low": 2}
    issues = sorted(issues, key=lambda i: order.get(i.get("severity", "low"), 3))[:MAX_ISSUES]
    return {"issues": issues, "passed": len(issues) == 0}
