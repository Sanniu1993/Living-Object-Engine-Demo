"""
splitter.py

Chapter Reader Workflow。
输入：一个包含全部章节的大txt文件。
输出：按章节切分后的文本列表。

MVP阶段的章节标题识别用正则，覆盖最常见的中文小说章节命名习惯：
  第一章 / 第1章 / 第01章 / Chapter 1 等。
也覆盖起点/纵横一类站点导出格式：一行分隔线（---...）+ 空行 + 编号标题，
  比如：
  ------------

  001 团藏，你根部姓志村啊？
如果你的原文标题格式不在这个正则范围内，直接告诉我实际格式，
调整正则即可 —— 不需要做成通用的可配置解析框架，MVP阶段一个正则够用。
"""

import re
from dataclasses import dataclass


CHAPTER_PATTERN = re.compile(
    r"^\s*(第[0-9一二三四五六七八九十百千]+[章节回]|Chapter\s+\d+)\s*[:：、]?\s*(.*)$"
    r"|^-{3,}\s*\n\s*\d{1,4}\s+.+$",
    re.MULTILINE,
)


# L0：作者话确定性识别。这些词组基本只出现在中文网文的作者求票/求收藏段落里，
# 正常故事正文几乎不会出现，所以用它们判定"整段是不是作者话"很安全。
# 注意"收藏"单独出现有歧义（剧情里也可能收藏东西），因此只收强信号词组。
_AUTHOR_NOTE_MARKERS = re.compile(
    r"月票|推荐票|追读|求订阅|求收藏|求鲜花|求评价|求打赏|打赏|跪求|跪谢|拜托|"
    r"求支持|求推荐|新书求|二合一|作者的话|作者君|码字|订阅一下|各位读者老爷|书友|"
    r"第[0-9零一二三四五六七八九十两百]+更|加更|明天见|晚安"
)
# 段首出现这些前缀也判为作者话（PS/P.S./作者：等）。
_AUTHOR_NOTE_PREFIX = re.compile(r"^\s*(PS[：:.\s]|P\.S|作者[：:]|【作者)", re.IGNORECASE)
# 纯分隔线/纯标点段落（——、----、***、===、。！ 等），末尾出现时属于排版残留，可安全清掉。
_SEP_ONLY = re.compile(r"^[\s\-—–~*=·.。!！,，、]+$")
# 长破折号分界线（——————/----/====，≥4 个）：网文作者惯用它把正文和文末后记隔开。
_DASH_SEP = re.compile(r"^[\s\-—–_=]{4,}$")
# 强后记标记：命中即认定"从这段起到章末都是作者后记/推书"，整块砍掉。
# 只在章节末尾段落里找（后记永远在末尾），避免误伤正文。这些词正文几乎不会出现。
_AFTERWORD_START = re.compile(
    r"推一下|推荐一下|推几本|好朋友的书|老书|新书|万订|小饭|读者姥爷|读者老爷|"
    r"爆肝|求月票|求推荐票|求订阅|[一二三四五六七八九十0-9]+更[!！。…]"
)


def strip_author_notes(content: str) -> str:
    """
    删掉章节里的作者话，不碰正常剧情。四道：
    0) 行级破折号分界：正文里第一条纯破折号行之后全是后记（章节已按"破折号+编号"切开，
       正文内再现纯破折号行必是后记分界，哪怕它只用单换行黏在正文后）→ 从它起砍到章末。
    1) 强后记标记：末尾 40% 段落里第一个"推书/后记"强标记（应对无破折号、无乞讨词的推书promo）。
    2) 逐段作者话：短段落命中乞讨/更新等关键词，或以 PS/作者 开头，删。
    3) 收尾清掉遗留的纯分隔线段落。
    确定性处理，几乎免费、全语言受益。
    """
    # 0) 行级：第一条纯破折号分界线之后全砍。
    lines = content.split("\n")
    for i, ln in enumerate(lines):
        if _DASH_SEP.match(ln.strip()):
            lines = lines[:i]
            break
    content = "\n".join(lines)

    paras = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]

    # 1) 强后记标记：末尾 40% 段落里第一个命中，从那段整块砍到章末。
    n = len(paras)
    for i in range(max(0, int(n * 0.6)), n):
        if _AFTERWORD_START.search(paras[i]):
            paras = paras[:i]
            break

    # 2) 逐段作者话过滤（只删短段落，长段落更可能是正文，从严保护，不误删）。
    kept = []
    for p in paras:
        is_note = bool(_AUTHOR_NOTE_PREFIX.match(p)) or bool(_AUTHOR_NOTE_MARKERS.search(p))
        if is_note and len(p) <= 60:
            continue
        kept.append(p)

    # 3) 清掉末尾遗留的纯分隔线/纯标点段落。
    while kept and _SEP_ONLY.match(kept[-1]):
        kept.pop()

    return "\n\n".join(kept)


@dataclass
class Chapter:
    index: int          # 1-based
    title: str
    content: str


def split_chapters(full_text: str) -> list[Chapter]:
    matches = list(CHAPTER_PATTERN.finditer(full_text))

    if not matches:
        raise ValueError(
            "未能在文本中识别出任何章节标题。\n"
            "支持的格式示例：第一章、第1章、第01章、Chapter 1。\n"
            "如果你的原文标题格式不同，请告诉我实际的标题写法，我来调整识别规则。"
        )

    chapters = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        raw_block = full_text[start:end].strip()

        # 分隔线+编号格式会匹配到多行（"---\n\n001 标题"），
        # 标题只取最后一个非空行。
        title_line = match.group(0).strip().splitlines()[-1].strip()
        content = strip_author_notes(full_text[match.end():end].strip())

        chapters.append(Chapter(index=i + 1, title=title_line, content=content))

    return chapters


def load_and_split(file_path: str) -> list[Chapter]:
    with open(file_path, "r", encoding="utf-8") as f:
        full_text = f.read()
    return split_chapters(full_text)
