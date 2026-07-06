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

from languages import (
    DEFAULT_LANG, LANGUAGES, get_language,
    find_untranslated_source as find_untranslated_cjk,
    find_long_sentences,
)
from llm_client import get_client, LLMClient
from memory_store import MemoryStore
from splitter import load_and_split
from workflow_extractor import extract_memory
from workflow_translator import translate_chapter, translate_title
from workflow_qa import run_qa
from workflow_review import run_fluency_review
from workflow_reviser import revise_translation


MAX_REVISE_ROUNDS = 2  # QA→修订最多来回几轮，有界防止QA噪音导致死循环


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Living Object Engine - MVP")
    parser.add_argument("--input", required=True, help="小说原文txt路径")
    parser.add_argument(
        "--target-lang",
        default=DEFAULT_LANG,
        help=f"目标语言（已登记：{', '.join(LANGUAGES)}；新增语言改 languages.py）",
    )
    parser.add_argument("--memory-path", default="memory.json", help="Memory文件路径（多语言共用同一份理解）")
    parser.add_argument("--output-dir", default="translations", help="译文输出根目录（各语言落到 <root>/<lang>/）")
    parser.add_argument("--qa-report", default=None, help="QA报告输出路径（默认 qa_report_<lang>.json）")
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
        help="定稿模式：QA发现问题后自动按清单修订译文，输出定稿",
    )
    parser.add_argument(
        "--recheck",
        action="store_true",
        help="修复后再用判官复查一遍（更稳但多花强判官调用）；默认关：QA→修复即收尾",
    )
    parser.add_argument(
        "--fluency",
        action="store_true",
        help="单语流畅度审校（L2）：判官只看译文，抓语法/生硬直译/前后矛盾并修复。"
             "对小语种（如阿拉伯语）尤其有用；每章多一次强判官调用",
    )
    parser.add_argument(
        "--seed-glossary",
        default=None,
        help="权威术语表种子（中文->目标语），跑前注入Memory作为canonical译名；"
             "默认按目标语言自动选（如 en→seed_glossary.json、ar→seed_glossary_ar.json）；传空字符串关闭",
    )
    args = parser.parse_args()

    lang = get_language(args.target_lang)
    # 各语言译文分目录落盘，互不覆盖：translations/<lang>/chapter_XX.txt
    output_dir = os.path.join(args.output_dir, lang.code)
    qa_report_path = args.qa_report or f"qa_report_{lang.code}.json"
    # 种子文件：命令行没显式给就用该语言在 languages.py 里声明的 seed_file。
    seed_glossary_path = args.seed_glossary if args.seed_glossary is not None else lang.seed_file
    os.makedirs(output_dir, exist_ok=True)

    print(f"[目标语言] {lang.zh_name}（{lang.code}）→ 译文目录 {output_dir}")
    print(f"[1/4] 读取并切分章节：{args.input}")
    chapters = load_and_split(args.input)
    if args.limit:
        chapters = chapters[: args.limit]
    print(f"      共识别到 {len(chapters)} 章")

    client = get_client()          # 翻译/抽取：便宜的deepseek
    qa_client = get_client("qa")   # 一致性QA判官：可在.env里配成更强的模型
    # 流畅度判官：默认和一致性QA同模型；配 FLUENCY_LLM_* 可单独换更强的（如 gpt-5）
    fluency_client = get_client("fluency", fallback_role="qa")
    memory = MemoryStore(args.memory_path)

    if seed_glossary_path and os.path.exists(seed_glossary_path):
        with open(seed_glossary_path, "r", encoding="utf-8") as f:
            seed = json.load(f)
        memory.seed_glossary(seed, lang.code)
        print(f"[种子] 已为 {lang.code} 注入 {len(seed)} 条权威术语（{seed_glossary_path}）")

    if lang.idiom_seed_file and os.path.exists(lang.idiom_seed_file):
        with open(lang.idiom_seed_file, "r", encoding="utf-8") as f:
            idiom_seed = json.load(f)
        memory.seed_idioms(idiom_seed, lang.code)
        print(f"[种子] 已为 {lang.code} 注入 {len(idiom_seed)} 条成语/惯用语（{lang.idiom_seed_file}）")

    if args.ab_test:
        run_ab_test(client, qa_client, memory, chapters, output_dir, args.ab_report, lang)
        print(f"\n对照实验完成。Memory: {args.memory_path} | 对比报告: {args.ab_report}")
        return

    # 断点续跑：加载已有QA报告，跳过的章保留其结果；新章增量合并、每章落盘。
    qa_by_chapter = _load_qa_report(qa_report_path)

    for chapter in chapters:
        out_path = os.path.join(output_dir, f"chapter_{chapter.index:02d}.txt")

        # 一章"已完成"（针对当前目标语言）= 该语言的glossary已提议 且 译文文件已存在。
        # 注意用 glossary_extracted 而非 extracted_chapters：换第二种语言时理解虽已抽过，
        # 但新语言的译文还没产出，不能因此跳过。
        if memory.is_glossary_extracted(chapter.index, lang.code) and os.path.exists(out_path):
            print(f"\n=== 第{chapter.index}章：{chapter.title}（{lang.code} 已完成，跳过）===")
            continue

        print(f"\n=== 第{chapter.index}章：{chapter.title} ===")

        print("  [提取] 更新Memory...")
        extract_memory(client, memory, chapter.index, chapter.content, lang)  # 幂等，重入不会重复append

        print("  [翻译] 仅消费Memory，不重新分析全文...")
        translated = translate_chapter(client, memory, chapter.index, chapter.content, lang)

        print("  [QA] 检查一致性...")
        qa_result = run_qa(qa_client, memory, chapter.index, translated, lang, chapter.content)
        status = "通过" if qa_result.get("passed") else f"发现 {len(qa_result.get('issues', []))} 个问题"
        print(f"      QA结果：{status}")

        if args.revise:
            translated, qa_result = _revise_until_clean(
                client, qa_client, memory, chapter, translated, qa_result, lang, args.recheck
            )

        if args.fluency:
            # 单语审校：流畅度判官只看译文抓语法/生硬/矛盾，deepseek 按清单修。
            translated, fluency_result = _review_fluency(
                fluency_client, client, memory, chapter, translated, lang
            )
            qa_result["fluency"] = fluency_result

        # 漏译闸（确定性，几乎免费）：译文里不该残留源语言(中文)，有就补译。判官抓不到这类，单独兜底。
        translated = _fix_untranslated(client, memory, chapter, translated, lang)

        # 长句闸（确定性）：按目标语言阈值找 run-on，只把超长的那几句拆短（阿语短句优先）。
        translated = _fix_long_sentences(client, memory, chapter, translated, lang)

        # 翻译章节标题（成品需要目标语标题）；标题也过漏译闸，残留中文就重译一次。
        title_out = translate_title(client, memory, chapter.title, lang)
        if find_untranslated_cjk(title_out):
            title_out = translate_title(client, memory, chapter.title, lang)
        print(f"      标题：{title_out}")

        # 输出归一化（按语言）：拉丁字母目标去掉日语罗马字 macron（Hyūga→Hyuga）；
        # 阿拉伯语等非拉丁目标不做处理。判官把 macron 当无实质差异不报，这里确定性兜底。
        translated = lang.normalize(translated)
        title_out = lang.normalize(title_out)

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(title_out + "\n\n" + translated)
        print(f"      {'定稿' if args.revise else '译文'}已写入 {out_path}")

        qa_result["chapter"] = chapter.index
        qa_by_chapter[chapter.index] = qa_result
        _write_qa_report(qa_report_path, qa_by_chapter)  # 增量落盘，中途崩不丢

    print(f"\n全部完成。Memory: {args.memory_path} | QA报告: {qa_report_path}")


def _review_fluency(judge_client, fix_client, memory, chapter, translated, lang):
    """
    单语流畅度审校闭环（L2）：判官(强模型)只看译文挑毛病 → deepseek 按清单修一次。
    只修一轮（判官已是强模型，一次足够；多轮性价比低）。审校发现的问题原样存进报告，
    即使这次没全修好，也留痕可追。返回 (修订后译文, 审校结果dict)。
    """
    print("  [流畅度审校] 判官只看译文，查语法/生硬/前后矛盾...")
    result = run_fluency_review(judge_client, chapter.index, translated, lang)
    issues = result.get("issues", [])
    if not issues:
        print("      流畅度：通过")
        return translated, result

    print(f"      流畅度：发现 {len(issues)} 处 → 修复")
    translated = revise_translation(
        fix_client, memory, chapter.index, translated, issues, lang, chapter.content
    )
    return translated, result


def _fix_long_sentences(client, memory, chapter, translated, lang, max_tries=2):
    """
    确定性长句闸：按 lang.max_sentence_words 找出超长句（run-on），只把这几句丢给 reviser
    在语义完整处断成 2~3 句，其余一律不动。阈值=0 的语言直接跳过（如英/西默认关）。
    检测免费（数词），只有真有超长句才花一次修复调用；拆完再复查，最多 max_tries 轮。
    """
    if not lang.max_sentence_words:
        return translated
    for _ in range(max_tries):
        longs = find_long_sentences(translated, lang.max_sentence_words)
        if not longs:
            break
        print(f"      [长句] {len(longs)} 句超 {lang.max_sentence_words} 词 → 拆短")
        issues = [{
            "type": "句子冗长",
            "severity": "low",
            "quote": s,
            "description": f"这句超过 {lang.max_sentence_words} 词，请在语义完整处断成 2~3 个较短句子，"
                           "保持原意、术语/人名不变，不要改动其他句子。",
        } for s in longs]
        translated = revise_translation(
            client, memory, chapter.index, translated, issues, lang, chapter.content
        )
    return translated


def _fix_untranslated(client, memory, chapter, translated, lang, max_tries=2):
    """
    确定性漏译兜底：译文含源语言(中文)就让 reviser 把那几段补译，最多补 max_tries 次。
    检测免费（正则），只有真漏译时才花一次 DeepSeek 调用。人名会走 Memory 里的既定译名。
    """
    for _ in range(max_tries):
        leftover = find_untranslated_cjk(translated)
        if not leftover:
            break
        print(f"      [漏译] 检测到未翻译中文：{' '.join(leftover)[:40]} → 补译")
        issue = [{
            "type": "漏译",
            "severity": "high",
            "description": f"以下中文片段未翻译，请译成地道的{lang.endonym}并融入上下文"
                           "（人名/术语用Memory里已确立的译名）：" + "、".join(leftover),
        }]
        translated = revise_translation(
            client, memory, chapter.index, translated, issue, lang, chapter.content
        )
    return translated


def _load_qa_report(path: str) -> dict:
    """加载已有QA报告为 {章号: 结果}，供断点续跑合并。文件不存在/损坏则返回空。"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return {r["chapter"]: r for r in json.load(f) if "chapter" in r}
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}


def _write_qa_report(path: str, qa_by_chapter: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump([qa_by_chapter[k] for k in sorted(qa_by_chapter)], f, ensure_ascii=False, indent=2)


def _revise_until_clean(client, qa_client, memory, chapter, translated, qa_result, lang, recheck=False):
    """
    定稿闭环，以"修复"收尾（角色分工：DeepSeek 翻译/修复，GPT-5 mini 判官）。

    recheck=False（默认，省判官）：译文 → QA找问题 → 修复 → 收尾（不复查）。每章只 1 次判官调用。
    recheck=True（更稳更贵）：译文 → QA → 修复 → 复查 → 最后修复（末轮不复查）。

    任一轮 QA 判定通过（无问题）则提前结束。入参 qa_result 是第一次 QA（main 里已跑）的结果。
    """
    max_rounds = MAX_REVISE_ROUNDS if recheck else 1
    for rnd in range(1, max_rounds + 1):
        issues = qa_result.get("issues", [])
        if qa_result.get("passed") or not issues:
            break

        print(f"  [修复 第{rnd}轮] DeepSeek 按QA清单修 {len(issues)} 个问题...")
        translated = revise_translation(
            client, memory, chapter.index, translated, issues, lang, chapter.content
        )

        if rnd == max_rounds:
            # 末轮：修完直接收尾，不再复查（省判官；末尾以修复动作结束）。
            print("      修复完成，直接定稿（未复查）")
            qa_result["note"] = "修复后未复查；上面列的是修复前发现的问题"
            break

        print(f"  [复查 第{rnd}轮] GPT-5 mini 重新QA...")
        qa_result = run_qa(qa_client, memory, chapter.index, translated, lang, chapter.content)
        status = "通过" if qa_result.get("passed") else f"仍有 {len(qa_result.get('issues', []))} 个问题"
        print(f"      复查结果：{status}")

    return translated, qa_result


def run_ab_test(client, qa_client, memory: MemoryStore, chapters, output_dir: str, report_path: str, lang):
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
        extract_memory(client, memory, chapter.index, chapter.content, lang)

        print("  [翻译-A] 关闭Memory...")
        translated_no_memory = translate_chapter(client, None, chapter.index, chapter.content, lang)
        _write_chapter_file(no_memory_dir, chapter.index, translated_no_memory)

        print("  [翻译-B] 开启Memory...")
        translated_with_memory = translate_chapter(client, memory, chapter.index, chapter.content, lang)
        _write_chapter_file(with_memory_dir, chapter.index, translated_with_memory)

        print("  [QA-A] 检查关闭Memory的译文...")
        summary_no_memory = _run_qa_safely(
            qa_client, memory, chapter.index, translated_no_memory, lang, chapter.content
        )

        print("  [QA-B] 检查开启Memory的译文...")
        summary_with_memory = _run_qa_safely(
            qa_client, memory, chapter.index, translated_with_memory, lang, chapter.content
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
    lang,
    chapter_text: str,
) -> dict:
    """
    便宜模型偶尔会输出解析失败的JSON（比如描述写太长把引号弄乱）。
    单章QA失败不该让整个多章节实验全部中断 —— 记下错误，继续跑下一章，
    比对报告里会如实标出这一章QA失败、不计入统计，而不是假装它通过了。
    """
    try:
        qa_result = run_qa(client, memory, chapter_index, translated_text, lang, chapter_text)
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
