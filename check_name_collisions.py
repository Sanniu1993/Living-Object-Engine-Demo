"""
防呆检查：扫出"多个不同的源文名 → 同一个英文名"的情况（撞名）。

动机（EXP-008 的教训）：曾把两个不同角色（大和=Yamato 木遁孩子、日向天藏=日向族长）
错误合并成同一个英文名 Tenzo，污染了 glossary 和多章译文。这类"人工别名注入"的错误，
一致性机制和判官都抓不到——但它是确定性可查的：同一英文名被多个源文 key 指向，就值得人工确认。

用法：项目根目录 `python check_name_collisions.py`
输出：每个"被多个源文名共用的英文名"及其源文 key，供人工判断"是真别名还是误合并"。
"""

import json
import os
from collections import defaultdict

memory_path = os.environ.get("MEMORY_PATH", "memory.json")
lang = os.environ.get("LANG_CODE", "en")   # glossary 现在按语言分区，默认查英文那份
m = json.load(open(memory_path, encoding="utf-8"))
glossary = m.get("glossary", {}).get(lang, {})

en_to_src = defaultdict(list)
for zh, en in glossary.items():
    en_to_src[(en or "").strip()].append(zh)

collisions = {en: srcs for en, srcs in en_to_src.items() if len(srcs) > 1 and en}

if not collisions:
    print(f"✓ 无撞名（{lang}）：每个译名只对应一个源文名。")
else:
    print(f"⚠ [{lang}] 发现 {len(collisions)} 个译名被多个源文名共用，请逐一确认是'真别名(同一实体)'还是'误合并(不同实体)'：\n")
    for en, srcs in sorted(collisions.items()):
        print(f"  '{en}'  ←  {' / '.join(srcs)}")
    print("\n提示：形近变体(如 天藏/天蔵)通常是同一实体的正常别名；")
    print("      语义不同的(如 大和 vs 日向天藏)若共用一个名，多半是误合并，要拆开。")
