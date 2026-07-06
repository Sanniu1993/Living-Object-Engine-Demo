"""
workflow_extractor.py

Workflow 2: Memory Extractor

只负责"理解"，不负责翻译。
输入：当前章节原文 + 已有Memory。
输出：从Memory里新增/更新的人物、地点、事件、术语，直接写回MemoryStore。

这是一个函数，不是一个Agent类 —— 它没有自主决策、没有工具调用循环，
就是一次结构化信息抽取，函数是最诚实的表达方式。
"""

from llm_client import LLMClient
from languages import Language
from memory_store import MemoryStore


def _extractor_system_prompt(lang: Language) -> str:
    """
    抽取器的产出分两类：
    - 理解（characters/locations/organizations/timeline/summary）是**语言无关**的，
      一份就够所有目标语言用；
    - glossary（专有名词译名）是**目标语言特定**的，按当前目标语言给建议译法。
    """
    return f"""你是一个小说内容结构化抽取器。
你的任务是阅读一章小说原文，结合已有的Memory（人物/地点/组织/术语库），
找出这一章里"新增的"或"发生变化的"信息。

只输出JSON，不要markdown代码块，不要任何解释性文字。

输出格式：
{{
  "characters": {{
    "人物名": {{"境界": "...", "关系": "...", "其他属性": "..."}}
  }},
  "locations": {{
    "地点名": {{"描述": "..."}}
  }},
  "organizations": {{
    "组织名": {{"描述": "..."}}
  }},
  "glossary": {{
    "专有名词": "建议的{lang.zh_name}翻译"
  }},
  "timeline_events": [
    {{"description": "事件描述", "involved_entities": ["人物名1", "地点名1"]}}
  ],
  "summary_update": "结合本章内容，对整个故事摘要的更新（完整的新摘要，不是增量）"
}}

规则：
- 只报告本章实际出现或变化的信息，不要凭空推测。
- characters/locations/organizations/timeline/summary 用中文填写（这些是语言无关的理解，供各语言共用）。
- glossary 的 value 一律用{lang.endonym}给出专有名词译名（人名/地名/组织/招式）。
- characters/locations/organizations 里只需要给出属性字典，
  不需要判断这是不是"变化"—— 上层代码会自动处理新增/合并/记录变化历史。
- 如果某个类别本章没有新信息，返回空对象/空数组即可。
"""


def extract_memory(
    client: LLMClient,
    memory: MemoryStore,
    chapter_index: int,
    chapter_text: str,
    lang: Language,
):
    """
    幂等分两层：
    - 理解（语言无关）：按 extracted_chapters 判，全局只抽一次。
    - glossary（每语言）：按 glossary_extracted[lang] 判。这样换第二种语言时，
      理解不会被重复 append（否则 state_log 会重复计数），但仍会为新语言补上 glossary。
    """
    understanding_done = memory.is_chapter_extracted(chapter_index)
    glossary_done = memory.is_glossary_extracted(chapter_index, lang.code)
    if understanding_done and glossary_done:
        return None

    user_prompt = f"""已有Memory（供你参考避免重复抽取已知信息）：
{memory.compact_context_string(lang.code)}

---

第{chapter_index}章原文：
{chapter_text}
"""

    result = client.complete_json(_extractor_system_prompt(lang), user_prompt)

    # 理解部分只在首次（语言无关）写入，避免第二种语言重复 append。
    if not understanding_done:
        for name, attrs in result.get("characters", {}).items():
            memory.upsert_character(name, attrs, chapter_index)

        for name, attrs in result.get("locations", {}).items():
            memory.upsert_location(name, attrs, chapter_index)

        for name, attrs in result.get("organizations", {}).items():
            memory.upsert_organization(name, attrs, chapter_index)

        for event in result.get("timeline_events", []):
            memory.add_timeline_event(
                chapter=chapter_index,
                description=event.get("description", ""),
                involved_entities=event.get("involved_entities", []),
            )

        summary_update = result.get("summary_update")
        if summary_update:
            memory.update_summary(summary_update)

        memory.mark_chapter_extracted(chapter_index)

    # glossary 按目标语言分别写入。
    if not glossary_done:
        glossary = result.get("glossary", {})
        if glossary:
            memory.add_glossary_terms(glossary, lang.code)
        memory.mark_glossary_extracted(chapter_index, lang.code)

    return result
