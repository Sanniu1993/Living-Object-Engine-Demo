"""
workflow_translator.py

Workflow 3: Translator

核心约束（整个架构的灵魂）：
Translator不能重新分析整本小说，必须只消费Memory + 当前章节。
这里的实现严格遵守这一点 —— prompt里只传入当前章节原文和Memory，
不会、也不能传入其他章节的原文。

memory传None时（对照实验用，验证"Memory到底有没有用"），
就完全不给术语/人物历史，只靠模型当章自己判断译法 —— 这是刻意的、
不是bug，用于和"传入真实Memory"的结果做对比。
"""

from typing import Optional

from llm_client import LLMClient
from languages import Language
from memory_store import MemoryStore


def _translator_system_prompt(lang: Language) -> str:
    return f"""你是一个专业的中译{lang.zh_name}小说译者。
你只能看到当前这一章的原文，看不到其他章节的原文 ——
所有关于人物、地点、专有名词译法的历史信息，都必须从下面提供的Memory中获取。

翻译要求：
- 目标语言是{lang.endonym}，译文必须全部使用{lang.endonym}，不得残留中文，也不要夹杂其他语言。
- 术语翻译必须严格遵循Memory中glossary里已有的译法，保持一致性。
- 人物称呼、境界等级的翻译要参考Memory中characters里的既有信息。
- 只输出翻译结果本身，不要输出任何解释或说明。

译法规范（避免直译/误译）：
- 成语、歇后语、惯用语不要按字面直译，要译成{lang.endonym}读者能看懂的对应说法。
- 专有名词若Memory里已有译法一律沿用；没有的按该语言习惯统一音译或意译，并前后一致。
{lang.translator_notes}
"""


def _title_system_prompt(lang: Language) -> str:
    return f"""你是小说章节标题翻译。把中文章节标题译成自然、有吸引力的{lang.endonym}章节标题。

要求：
- 目标语言是{lang.endonym}，标题必须全部使用{lang.endonym}，绝不残留中文。
- 人物/术语必须用下面Memory里已确立的译法。
- 保留开头的章节序号，译成 "{lang.chapter_label} N: ..." 的形式（如 "031 ..." → "{lang.chapter_label} 31: ..."）。
- 删掉中文网文的作者话（如"求月票""加更""二合一大章"之类），不要译进标题。
- 成语/网络梗不要字面直译，用{lang.endonym}读者能懂的说法。
- 只输出翻译后的标题这一行，不要引号、不要解释。
{lang.title_notes}
"""


def translate_title(client: LLMClient, memory: MemoryStore, title: str, lang: Language) -> str:
    user_prompt = f"""Memory（术语/人名参考，务必沿用其中的{lang.endonym}译法）：
{memory.compact_context_string(lang.code)}

---

请翻译这个章节标题：
{title}
"""
    return client.complete(_title_system_prompt(lang), user_prompt, temperature=0.2).strip()


def translate_chapter(
    client: LLMClient,
    memory: Optional[MemoryStore],
    chapter_index: int,
    chapter_text: str,
    lang: Language,
) -> str:
    memory_context = (
        memory.compact_context_string(lang.code)
        if memory is not None
        else "（无——本次不提供Memory，术语和人物译法请自行判断）"
    )
    user_prompt = f"""Memory（人物/地点/术语库/时间线，供翻译时保持一致性）：
{memory_context}

---

请翻译第{chapter_index}章：
{chapter_text}
"""
    return client.complete(_translator_system_prompt(lang), user_prompt, temperature=0.3)
