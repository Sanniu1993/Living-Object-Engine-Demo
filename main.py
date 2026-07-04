"""
main.py

整个MVP的入口。一个for循环，四步走完。

流程：
  小说txt -> 章节拆分 -> [逐章: 提取Memory -> 翻译 -> QA] -> 输出译文 + QA报告

刻意不用的东西（对应架构review的共识）：
  - 不用LangGraph：这是纯顺序流程，没有分支/循环/并行，for循环足够诚实地表达它。
  - 不把四步包装成Agent类：它们是四个函数，没有自主决策能力，
    调用Agent这个词会暗示这里有的东西实际上不存在。
  - 不做多文件Memory：全程一个 memory.json。

用法：
  python main.py --input chapters/my_novel.txt

对照实验（验证Memory到底有没有用）：
  python main.py --input chapters/my_novel.txt --ab-test
  每章同时跑"关闭Memory"和"开启Memory"两版翻译+QA，Memory本身仍正常提取、
  正常增长（两版共用同一份Memory作为QA判定基准，只是A版翻译时不给Translator看），
  结果写进 --ab-report 指定的对比报告里。
"""

import argparse
import json
import os
from dotenv import load_dotenv

from llm_client import get_client, LLMClient
from memory_store import MemoryStore
from splitter import load_and_split
from workflow_extractor import extract_memory
from workflow_translator import translate_chapter
from workflow_qa import run_qa
from workflow_reviser import revise_translation


MAX_REVISE_ROUNDS = 2  # QA→修订最多来回几轮，有界防止QA噪音导致死循环


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Living Object Engine - MVP")
    parser.add_argument("--input", required=True, help="小说原文txt路径")
    parser.add_argument("--memory-path", default="memory.json", help="Memory文件路径")
    parser.add_argument("--output-dir", default="translations", help="译文输出目录")
    parser.add_argument("--qa-report", default="qa_report.json", help="QA报告输出路径")
    parser.add_argument("--limit", type=int, default=None, help="只处理前N章（调试用）")
    parser.add_argument(
        "--ab-test",
        action="store_true",
        help="对照实验模式：每章同时跑关闭/开启Memory两版翻译，输出对比报告",
    )
    parser.add_argument(
        "--ab-report",
        default="ab_test_report.json",
        help="对照实验对比报告输出路径（仅 --ab-test 时生效）",
    )
    parser.add_argument(
        "--revise",
        action="store_true",
        help="定稿模式：QA发现问题后自动按清单修订译文，最多修2轮，输出定稿",
    )
    parser.add_argument(
        "--seed-glossary",
        default="seed_glossary.json",
        help="权威术语表种子（中文->英文），跑前注入Memory作为canonical译名；传空字符串关闭",
    )
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    print(f"[1/4] 读取并切分章节：{args.input}")
    chapters = load_and_split(args.input)
    if args.limit:
        chapters = chapters[: args.limit]
    print(f"      共识别到 {len(chapters)} 章")

    client = get_client()          # 翻译/抽取：便宜的deepseek
    qa_client = get_client("qa")   # QA判官：可在.env里配成更强的模型（如openai）
    memory = MemoryStore(args.memory_path)

    if args.seed_glossary and os.path.exists(args.seed_glossary):
        with open(args.seed_glossary, "r", encoding="utf-8") as f:
            seed = json.load(f)
        memory.seed_glossary(seed)
        print(f"[种子] 已注入 {len(seed)} 条权威术语（{args.seed_glossary}）")

    if args.ab_test:
        run_ab_test(client, qa_client, memory, chapters, args.output_dir, args.ab_report)
        print(f"\n对照实验完成。Memory: {args.memory_path} | 对比报告: {args.ab_report}")
        return

    all_qa_reports = []

    for chapter in chapters:
        print(f"\n=== 第{chapter.index}章：{chapter.title} ===")

        print("  [提取] 更新Memory...")
        extract_memory(client, memory, chapter.index, chapter.content)

        print("  [翻译] 仅消费Memory，不重新分析全文...")
        translated = translate_chapter(client, memory, chapter.index, chapter.content)

        print("  [QA] 检查一致性...")
        qa_result = run_qa(qa_client, memory, chapter.index, translated, chapter.content)
        status = "通过" if qa_result.get("passed") else f"发现 {len(qa_result.get('issues', []))} 个问题"
        print(f"      QA结果：{status}")

        if args.revise:
            translated, qa_result = _revise_until_clean(
                client, qa_client, memory, chapter, translated, qa_result
            )

        out_path = os.path.join(args.output_dir, f"chapter_{chapter.index:02d}.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(translated)
        print(f"      {'定稿' if args.revise else '译文'}已写入 {out_path}")

        qa_result["chapter"] = chapter.index
        all_qa_reports.append(qa_result)

    with open(args.qa_report, "w", encoding="utf-8") as f:
        json.dump(all_qa_reports, f, ensure_ascii=False, indent=2)

    print(f"\n全部完成。Memory: {args.memory_path} | QA报告: {args.qa_report}")


def _revise_until_clean(client, qa_client, memory, chapter, translated, qa_result):
    """
    QA→修订→再QA的有界闭环，产出定稿。

    每轮：拿上一轮QA的问题清单去修订译文，再QA一次。QA通过、或没有可修的问题、
    或达到MAX_REVISE_ROUNDS就停。返回(最终译文, 最终QA结果)。
    因为QA判官（deepseek）有噪音，可能永远"不通过"，所以必须有轮数上限。
    """
    for rnd in range(1, MAX_REVISE_ROUNDS + 1):
        issues = qa_result.get("issues", [])
        if qa_result.get("passed") or not issues:
            break

        print(f"  [修订 第{rnd}轮] 按QA清单修 {len(issues)} 个问题...")
        translated = revise_translation(
            client, memory, chapter.index, translated, issues, chapter.content
        )

        print(f"  [复检 第{rnd}轮] 重新QA...")
        qa_result = run_qa(qa_client, memory, chapter.index, translated, chapter.content)
        status = "通过" if qa_result.get("passed") else f"仍有 {len(qa_result.get('issues', []))} 个问题"
        print(f"      复检结果：{status}")

    if not qa_result.get("passed") and qa_result.get("issues"):
        print(f"      [提示] 修订{MAX_REVISE_ROUNDS}轮后仍有残留问题，已输出当前最好结果（残留见QA报告）")
    return translated, qa_result


def run_ab_test(client, qa_client, memory: MemoryStore, chapters, output_dir: str, report_path: str):
    """
    实验A（关闭Memory）：Translator看不到Memory，只能靠本章内容自己判断译法。
    实验B（开启Memory）：Translator正常消费Memory。
    两版都用同一份、正常提取增长的Memory做QA判定基准 —— 这样QA报出的问题数差异，
    才能真实反映"有没有Memory对翻译一致性的影响"，而不是两边基准不同导致的噪音。

    client用于翻译/抽取（便宜模型），qa_client用于QA（可配更强模型当判官）。
    """
    no_memory_dir = os.path.join(output_dir, "no_memory")
    with_memory_dir = os.path.join(output_dir, "with_memory")
    os.makedirs(no_memory_dir, exist_ok=True)
    os.makedirs(with_memory_dir, exist_ok=True)

    per_chapter = []

    for chapter in chapters:
        print(f"\n=== 第{chapter.index}章：{chapter.title}（对照实验）===")

        print("  [提取] 更新共享Memory...")
        extract_memory(client, memory, chapter.index, chapter.content)

        print("  [翻译-A] 关闭Memory...")
        translated_no_memory = translate_chapter(client, None, chapter.index, chapter.content)
        _write_chapter_file(no_memory_dir, chapter.index, translated_no_memory)

        print("  [翻译-B] 开启Memory...")
        translated_with_memory = translate_chapter(client, memory, chapter.index, chapter.content)
        _write_chapter_file(with_memory_dir, chapter.index, translated_with_memory)

        print("  [QA-A] 检查关闭Memory的译文...")
        summary_no_memory = _run_qa_safely(
            qa_client, memory, chapter.index, translated_no_memory, chapter.content
        )

        print("  [QA-B] 检查开启Memory的译文...")
        summary_with_memory = _run_qa_safely(
            qa_client, memory, chapter.index, translated_with_memory, chapter.content
        )

        per_chapter.append({
            "chapter": chapter.index,
            "title": chapter.title,
            "no_memory": summary_no_memory,
            "with_memory": summary_with_memory,
        })

        print(
            f"      无Memory：{_status_text(summary_no_memory)} | "
            f"有Memory：{_status_text(summary_with_memory)}"
        )

        # 逐章落盘，避免某一章QA解析失败（便宜模型偶尔输出格式抖动）
        # 就把前面几章已经跑出来的结果全部丢掉。
        report = {
            "per_chapter": per_chapter,
            "summary": {
                "no_memory": _aggregate([c["no_memory"] for c in per_chapter]),
                "with_memory": _aggregate([c["with_memory"] for c in per_chapter]),
            },
        }
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    return report


def _run_qa_safely(
    client: LLMClient,
    memory: MemoryStore,
    chapter_index: int,
    translated_text: str,
    chapter_text: str,
) -> dict:
    """
    便宜模型偶尔会输出解析失败的JSON（比如描述写太长把引号弄乱）。
    单章QA失败不该让整个多章节实验全部中断 —— 记下错误，继续跑下一章，
    比对报告里会如实标出这一章QA失败、不计入统计，而不是假装它通过了。
    """
    try:
        qa_result = run_qa(client, memory, chapter_index, translated_text, chapter_text)
        return _summarize_qa(qa_result)
    except Exception as e:
        print(f"      [警告] QA解析失败，跳过本章统计：{e}")
        return {"passed": None, "issue_count": None, "issues": [], "error": str(e)}


def _write_chapter_file(dir_path: str, chapter_index: int, text: str):
    out_path = os.path.join(dir_path, f"chapter_{chapter_index:02d}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)


def _summarize_qa(qa_result: dict) -> dict:
    issues = qa_result.get("issues", [])
    return {
        "passed": qa_result.get("passed", False),
        "issue_count": len(issues),
        "issues": issues,
    }


def _status_text(qa_summary: dict) -> str:
    if qa_summary.get("error"):
        return "QA失败"
    if qa_summary["passed"]:
        return "通过"
    return f"发现{qa_summary['issue_count']}个问题"


def _aggregate(chapter_summaries: list[dict]) -> dict:
    ok_summaries = [s for s in chapter_summaries if not s.get("error")]
    errored = len(chapter_summaries) - len(ok_summaries)

    by_severity = {"high": 0, "medium": 0, "low": 0}
    for summary in ok_summaries:
        for issue in summary["issues"]:
            severity = issue.get("severity", "low")
            by_severity[severity] = by_severity.get(severity, 0) + 1

    return {
        "total_chapters": len(chapter_summaries),
        "errored_chapters": errored,
        "passed_chapters": sum(1 for s in ok_summaries if s["passed"]),
        "total_issues": sum(s["issue_count"] for s in ok_summaries),
        "by_severity": by_severity,
    }


if __name__ == "__main__":
    main()
