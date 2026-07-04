"""
memory_store.py

Living Object的核心：Memory。

设计原则（对应我们讨论达成的共识）：
1. 单一 memory.json 文件，不拆分成六个文件。字段内部分区，
   等真实数据体积/更新频率明显失衡时再考虑拆分——现在没有数据支撑拆分。
2. Memory 只增长，不覆盖。所有更新操作都是"追加"或"合并"，
   从不用新值直接替换旧值。
3. State 作为独立的通用记录结构，字段设计上不含任何"小说"词汇，
   理论上可以原样迁移到法律案件/CRM/病历等场景：
       { entity_id, old_value, new_value, chapter, trigger_event }
   这是本项目里唯一一个「现在就要证明其跨行业通用性」的抽象。

MVP阶段不做的事（刻意排除）：
   - 不做状态迁移合法性校验（比如"死亡后不能复活"这种规则引擎）
   - 不做多文件拆分
   - 不用Pydantic锁死schema —— 先让数据自然长出形状
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional


MEMORY_SCHEMA_VERSION = 1


def _empty_memory() -> dict:
    return {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "summary": "",
        "characters": {},      # entity_id -> {attributes..., "state_history": [...]}
        "locations": {},       # entity_id -> {...}
        "organizations": {},   # entity_id -> {...}
        "glossary": {},        # 术语 -> 译文
        "timeline": [],        # 追加写入的事件列表，永不删除/覆盖
        "state_log": [],       # 全局State变化记录，跨entity类型共用同一结构
    }


class MemoryStore:
    """
    所有Workflow共享同一个MemoryStore实例（或同一个memory.json路径）。
    Workflow只应该调用这里暴露的方法来读写Memory，
    不应该在业务代码里直接操作dict结构 —— 这样以后换存储介质（比如换成数据库）
    只需要改这一个文件。
    """

    def __init__(self, path: str):
        self.path = path
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        else:
            self.data = _empty_memory()
            self._save()

    # ---------- 持久化 ----------

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # ---------- 读取（供Workflow消费，只读不改） ----------

    def as_dict(self) -> dict:
        return self.data

    def as_context_string(self) -> str:
        """
        供Translator/QA等Workflow拼接进prompt的精简上下文。
        MVP阶段直接把结构化Memory转成JSON字符串喂给模型，
        不做额外的摘要/裁剪 —— 10章体量不需要。
        """
        return json.dumps(self.data, ensure_ascii=False, indent=2)

    def relevant_context_string(self, chapter_text: str) -> str:
        """
        只挑出当前章节实际涉及的Memory条目，供QA使用。

        动机：Memory只增长（见文件顶部设计原则），到中后段characters/timeline/glossary
        会越滚越大。若把完整Memory全塞进QA的prompt，便宜模型（deepseek）会因输出过长
        而陷入重复退化、甚至JSON被截断——第4章QA失败正是这么来的。

        判断依据是"中文key/entity名是否出现在本章中文原文里"，因为Memory的key就是中文，
        而QA拿到的译文是英文、不好直接匹配。这样过滤是刻意从严：本章没出现的历史条目，
        对本章的一致性检查本来也用不上。
        """
        def mentioned(name: str) -> bool:
            return bool(name) and name in chapter_text

        characters = {k: v for k, v in self.data["characters"].items() if mentioned(k)}
        locations = {k: v for k, v in self.data["locations"].items() if mentioned(k)}
        organizations = {k: v for k, v in self.data["organizations"].items() if mentioned(k)}
        glossary = {k: v for k, v in self.data["glossary"].items() if mentioned(k)}

        relevant_entities = set(characters) | set(locations) | set(organizations)
        timeline = [
            e for e in self.data["timeline"]
            if any(ent in relevant_entities for ent in e.get("involved_entities", []))
        ]
        state_log = [
            s for s in self.data["state_log"] if s.get("entity_id") in relevant_entities
        ]

        view = {
            "summary": self.data.get("summary", ""),
            "characters": characters,
            "locations": locations,
            "organizations": organizations,
            "glossary": glossary,
            "timeline": timeline,
            "state_log": state_log,
        }
        return json.dumps(view, ensure_ascii=False, indent=2)

    # ---------- 写入：只增长，不覆盖 ----------

    def upsert_character(self, entity_id: str, attributes: dict, chapter: int):
        """
        新增或更新一个人物。
        - 全新人物：创建记录，记下首次出现章节。
        - 已存在人物：合并新属性（新字段补充，已有字段若有变化则走
          record_state_change 记录，而不是在这里静默覆盖）。
        """
        characters = self.data["characters"]
        now = datetime.now(timezone.utc).isoformat()

        if entity_id not in characters:
            characters[entity_id] = {
                "attributes": dict(attributes),
                "first_seen_chapter": chapter,
                "last_updated": now,
                "state_history": [],
            }
        else:
            record = characters[entity_id]
            record["last_updated"] = now
            for key, new_value in attributes.items():
                old_value = record["attributes"].get(key)
                if old_value is None:
                    # 全新字段，直接补充，不算State变化
                    record["attributes"][key] = new_value
                elif old_value != new_value:
                    # 已有字段发生变化 —— 这才是需要保留历史的State变化
                    record["attributes"][key] = new_value
                    self.record_state_change(
                        entity_type="character",
                        entity_id=entity_id,
                        field=key,
                        old_value=old_value,
                        new_value=new_value,
                        chapter=chapter,
                        trigger_event=None,
                    )

        self._save()

    def upsert_location(self, entity_id: str, attributes: dict, chapter: int):
        self._upsert_simple("locations", entity_id, attributes, chapter)

    def upsert_organization(self, entity_id: str, attributes: dict, chapter: int):
        self._upsert_simple("organizations", entity_id, attributes, chapter)

    def _upsert_simple(self, bucket: str, entity_id: str, attributes: dict, chapter: int):
        store = self.data[bucket]
        now = datetime.now(timezone.utc).isoformat()
        if entity_id not in store:
            store[entity_id] = {
                "attributes": dict(attributes),
                "first_seen_chapter": chapter,
                "last_updated": now,
            }
        else:
            record = store[entity_id]
            record["last_updated"] = now
            record["attributes"].update(attributes)
        self._save()

    def seed_glossary(self, terms: dict[str, str]):
        """
        注入权威术语表（种子）。

        与 add_glossary_terms 的"只增不改"刻意相反：种子是人工策划的 ground truth，
        应当覆盖 Extractor 之前的首次猜测——所以这里是"设置/覆盖"，不是"仅新增"。
        用于在跑之前给 Memory 一个高质量初始状态，让被冻结、被一致传播的译名从一开始就对。
        """
        glossary = self.data["glossary"]
        for term, translation in terms.items():
            glossary[term] = translation
        self._save()

    def add_glossary_terms(self, terms: dict[str, str]):
        """术语只增不改：如果术语已存在且译法不同，保留原有译法，
        避免QA阶段出现"同一术语前后翻译不一致"却又被静默改掉、无法追溯的情况。
        真正的译法冲突应该被QA阶段发现并报告，而不是在这里被覆盖掩盖。
        """
        glossary = self.data["glossary"]
        for term, translation in terms.items():
            if term not in glossary:
                glossary[term] = translation
        self._save()

    def add_timeline_event(self, chapter: int, description: str, involved_entities: list[str]):
        self.data["timeline"].append({
            "chapter": chapter,
            "description": description,
            "involved_entities": involved_entities,
        })
        self._save()

    def record_state_change(
        self,
        entity_type: str,
        entity_id: str,
        field: str,
        old_value: Any,
        new_value: Any,
        chapter: int,
        trigger_event: Optional[str] = None,
    ):
        """
        跨行业通用的State记录。字段结构不含任何行业词汇：
        entity_type/entity_id 指向"谁"，field/old_value/new_value 指向"什么变了"，
        chapter 指向"何时"，trigger_event 指向"为什么"。

        这条记录只追加，永不修改或删除 —— 这是验证"Memory能否完整保留
        多次状态变化"这一核心假设的关键机制。
        """
        self.data["state_log"].append({
            "entity_type": entity_type,
            "entity_id": entity_id,
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "chapter": chapter,
            "trigger_event": trigger_event,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        })
        self._save()

    def update_summary(self, new_summary: str):
        """
        Summary是唯一允许"整体替换"的字段，因为它本质上是滚动摘要，
        不是逐条记录。但即便如此，也不删除旧版本 —— 追加进history里，
        方便回溯每一章之后摘要是如何演变的。
        """
        if "summary_history" not in self.data:
            self.data["summary_history"] = []
        if self.data.get("summary"):
            self.data["summary_history"].append(self.data["summary"])
        self.data["summary"] = new_summary
        self._save()

    # ---------- 验证辅助：用于检查核心假设是否成立 ----------

    def get_state_history(self, entity_id: str) -> list[dict]:
        """取出某个entity的完整State变化历史，用于验证Memory是否真的没有丢数据。"""
        return [s for s in self.data["state_log"] if s["entity_id"] == entity_id]
