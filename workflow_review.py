"""
workflow_review.py

Workflow 6：单语流畅度审校（L2）

和 QA（workflow_qa）的分工：
- QA 查**跨源**问题：术语/称呼是否和 Memory 里已确立的译法一致、是否与设定冲突。
  它的判据是"译文 vs Memory"。
- 本模块查**单语**问题：把译文当作一篇独立的目标语文章来读，只判断它自己
  通不通、对不对、自洽不自洽。判据只有"译文本身"——刻意不看中文原文，也不看 Memory。

为什么分开：小语种（如阿拉伯语）便宜模型的生成更毛糙，会出现语法残句、逐字硬翻、
前后自相矛盾这类问题——它们和"是否忠实原文""是否术语一致"是不同维度，QA 的三类白名单
故意不覆盖。硬塞进 QA 会让判官职责混乱、噪音变大，所以单起一个判官、单一套白名单。

产出的 issue 结构与 QA 完全一致（type/description/severity），因此可以原样喂给现有的
reviser 闭环去修，reviser 一行都不用改。
"""

from llm_client import LLMClient
from languages import Language


# 单语审校只报这三类；其余（剧情/风格偏好/用词高级与否）一律不报。
# 注意：句长是可确定性测量的，交给 languages.find_long_sentences + 长句闸处理，不劳判官（省调用、无噪音）。
FLUENCY_ALLOWED_TYPES = {"语法错误", "生硬直译", "前后矛盾"}

MAX_ISSUES = 15
# 推理模型的 max_tokens 是"推理+输出"的总额。越强的模型推理越多：
# EXP-010 实测 gpt-5 在 8192 下被推理吃光、两轮全空返，16000 起才吐得出 JSON。
# 所以这里给足 24000（gpt-5-mini 用不满、无额外成本；gpt-5 才够用）。重试仍给足，不能反而调小。
REVIEW_MAX_TOKENS = 24000
REVIEW_RETRY_MAX_TOKENS = 16000


def _review_system_prompt(lang: Language) -> str:
    return f"""你是一位以{lang.endonym}为母语的资深文学编辑。
你只会拿到一章的{lang.endonym}译文——看不到原文，也没有任何术语表。
请完全以母语者的语感，把它当作一篇独立的{lang.endonym}文章来审读。

你只报以下三类问题，除此之外一律不报：
1. 语法错误：不合语法、成分残缺、读不通顺的句子（缺主语/缺谓语的残句等）。
2. 生硬直译：明显像从别的语言逐字硬翻、母语者绝不会这么说、意思读不明白的表达。
3. 前后矛盾：译文内部自相矛盾（如前一句说"强调的是A"、后一句却说"强调的是B"）。
（句子长短不用你管——由程序另行处理。你只判断对错、通顺、自洽。）

硬约束（必须遵守）：
- 你看不到原文，所以**不要**判断"是否忠实于原文""有没有漏译/错译"——那不是你的活。
  只判断：作为一篇{lang.endonym}文章，它本身读起来对不对、通不通、自洽不自洽。
- 禁止评价剧情、人物、风格偏好、用词是否高级。
- 不确定的不报。宁可少报也不要凑数——一条噪音比漏一条更糟。
- type字段只能是"语法错误""生硬直译""前后矛盾"三者之一。
- 每条必须给出 quote：从译文里**原样摘抄**那段有问题的文字（供修订时定位）。
- description 要同时说清"哪里不对"和"应该怎么改"。

严格输出规则：
- 只返回严格JSON，不要markdown代码块，不要JSON之外的任何文字。
- 最多返回{MAX_ISSUES}条，按severity从high到low排序。
- 没有发现问题就返回空数组。

输出格式（只有这一种）：
{{"issues": [{{"type": "语法错误/生硬直译/前后矛盾", "quote": "有问题的译文原文片段", "description": "问题+修改建议", "severity": "high/medium/low"}}]}}

没有发现问题时，返回：
{{"issues": []}}
"""


_REVIEW_RETRY_SYSTEM_PROMPT = """上一次输出无效（不是合法JSON或为空）。
请只返回严格JSON：{"issues":[...]}
最多10条，按severity从high到low排序。
每条含 type / quote / description / severity 四个字段；type 只能是"语法错误""生硬直译""前后矛盾"。
不要解释，不要markdown，不要JSON之外的任何文字。
"""


def run_fluency_review(client: LLMClient, chapter_index: int, translated_text: str, lang: Language) -> dict:
    """
    只吃译文，返回 {"issues": [...], "passed": bool}。issue 结构与 QA 对齐，可直接喂 reviser。
    刻意不传 Memory / 原文：这是单语审校，多给反而诱导判官跑去做忠实度/一致性判断。
    """
    user_prompt = f"""请审读第{chapter_index}章的{lang.endonym}译文：

{translated_text}
"""
    try:
        result = client.complete_json(
            _review_system_prompt(lang), user_prompt, temperature=0.1, max_tokens=REVIEW_MAX_TOKENS
        )
    except ValueError:
        # 推理模型偶尔返回空/非法JSON（推理吃光配额），换更短更硬的prompt重试一次。
        result = client.complete_json(
            _REVIEW_RETRY_SYSTEM_PROMPT, user_prompt, temperature=0.0, max_tokens=REVIEW_RETRY_MAX_TOKENS
        )
    return _normalize(result)


def _normalize(result: dict) -> dict:
    """丢掉三类之外的 off-spec 条目；按 severity 排序截断；passed 由"是否为空"推导。"""
    issues = result.get("issues", []) or []
    issues = [i for i in issues if i.get("type") in FLUENCY_ALLOWED_TYPES]
    order = {"high": 0, "medium": 1, "low": 2}
    issues = sorted(issues, key=lambda i: order.get(i.get("severity", "low"), 3))[:MAX_ISSUES]
    return {"issues": issues, "passed": len(issues) == 0}
