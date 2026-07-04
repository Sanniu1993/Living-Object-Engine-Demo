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
from memory_store import MemoryStore


TRANSLATOR_SYSTEM_PROMPT = """你是一个专业的中译英小说译者。
你只能看到当前这一章的原文，看不到其他章节的原文 ——
所有关于人物、地点、专有名词译法的历史信息，都必须从下面提供的Memory中获取。

翻译要求：
- 术语翻译必须严格遵循Memory中glossary里已有的译法，保持一致性。
- 人物称呼、境界等级的翻译要参考Memory中characters里的既有信息。
- 只输出翻译结果本身，不要输出任何解释或说明。
"""


def translate_chapter(
    client: LLMClient,
    memory: Optional[MemoryStore],
    chapter_index: int,
    chapter_text: str,
) -> str:
    memory_context = (
        memory.as_context_string()
        if memory is not None
        else "（无——本次不提供Memory，术语和人物译法请自行判断）"
    )
    user_prompt = f"""Memory（人物/地点/术语库/时间线，供翻译时保持一致性）：
{memory_context}

---

请翻译第{chapter_index}章：
{chapter_text}
"""
    return client.complete(TRANSLATOR_SYSTEM_PROMPT, user_prompt, temperature=0.3)
