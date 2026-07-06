"""
verify.py

对应我们在架构讨论里定下的、唯一重要的验证标准，不做别的事。

验证点1：Memory是否真的在成长而非被覆盖？
  检查 state_log 里是否存在同一个entity_id的多条记录（说明状态变化被
  完整保留，而不是只剩最后一次）。

验证点2：Translator是否真的只靠Memory就还原了早期章节的专有名词？
  检查 glossary 是否覆盖了第1章出现的术语，并且这些术语在最后一章的
  译文里是否被正确使用（而不是被重新发明了一套新译法）。

这不是自动化测试框架，就是一个跑一次看结果的脚本 —— MVP阶段不需要更多。

用法：
  python verify.py --lang en          # 译文默认在 translations/<lang> 下
  python verify.py --lang ar --translations-dir translations/ar
"""

import argparse
import json
import os
import re


def verify_state_growth(memory: dict):
    print("\n--- 验证点1：State是否完整保留多次变化 ---")
    state_log = memory.get("state_log", [])
    if not state_log:
        print("  state_log为空。可能是这批章节里没有人物属性发生变化，"
              "也可能是Extractor没能识别出变化。建议检查具体章节内容。")
        return

    by_entity = {}
    for entry in state_log:
        by_entity.setdefault(entry["entity_id"], []).append(entry)

    multi_change_entities = {k: v for k, v in by_entity.items() if len(v) > 1}

    print(f"  共记录 {len(state_log)} 条State变化，涉及 {len(by_entity)} 个entity。")
    if multi_change_entities:
        print(f"  其中 {len(multi_change_entities)} 个entity有多次状态变化，历史被完整保留：")
        for entity_id, entries in multi_change_entities.items():
            chain = " -> ".join(f"ch{e['chapter']}:{e['old_value']}→{e['new_value']}" for e in entries)
            print(f"    {entity_id}: {chain}")
    else:
        print("  暂未出现同一entity的多次状态变化。"
              "这本身不代表失败，可能是这10章里角色状态变化确实较少。")


def verify_glossary_consistency(memory: dict, translations_dir: str, lang: str):
    print(f"\n--- 验证点2：早期章节术语是否在后续翻译中被正确复用（{lang}）---")
    # glossary 现在按语言分区：{lang: {术语: 译文}}。取当前语言那一份。
    glossary = memory.get("glossary", {}).get(lang, {})
    if not glossary:
        print(f"  {lang} 的 glossary 为空，无法验证。")
        return

    files = sorted(
        f for f in os.listdir(translations_dir) if f.startswith("chapter_") and f.endswith(".txt")
    )
    if not files:
        print(f"  {translations_dir} 下没有找到译文文件。")
        return

    last_chapter_path = os.path.join(translations_dir, files[-1])
    with open(last_chapter_path, "r", encoding="utf-8") as f:
        last_text = f.read()

    print(f"  Glossary共 {len(glossary)} 条术语。检查最后一章（{files[-1]}）是否复用了这些译法：")
    matched, missing = [], []
    for term, translation in glossary.items():
        # 简单子串匹配即可，MVP阶段不需要更复杂的NLP比对
        if translation and translation.lower() in last_text.lower():
            matched.append(term)
        else:
            missing.append(term)

    print(f"    命中: {len(matched)} / {len(glossary)}")
    if missing:
        print(f"    未在最后一章出现的术语（可能是该章本身未涉及，也可能是译法不一致）：")
        for term in missing[:10]:
            print(f"      - {term} -> {glossary[term]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory-path", default="memory.json")
    parser.add_argument("--lang", default="en", help="要验证的目标语言（en/ar/es...）")
    parser.add_argument(
        "--translations-dir",
        default=None,
        help="译文目录，默认 translations/<lang>",
    )
    args = parser.parse_args()

    translations_dir = args.translations_dir or os.path.join("translations", args.lang)

    with open(args.memory_path, "r", encoding="utf-8") as f:
        memory = json.load(f)

    verify_state_growth(memory)
    verify_glossary_consistency(memory, translations_dir, args.lang)


if __name__ == "__main__":
    main()
