"""
workflow_reviser.py

Workflow 5: Reviser（修订）

拿到QA挑出的问题后，按问题清单去修订译文，产出定稿。

刻意的边界（很重要）：
- 只修QA明确列出的那些问题（术语/称呼不一致、设定冲突），不重新翻译整章、
  不润色文风、不改动没被点名的句子 —— 越少改动，越不容易引入新问题。
- 修订依据Memory里已确立的译法（canonical译名），把不一致的地方统一过去。
- 只输出修订后的完整译文本身，不输出任何解释。

这一步只在"要定稿"的普通流程里用（--revise），A/B对照实验绝不能用它——
否则两组译文都被修干净，就无法比较Memory到底有没有用了。
"""

import json
from typing import Optional

from llm_client import LLMClient
from languages import Language, find_untranslated_source
from memory_store import MemoryStore

# 残留源语言（中文）检测统一收敛到 languages.py。这里保留旧名 find_untranslated_cjk
# 作为别名，避免调用方大改；语义就是"译文里没翻干净的源语言片段"。
find_untranslated_cjk = find_untranslated_source


def _reviser_system_prompt(lang: Language) -> str:
    return f"""你是一个译文修订员。
你会拿到：一章的{lang.zh_name}译文、一份问题清单、以及Memory（术语库/人物，key是中文原文）。

你的唯一任务：把清单里列出的问题逐一改好，产出修订后的完整译文。

清单里的问题可能是这几类：
- 术语/人物称呼的{lang.endonym}译法不一致、与设定冲突 → 统一到 Memory 里已确立的译法。
- 语法错误 / 生硬直译 / 前后矛盾 → 把被点名的那处改写通顺、改到自洽（这类允许改写该片段本身）。

严格规则：
- 只改清单点名的问题；有 quote 字段的，就精确定位到那段文字去改。
- 涉及人名/术语时，一律用 Memory 里已确立的{lang.endonym}译法，全章保持同一种写法。
- 除被点名处外，不要重译、不要润色、不要改动其他句子和文风。
- 不要新增或删减剧情内容。
- 只输出修订后的完整译文正文，不要输出任何解释、注释、markdown或JSON。
"""


def revise_translation(
    client: LLMClient,
    memory: MemoryStore,
    chapter_index: int,
    translated_text: str,
    issues: list[dict],
    lang: Language,
    chapter_text: Optional[str] = None,
) -> str:
    """
    issues为空时无需修订，直接原样返回。
    """
    if not issues:
        return translated_text

    memory_context = (
        memory.relevant_context_string(chapter_text, lang.code)
        if chapter_text is not None
        else memory.as_context_string(lang.code)
    )
    issues_text = json.dumps(issues, ensure_ascii=False, indent=2)

    user_prompt = f"""Memory（术语/人物已确立的{lang.endonym}译法，供统一时参照）：
{memory_context}

---

QA发现的问题清单（逐一改好）：
{issues_text}

---

第{chapter_index}章当前译文（在此基础上修订）：
{translated_text}
"""
    # 修订是"照清单改词"的确定性任务，用低温度让改动更克制、可复现。
    return client.complete(_reviser_system_prompt(lang), user_prompt, temperature=0.1)
