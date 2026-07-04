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
        content = full_text[match.end():end].strip()

        chapters.append(Chapter(index=i + 1, title=title_line, content=content))

    return chapters


def load_and_split(file_path: str) -> list[Chapter]:
    with open(file_path, "r", encoding="utf-8") as f:
        full_text = f.read()
    return split_chapters(full_text)
