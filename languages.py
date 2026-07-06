"""
languages.py

多语言插口 —— 加语言时唯一需要动的中心文件。

设计出发点（对应整个架构的灵魂）：
Extractor「只理解，不翻译」，所以 Memory 里 characters/locations/organizations/
timeline/state_log/summary 都是**语言无关**的，一份就能喂给所有目标语言、不用重跑。
真正和语言绑定的只有两样：glossary（术语译名）和译文本身。

因此"多语言"不是复制一整套流程，而是：
    一份语言无关的理解 + 每个目标语言各一份 glossary。

源语言固定为中文（这个 demo 的原文都是中文小说）。要新增一个目标语言：
  1. 在下面 LANGUAGES 里加一条 Language；
  2.（可选）放一份 seed_glossary_<code>.json 权威术语种子；
  就这两步，main / 各 workflow / verify 全都从这里取配置，不再写死"英文"。
"""

import re
from dataclasses import dataclass
from typing import Callable


# ---------- 输出归一化插口（每语言可各自指定） ----------

# 日语罗马字长音符 → 朴素拼写（ō→o, ū→u…），只对拉丁字母目标有意义。
# 阿拉伯语等非拉丁目标不需要，用 _identity。
_MACRON_TABLE = str.maketrans("āēīōūĀĒĪŌŪ", "aeiouAEIOU")


def _strip_macrons(text: str) -> str:
    """去掉日语罗马字长音符，统一成朴素拼写，避免 Hyuga/Hyūga 混用。"""
    return text.translate(_MACRON_TABLE)


def _identity(text: str) -> str:
    return text


# ---------- 源语言残留检测插口 ----------
# 源语言固定是中文，所以"没翻干净"= 译文里残留中文（CJK）。
# 目标语只要不是 CJK（en/ar/es 都不是），这个检测就成立。
# 未来若要加日语/韩语这类 CJK 目标，需要在这里换成按"源文特有片段"检测，而不是查 CJK。
_CJK_RE = re.compile(r"[一-鿿]+")


def find_untranslated_source(text: str) -> list[str]:
    """确定性地找出译文里残留的源语言（中文）片段，返回去重后的列表。"""
    seen, out = set(), []
    for frag in _CJK_RE.findall(text):
        if frag not in seen:
            seen.add(frag)
            out.append(frag)
    return out


@dataclass(frozen=True)
class Language:
    """
    一个目标语言的完整配置。所有和"这门语言"有关的差异都收敛在这里，
    workflow 只认 Language 对象，不认具体是哪门语言。
    """
    code: str                # 命令行 --target-lang 用的短码：en / ar / es
    zh_name: str             # 中文名，拼进给模型的中文 prompt（"中译英"里的"英"）
    endonym: str             # 语种约束里用的名字（"English" / "Arabic (العربية)"）
    chapter_label: str       # 章节标题里 "Chapter" 的对应词（Chapter / الفصل / Capítulo）
    seed_file: str           # 该语言的权威术语表种子文件名（没有就留空串）
    rtl: bool = False        # 是否从右到左（阿拉伯语=True），目前仅作元信息
    translator_notes: str = ""   # 该语言特有的译法提示，拼进 translator prompt
    title_notes: str = ""        # 该语言特有的标题译法提示
    normalize_output: Callable[[str], str] = _identity  # 输出归一化插口

    def normalize(self, text: str) -> str:
        return self.normalize_output(text)


# ---------- 各语言特有的译法提示 ----------

_EN_TRANSLATOR_NOTES = """- "火影"指动漫《火影忍者》这部作品时，译作 Naruto；只有指"火影"这个职位时才译 Hokage。
- 穿越设定里的"原身/原主"指这具身体原来的主人，不要译成 predecessor（前任），
  可译 the body's original owner 之类。
- 例：背黑锅 → take the blame / be the scapegoat（不是 "bear a black pot"）；
      待价而沽 → hold out for a better offer；天无二日 → there can't be two suns."""

_EN_TITLE_NOTES = """- 人物/术语必须用下面Memory里已确立的英文译法（如 大蛇丸→Orochimaru、猿飞日斩→Hiruzen Sarutobi）。"""

_AR_TRANSLATOR_NOTES = """- 专有名词（人名/地名/招式）按阿拉伯语通行的音译习惯转写，并与 glossary 保持完全一致。
- 阿拉伯语从右到左书写，但数字、章节序号照常保留。
- 成语/网络梗按意思译成阿拉伯语读者能懂的说法，绝不逐字直译。"""


# ---------- 语言注册表（新增语言 = 在这里加一条） ----------

LANGUAGES: dict[str, Language] = {
    "en": Language(
        code="en",
        zh_name="英语",
        endonym="English",
        chapter_label="Chapter",
        seed_file="seed_glossary.json",   # 保留旧文件名，向后兼容
        translator_notes=_EN_TRANSLATOR_NOTES,
        title_notes=_EN_TITLE_NOTES,
        normalize_output=_strip_macrons,
    ),
    "ar": Language(
        code="ar",
        zh_name="阿拉伯语",
        endonym="Arabic (العربية)",
        chapter_label="الفصل",
        seed_file="seed_glossary_ar.json",
        rtl=True,
        translator_notes=_AR_TRANSLATOR_NOTES,
        title_notes="",              # 标题人名/术语走 glossary，通用规则已够
        normalize_output=_identity,  # 阿拉伯文无罗马字长音符，不归一
    ),
    # 西班牙语插口：已登记好，随时可用 `--target-lang es` 启用。
    # 要更好的一致性再补一份 seed_glossary_es.json 即可（没有也能跑，靠 Extractor 提议）。
    "es": Language(
        code="es",
        zh_name="西班牙语",
        endonym="Spanish (Español)",
        chapter_label="Capítulo",
        seed_file="seed_glossary_es.json",
        translator_notes="",
        title_notes="",
        normalize_output=_strip_macrons,   # 西语用拉丁字母，罗马字人名同样归一
    ),
}

DEFAULT_LANG = "en"


def get_language(code: str) -> Language:
    code = (code or "").lower()
    if code not in LANGUAGES:
        raise ValueError(
            f"未知的目标语言：{code!r}。已登记：{', '.join(LANGUAGES)}。"
            f"要加新语言，请在 languages.py 的 LANGUAGES 里加一条。"
        )
    return LANGUAGES[code]
