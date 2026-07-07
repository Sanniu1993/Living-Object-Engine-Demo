"""
lint.py — 确定性译文体检（免费、每次都跑、结果稳定不抖）

定位（对应"能确定性判的别用 LLM"）：有一类错误确定性可判，不该花钱、也不该靠会抖的判官——
- 残留源语言（中文）/ 夹带的外语（英文）token
- 已确认的方言泄漏 / 反复出错的固定短语（直接替换修掉）
- 疑似人名污染：两个已知名字揉成一个（如 ساروتوبي 头 + أوروتشيمارو 尾 = ساروتشيمارو）

这些收进 lint，判官只留给真正需要语感的活（语法/直译/矛盾）。
lint_<lang>.json 的 replace 映射是一个"确认修正"的 Living Object：
终校每发现一类新硬伤就加一条 wrong->right，以后每次自动根治、零成本、不复发。

用法：python lint.py --lang ar [--fix]
"""

import argparse
import json
import os
import re

from languages import get_language, find_untranslated_source
from memory_store import MemoryStore

_LATIN_RE = re.compile(r"[A-Za-z]{2,}")          # 拉丁字母串
_ARABIC_RE = re.compile(r"[؀-ۿ]{2,}")  # 阿拉伯字母串
_TOKEN_RE = re.compile(r"[^\s«».,،؛:!؟\"'()\[\]]+")


def _rules_path(lang_code: str) -> str:
    return f"lint_{lang_code}.json"


def load_rules(lang_code: str) -> dict:
    path = _rules_path(lang_code)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def apply_fixes(text: str, lang_code: str) -> tuple[str, int]:
    """确定性替换：把 replace 映射（确认的 wrong->right）全改掉。返回 (新文本, 改动次数)。"""
    n = 0
    for wrong, right in load_rules(lang_code).get("replace", {}).items():
        c = text.count(wrong)
        if c:
            text = text.replace(wrong, right)
            n += c
    return text, n


def _name_stems(memory: MemoryStore, lang_code: str, minlen: int = 5) -> set:
    """从 glossary 取所有足够长的名字词，作为人名污染检测的基准。"""
    stems = set()
    for val in memory.glossary_for(lang_code).values():
        for w in str(val).split():
            w = w.strip("«».,،؛:!؟\"'()")
            if len(w) >= minlen:
                stems.add(w)
    return stems


def find_name_blends(text: str, memory: MemoryStore, lang_code: str) -> list[str]:
    """
    疑似人名污染：某 token 不是任何已知名字，却同时以某已知名字的词头(≥5)开头、
    以另一个【不同】名字的词尾(≥5)结尾。只报高置信的（token≥8），尽量不误伤。
    """
    stems = _name_stems(memory, lang_code)
    if not stems:
        return []
    seen, out = set(), []
    for tok in set(_TOKEN_RE.findall(text)):
        if len(tok) < 8 or tok in stems:
            continue
        h, t = tok[:5], tok[-5:]
        head_names = {s for s in stems if s[:5] == h}
        tail_names = {s for s in stems if s[-5:] == t}
        # 头尾都命中，且来自不同名字（非同一名字的正常变形）→ 判为疑似揉名
        if head_names and tail_names and not (head_names & tail_names):
            if tok not in seen:
                seen.add(tok)
                out.append(tok)
    return out


def find_foreign(text: str, lang) -> list[str]:
    """
    夹带的"外来脚本"token（按目标语脚本自适应）：
    - 非拉丁目标(阿语)：残留整串拉丁字母(英文)才是外来，如漏译的 Subjects/sake。
    - 拉丁目标(英/西)：英文本就是拉丁，不能当外来；此时反过来查残留阿拉伯字母。
    源语言中文(CJK)始终另由 find_untranslated_source 检测，不在此列。
    """
    pattern = _ARABIC_RE if lang.latin_script else _LATIN_RE
    seen, out = set(), []
    for m in pattern.findall(text):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def run_lint(text: str, memory: MemoryStore, lang) -> list[tuple]:
    """纯检测（不改文本）。返回 [(类型, [命中项]), ...]。"""
    findings = []
    cjk = find_untranslated_source(text)
    if cjk:
        findings.append(("残留中文", cjk))
    foreign = find_foreign(text, lang)
    if foreign:
        findings.append(("夹带外语", foreign))
    # 人名污染的头/尾启发式在拉丁文里易误伤(普通英文词碰巧撞名字头尾，如 standing)，
    # 只在非拉丁目标(音译名很独特)启用；拉丁目标的名字错交给流畅度判官。
    if not lang.latin_script:
        blends = find_name_blends(text, memory, lang.code)
        if blends:
            findings.append(("疑似人名污染", blends))
    hit = [w for w in load_rules(lang.code).get("replace", {}) if w in text]
    if hit:
        findings.append(("已知错误短语(可--fix自动改)", hit))
    return findings


def main():
    parser = argparse.ArgumentParser(description="确定性译文体检")
    parser.add_argument("--lang", default="ar")
    parser.add_argument("--memory-path", default="memory.json")
    parser.add_argument("--dir", default=None, help="译文目录，默认 translations/<lang>")
    parser.add_argument("--fix", action="store_true", help="对命中 replace 映射的地方自动替换并写回")
    args = parser.parse_args()

    lang = get_language(args.lang)
    memory = MemoryStore(args.memory_path)
    d = args.dir or os.path.join("translations", lang.code)
    files = sorted(f for f in os.listdir(d) if f.startswith("chapter_") and f.endswith(".txt"))

    total = 0
    for fn in files:
        path = os.path.join(d, fn)
        text = open(path, encoding="utf-8").read()
        if args.fix:
            text, n = apply_fixes(text, lang.code)
            if n:
                open(path, "w", encoding="utf-8").write(text)
                print(f"{fn}: 自动修正 {n} 处")
        findings = run_lint(text, memory, lang)
        for typ, items in findings:
            total += len(items)
            print(f"{fn} ⚠ {typ}: {' / '.join(map(str, items))[:100]}")
    print(f"\n共 {total} 处待处理" + ("（已应用可自动修的替换）" if args.fix else "（加 --fix 自动修可修项）"))


if __name__ == "__main__":
    main()
