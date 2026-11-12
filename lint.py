"""
lint.py — 确定性译文体检（免费、每次都跑、结果稳定不抖）

定位（对应"能确定性判的别用 LLM"）：有一类错误确定性可判，不该花钱、也不该靠会抖的判官——
- 残留源语言（中文）/ 夹带的外语（英文）token
- 已确认的方言泄漏 / 反复出错的固定短语（直接替换修掉）
- 疑似人名污染：两个已知名字揉成一个（如 ساروتوبي 头 + أوروتشيمارو 尾 = ساروتشيمارو）

这些收进 lint，判官只留给真正需要语感的活（语法/直译/矛盾）。
profile 里的 lint_<lang>.json（replace 映射）是一个"确认修正"的 Living Object：
终校每发现一类新硬伤就加一条 wrong->right，以后每次自动根治、零成本、不复发。

用法：python lint.py --lang ar --profile examples/naruto [--fix]
"""

import argparse
import json
import os
import re

from languages import Language, get_language, find_untranslated_source
from novel_profile import apply_profile
from memory_store import MemoryStore

_LATIN_RE = re.compile(r"[A-Za-z]{2,}")          # 拉丁字母串
_ARABIC_RE = re.compile(r"[؀-ۿ]{2,}")  # 阿拉伯字母串
_TOKEN_RE = re.compile(r"[^\s«».,،؛:!؟\"'()\[\]]+")


def load_rules(lang: Language) -> dict:
    path = lang.lint_rules_file
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def apply_fixes(text: str, lang: Language) -> tuple[str, int]:
    """确定性替换：把 replace 映射（确认的 wrong->right）全改掉。返回 (新文本, 改动次数)。"""
    n = 0
    for wrong, right in load_rules(lang).get("replace", {}).items():
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


def _levenshtein(a: str, b: str, maxd: int = 2) -> int:
    """有界编辑距离：长度差已超 maxd 直接短路返回 maxd+1，否则标准 DP。"""
    if abs(len(a) - len(b)) > maxd:
        return maxd + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            cur.append(v)
            best = min(best, v)
        if best > maxd:      # 该行最小值已超上界，后面不可能更小
            return maxd + 1
        prev = cur
    return prev[-1]


_TYPO_STRIP = "«».,،؛:!؟?？;；\"'()-…“”‘’、"


def _norm_word(w: str) -> str:
    """剥掉首尾标点 + 尾部所有格('s/'s)，得到纯词，供名字比对。"""
    w = w.strip(_TYPO_STRIP)
    for suf in ("'s", "’s", "'S", "’S"):
        if w.endswith(suf):
            w = w[:-2]
            break
    return w


def _person_name_tokens(memory: MemoryStore, lang_code: str, minlen: int = 5) -> set:
    """
    近似错拼检测的基准词典：**只取人物名**（glossary 里 key 是 characters 实体的那些值）。
    刻意不含招式/组织名——那些会拆出 Release/Village/Force 之类普通词，撞得满屏误报。
    人物名是音译专名（Hiruzen/Orochimaru…），和普通英文词几乎不可能撞。
    """
    char_keys = set(memory.as_dict().get("characters", {}))
    glossary = memory.glossary_for(lang_code)
    names = set()
    for zh in char_keys:
        for w in str(glossary.get(zh, "")).split():
            w = _norm_word(w)
            if len(w) >= minlen:
                names.add(w)
    return names


def find_name_typos(text: str, memory: MemoryStore, lang) -> list[str]:
    """
    疑似人名错拼/错译：某 token 与某个 canonical **人物名**编辑距离 1~2、但不完全相同。
    抓 Hirzen(≈Hiruzen)、Biruho(≈Hiruko) 这类——lint 和 QA 都盯不住的单名拼写坑。
    降误报：只比人物名（见 _person_name_tokens）、token≥6、长度相近、拉丁目标只查大写专名。
    返回 "错拼→建议" 列表。
    """
    names = _person_name_tokens(memory, lang.code)
    if not names:
        return []
    seen, out = set(), []
    for tok in set(_TOKEN_RE.findall(text)):
        core = _norm_word(tok)
        if len(core) < 6 or core in names or core in seen:
            continue
        if lang.latin_script and not core[:1].isupper():
            continue
        best, bd = None, 3
        for nm in names:
            if abs(len(nm) - len(core)) > 2:
                continue
            d = _levenshtein(core, nm, 2)
            if 1 <= d < bd:
                bd, best = d, nm
        if best:
            seen.add(core)
            out.append(f"{core}→{best}")
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
    # 名字近似错拼（两语通用；拉丁目标只查大写专名，控误报）
    typos = find_name_typos(text, memory, lang)
    if typos:
        findings.append(("疑似人名错拼", typos))
    hit = [w for w in load_rules(lang).get("replace", {}) if w in text]
    if hit:
        findings.append(("已知错误短语(可--fix自动改)", hit))
    return findings


def main():
    parser = argparse.ArgumentParser(description="确定性译文体检")
    parser.add_argument("--lang", default="ar")
    parser.add_argument("--memory-path", default="memory.json")
    parser.add_argument("--dir", default=None, help="译文目录，默认 translations/<lang>")
    parser.add_argument("--profile", default=None, help="小说 profile 目录（提供 lint_<lang>.json），如 examples/naruto")
    parser.add_argument("--fix", action="store_true", help="对命中 replace 映射的地方自动替换并写回")
    args = parser.parse_args()

    lang = apply_profile(get_language(args.lang), args.profile)
    memory = MemoryStore(args.memory_path)
    d = args.dir or os.path.join("translations", lang.code)
    files = sorted(f for f in os.listdir(d) if f.startswith("chapter_") and f.endswith(".txt"))

    total = 0
    for fn in files:
        path = os.path.join(d, fn)
        text = open(path, encoding="utf-8").read()
        if args.fix:
            text, n = apply_fixes(text, lang)
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
