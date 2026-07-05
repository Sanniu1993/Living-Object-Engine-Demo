"""
EXP-005: 受控对比两个 QA 判官（DeepSeek vs GPT-5 mini）。

只变判官，其余冻结（同一份译文、同一份 Memory、同一套 QA prompt）。

两组输入：
- 干净组：项目官方 translations/chapter_0N.txt（测"误报率"——理想应报 0 条）
- 植错组：往第1章故意植入 5 个已知错误（测"命中率"——ground truth 已知）

单章 QA 失败（便宜模型偶尔返回空）不再让整轮崩溃：记 error、继续。
用法：项目根目录 `python docs/experiments/exp005_judge_compare.py`
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

from llm_client import _build_client
from memory_store import MemoryStore
from splitter import load_and_split
from workflow_qa import run_qa

load_dotenv()

memory = MemoryStore("memory.json")
chapters = load_and_split("chapters/1-5.text")
ch_by_idx = {c.index: c for c in chapters}

judges = {
    "deepseek": _build_client("deepseek", "deepseek-chat"),
    "gpt5mini": _build_client("aihubmix", "gpt-5-mini"),
}

# 第1章植入的已知错误（find, replace, count, 说明）——ground truth。
# count=0 表示全章替换（制造"整章都违反 Memory glossary"的明显错误）；
# count=1 表示只改 1 处（制造"全章其余处一致、仅此处不一致"的隐蔽错误）。
PLANTED = [
    ("Hokage Advisor", "Hokage Assistant", 0, "术语(全章违规)：glossary 为 Hokage Advisor"),
    ("Sage of Six Paths", "Sage of the Six Realms", 0, "术语(全章违规)：glossary 为 Sage of Six Paths"),
    ("Hiruzen Sarutobi", "Sarutobi Hiruzen", 1, "人名顺序(隐蔽,仅1处)：Memory 为 Hiruzen Sarutobi"),
    ("Orochimaru", "Orochi", 1, "人名(隐蔽,仅1处)：Memory 为 Orochimaru"),
]


def judge_on(judge, ch_index, ch_content, text):
    try:
        qa = run_qa(judge, memory, ch_index, text, ch_content)
        return {"issues": qa.get("issues", []), "passed": qa.get("passed")}
    except Exception as e:
        return {"error": str(e)[:150], "issues": [], "passed": None}


def make_planted(text):
    planted_applied = []
    for find, repl, count, desc in PLANTED:
        if find in text:
            text = text.replace(find, repl) if count == 0 else text.replace(find, repl, count)
            planted_applied.append({"from": find, "to": repl, "desc": desc})
    return text, planted_applied


# ---- 干净组：官方 5 章 ----
clean = []
for ch in chapters:
    with open(f"translations/chapter_{ch.index:02d}.txt", "r", encoding="utf-8") as f:
        text = f.read()
    row = {"chapter": ch.index}
    for name, judge in judges.items():
        row[name] = judge_on(judge, ch.index, ch.content, text)
    clean.append(row)
    print(
        f"[干净] 第{ch.index}章: "
        f"deepseek {len(row['deepseek']['issues'])}条{'(err)' if row['deepseek'].get('error') else ''} | "
        f"gpt5mini {len(row['gpt5mini']['issues'])}条{'(err)' if row['gpt5mini'].get('error') else ''}"
    )

# ---- 植错组：第1章植入 5 个已知错误 ----
ch1 = ch_by_idx[1]
with open("translations/chapter_01.txt", "r", encoding="utf-8") as f:
    ch1_clean = f.read()
ch1_planted, planted_applied = make_planted(ch1_clean)

planted = {"chapter": 1, "planted_errors": planted_applied}
for name, judge in judges.items():
    planted[name] = judge_on(judge, 1, ch1.content, ch1_planted)
print(
    f"[植错] 第1章(植入{len(planted_applied)}个): "
    f"deepseek {len(planted['deepseek']['issues'])}条 | gpt5mini {len(planted['gpt5mini']['issues'])}条"
)

out = os.path.join("docs", "experiments", "EXP-005-data.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump({"clean": clean, "planted": planted}, f, ensure_ascii=False, indent=2)
print(f"\n数据已写入 {out}")
