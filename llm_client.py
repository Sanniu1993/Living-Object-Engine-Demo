"""
llm_client.py

模型调用层。刻意做成一个薄接口，屏蔽具体调用哪个provider/哪个模型。

设计原则：
- 上层代码（memory_extractor / translator / qa）永远只调用 LLMClient.complete()
  或 LLMClient.complete_json()，不知道也不关心背后是OpenAI、OpenRouter还是别的。
- 换模型/换provider，只改这一个文件 + .env 里的配置，不改任何业务逻辑代码。
- 现在只实现 OpenAI 官方API，但接口形状已经预留了切换空间。

如果以后要换成OpenRouter或Azure，只需要新增一个类实现同样的
`complete` / `complete_json` 方法，然后在 get_client() 里切换即可。
"""

import os
import json
from typing import Optional
from openai import OpenAI


class LLMClient:
    """
    所有Workflow步骤都通过这个接口调用模型。
    不要在业务代码里直接 import openai —— 统一走这里。
    """

    def complete(
        self, system: str, user: str, temperature: float = 0.3, max_tokens: Optional[int] = None
    ) -> str:
        """返回纯文本响应。max_tokens为None时用provider默认值。"""
        raise NotImplementedError

    def complete_json(
        self, system: str, user: str, temperature: float = 0.2, max_tokens: Optional[int] = None
    ) -> dict:
        """
        返回解析后的JSON dict。
        要求调用方在system prompt里明确要求"只输出JSON，不要markdown代码块"。
        max_tokens可用于收紧输出长度，避免便宜模型发散到把JSON撑爆。
        """
        raise NotImplementedError


class OpenAIClient(LLMClient):
    """
    DeepSeek / AIHubMix 等的API都是OpenAI兼容格式，所以复用这一个类，
    只是换一下 base_url / api_key / 默认模型名。
    """

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
    ):
        # reasoning_effort：仅推理模型（gpt-5 等）有效。EXP-011 实测这个任务用 minimal
        # 就够（0 推理token、质量不降、成本降~85%）。非推理模型（deepseek）留 None 别传。
        self.reasoning_effort = reasoning_effort
        # 模型名做成配置项，不硬编码在业务逻辑里。
        # 默认值只是一个当前存在的模型，随时可以在 .env 里覆盖。
        self.model = model or os.environ.get("LLM_MODEL", "gpt-4o")
        if base_url is None:
            # 官方 OpenAI 路径：api_key 没显式传就回退到 OPENAI_API_KEY。
            key = api_key or os.environ.get("OPENAI_API_KEY")
        else:
            # 兼容 provider（deepseek/aihubmix 等）：key 必须由调用方明确传入，
            # 不回退 OPENAI_API_KEY，否则会拿错 key 静默打到别家 base_url 上。
            key = api_key
        if not key:
            raise RuntimeError(
                "未找到 API key。请在 .env 里为当前 provider 配置对应的 key："
                "openai→OPENAI_API_KEY，deepseek→DEEPSEEK_API_KEY，aihubmix→AIHUBMIX_API_KEY。"
            )
        self.client = OpenAI(api_key=key, base_url=base_url)

    def complete(
        self, system: str, user: str, temperature: float = 0.3, max_tokens: Optional[int] = None
    ) -> str:
        kwargs = {
            "model": self.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def complete_json(
        self, system: str, user: str, temperature: float = 0.2, max_tokens: Optional[int] = None
    ) -> dict:
        raw = self.complete(system, user, temperature=temperature, max_tokens=max_tokens)
        return _safe_parse_json(raw)


def _safe_parse_json(raw: str) -> dict:
    """
    模型偶尔会包一层```json代码块，这里做一次清理再解析。
    解析失败时抛出异常并把原始内容带出来，方便调试，而不是静默返回空dict——
    静默失败会让Memory悄悄丢数据，这比报错更危险。
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"模型返回内容无法解析为JSON。\n原始返回：\n{raw}\n\n错误：{e}"
        )


def _build_client(provider: str, model: Optional[str], reasoning_effort: Optional[str] = None) -> LLMClient:
    provider = provider.lower()
    if provider == "openai":
        # 官方OpenAI（ChatGPT）。model显式传入，避免落到全局LLM_MODEL（那是deepseek）。
        return OpenAIClient(model=model or "gpt-4o", reasoning_effort=reasoning_effort)
    if provider == "deepseek":
        # DeepSeek便宜、API兼容OpenAI格式，调试阶段用它跑翻译/抽取。
        return OpenAIClient(
            model=model or "deepseek-v4-flash",  # deepseek-chat 已于 2026-07 弃用
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
            reasoning_effort=reasoning_effort,
        )
    if provider == "aihubmix":
        # AIHubMix：API聚合平台，OpenAI兼容格式，一个key调GPT/Claude等强模型。
        # 用它给QA当强判官（模型ID沿用各家原名，如 gpt-5-mini）。
        return OpenAIClient(
            model=model or "gpt-5-mini",
            api_key=os.environ.get("AIHUBMIX_API_KEY"),
            base_url="https://aihubmix.com/v1",
            reasoning_effort=reasoning_effort,
        )
    raise ValueError(
        f"未知的 LLM_PROVIDER: {provider}。当前MVP只实现了 'openai'、'deepseek'、'aihubmix'。"
    )


def get_client(role: Optional[str] = None, fallback_role: Optional[str] = None) -> LLMClient:
    """
    唯一的入口点。以后要换provider，改这里/`.env`即可，业务代码不需要动。

    支持按角色分别配置模型，实现"翻译用便宜的deepseek、QA用更强的模型当判官"：
    - role=None（默认，翻译/抽取用）：读 LLM_PROVIDER / LLM_MODEL。
    - role="qa"：读 QA_LLM_PROVIDER / QA_LLM_MODEL；没配则回退默认那套。
    - role="fluency"（流畅度判官）：读 FLUENCY_LLM_PROVIDER / FLUENCY_LLM_MODEL / FLUENCY_REASONING_EFFORT；
      没配则用 fallback_role="qa"（默认和一致性QA同模型）；再没配才回退默认。

    每个角色还可配 {PREFIX}REASONING_EFFORT（minimal/low/medium/high），只对推理模型生效。
    fallback_role：某角色没显式配置时，先尝试用哪个角色的配置兜底，最后才落到全局默认。
    """
    for r in (role, fallback_role):
        if not r:
            continue
        prefix = f"{r.upper()}_"
        provider = os.environ.get(f"{prefix}LLM_PROVIDER")
        if provider:
            return _build_client(
                provider,
                os.environ.get(f"{prefix}LLM_MODEL"),
                os.environ.get(f"{prefix}REASONING_EFFORT"),
            )
    # 全局默认（翻译/抽取那套）
    provider = os.environ.get("LLM_PROVIDER", "openai")
    return _build_client(provider, os.environ.get("LLM_MODEL"), os.environ.get("REASONING_EFFORT"))
