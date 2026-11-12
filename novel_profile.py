"""
novel_profile.py

"一本书一个 profile"：把和具体小说绑定的东西（种子词表、成语表、本书特有的译法备注、
lint 确认修正映射）从引擎里剥出来，放进一个目录：

    examples/<book>/profile.json
    examples/<book>/seed_glossary_en.json ...

引擎本身（languages.py + workflow_*）只保留语言级、和书无关的规则。
不传 --profile 时引擎照样能跑：没有种子，glossary 全靠 Extractor 逐章提议、Memory 逐章增长。

profile.json 结构（所有字段可选，路径相对于 profile 目录）：
{
  "name": "...",
  "description": "...",
  "languages": {
    "<lang code>": {
      "seed_glossary": "seed_glossary_en.json",   # {中文术语: 目标语译名}
      "seed_idioms":   "seed_idioms_ar.json",     # {中文成语/梗: 目标语地道说法}
      "lint_rules":    "lint_ar.json",            # {"replace": {wrong: right}}
      "translator_notes": ["- 本书特有的译法提示", "..."],   # 追加到语言级 notes 之后
      "title_notes":      ["- ..."]
    }
  }
}
"""

import dataclasses
import json
import os
from typing import Optional

from languages import Language


def _join(notes) -> str:
    if not notes:
        return ""
    if isinstance(notes, str):
        return notes
    return "\n".join(notes)


def _merge_notes(base: str, extra: str) -> str:
    return "\n".join(s for s in (base, extra) if s)


def apply_profile(lang: Language, profile_dir: Optional[str]) -> Language:
    """返回叠加了 profile 的新 Language（原对象不变）。profile_dir 为空则原样返回。"""
    if not profile_dir:
        return lang
    path = os.path.join(profile_dir, "profile.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到 profile：{path}")
    with open(path, "r", encoding="utf-8") as f:
        profile = json.load(f)

    cfg = profile.get("languages", {}).get(lang.code, {})

    def resolve(key: str) -> str:
        rel = cfg.get(key)
        return os.path.join(profile_dir, rel) if rel else ""

    return dataclasses.replace(
        lang,
        seed_file=resolve("seed_glossary"),
        idiom_seed_file=resolve("seed_idioms"),
        lint_rules_file=resolve("lint_rules"),
        translator_notes=_merge_notes(lang.translator_notes, _join(cfg.get("translator_notes"))),
        title_notes=_merge_notes(lang.title_notes, _join(cfg.get("title_notes"))),
    )
