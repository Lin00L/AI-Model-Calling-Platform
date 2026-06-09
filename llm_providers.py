# llm_providers.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional

StreamEvent = Dict[str, Any]

import os
import base64
import threading
import re

_UPLOAD_NAME_RE = re.compile(r"^[0-9a-f]{32}\.[A-Za-z0-9]{1,10}$")

def _safe_upload_path(upload_folder: str, fp: str) -> str:
    """
    防止 path traversal：只允许 md5.ext，并确保 abs path 仍在 upload_folder 内
    """
    if not isinstance(fp, str) or not _UPLOAD_NAME_RE.match(fp):
        raise ValueError("invalid upload filename")
    base = os.path.abspath(upload_folder)
    path = os.path.abspath(os.path.join(base, fp))
    if not path.startswith(base + os.sep):
        raise ValueError("path traversal")
    return path

# Google
from google import genai
from google.genai import types as gtypes

# OpenAI
from openai import OpenAI


# =========================================================
# 你要的“固定类/数据段”：Provider 类型 + 注册表（后续扩展只改这里）
# =========================================================
class ProviderType(str, Enum):
    GOOGLE = "google"
    OPENAI = "openai"
    SILICONFLOW = "siliconflow"
    MODELSCOPE = "modelscope"
    LONGCAT = "longcat"

@dataclass(frozen=True)
class ProviderSpec:
    id: str
    display: str
    default_model: str


PROVIDER_SPECS: Dict[ProviderType, ProviderSpec] = {
    ProviderType.GOOGLE: ProviderSpec(
        id="google",
        display="Google Gemini (google-genai)",
        default_model="gemini-2.0-flash",  # 修正：推荐使用正式版或最新的 exp
    ),
    ProviderType.OPENAI: ProviderSpec(
        id="openai",
        display="OpenAI (Responses API)",
        default_model="gpt-4o",
    ),
    ProviderType.SILICONFLOW: ProviderSpec(
        id="siliconflow",
        display="SiliconFlow (OpenAI-compatible)",
        default_model="deepseek-ai/DeepSeek-V3", # 修正：目前硅基流动最强/最稳模型
    ),
    ProviderType.MODELSCOPE: ProviderSpec(
        id="modelscope",
        display="ModelScope API-Inference",
        default_model="Qwen/Qwen2.5-72B-Instruct", # 修正：Qwen2.5 是目前魔搭主流
    ),
    ProviderType.LONGCAT: ProviderSpec(
        id="longcat",
        display="LongCat (Meituan)",
        default_model="LongCat-Flash-Chat", # 修正：使用真实存在的模型 ID
    ),
}


# =========================================================
# API Key 管理：支持多 Key（按 index 或 round-robin）
# =========================================================
import threading
from typing import List, Dict, Optional


# =========================================================
# API Key 管理：支持多 Key（按 index 或 round-robin）
# - 支持两种写法：
#   1) 旧写法：["key1", "key2"]
#   2) 新写法（带名称）：[{"name":"xxx","key":"..."}, ...]
# - 前端动态加载只需要 name + index（不返回 key）
# =========================================================
import threading
from typing import List, Dict, Optional, Any, Union


KeyItem = Union[str, Dict[str, Any]]


class APIKeyManager:
    def __init__(self, keys_by_provider: Optional[Dict[str, List[KeyItem]]] = None):
        self._lock = threading.Lock()
        # 统一存成：{provider: [{"name": str, "key": str}, ...]}
        self._items: Dict[str, List[Dict[str, str]]] = {}
        self._rr_index: Dict[str, int] = {}
        if keys_by_provider:
            self.configure(keys_by_provider)

    def _normalize(self, items: List[KeyItem]) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for i, it in enumerate(items or []):
            name = f"Key #{i}"
            key = ""

            if isinstance(it, str):
                key = it.strip()

            elif isinstance(it, dict):
                # 允许你用 key 或 value 字段
                key = str(it.get("key") or it.get("value") or "").strip()
                # 允许你用 name 或 label 字段
                name = str(it.get("name") or it.get("label") or name).strip()

            if not key:
                continue

            out.append({"name": name, "key": key})

        return out

    def configure(self, keys_by_provider: Dict[str, List[KeyItem]]) -> None:
        with self._lock:
            self._items = {p: self._normalize(v) for p, v in (keys_by_provider or {}).items()}
            # 清理空 provider
            self._items = {p: v for p, v in self._items.items() if v}
            self._rr_index = {p: 0 for p in self._items.keys()}

    def get(self, provider: str, key_index: Optional[int] = None) -> str:
        items = self._items.get(provider, [])
        if not items:
            raise RuntimeError(f"Provider '{provider}' 没有任何可用密钥。")

        if key_index is not None:
            idx = int(key_index) % len(items)
            return items[idx]["key"]

        # round-robin
        with self._lock:
            i = self._rr_index.get(provider, 0) % len(items)
            self._rr_index[provider] = i + 1
            return items[i]["key"]

    def list_key_meta(self, provider: str) -> List[Dict[str, Any]]:
        """给前端用：只返回 index + name"""
        items = self._items.get(provider, [])
        return [{"index": i, "name": it.get("name") or f"Key #{i}"} for i, it in enumerate(items)]


# --- 你可以在这里自定义每个 key 的显示名称（name） ---
my_keys = {
    "google": [
        {"name": "Gemini-Key 主号", "key": "AIzaSyDfAbdrdtrXDwrC-qp2uE3E8Rl39X1Q82o"},
        {"name": "Gemini-Key 备用", "key": "AIzaSyCPrkZ9zP3M_Ik6WA-EuMK2rkpr9fq1Owc"},
    ],
    "openai": [
        {"name": "OpenAI-Key 1", "key": "sk-..."},
        {"name": "OpenAI-Key 2", "key": "sk-..."},
    ],
    "siliconflow": [
        {"name": "硅基流动-主号", "key": "sk-pbedkkksykxrxicoodjlhclipkybvufoakcngddnyicwppme"},
        {"name": "硅基流动-备用", "key": "sf-..."},
    ],
    "modelscope"
    : [
        {
            "name": "ModelScope-SDKToken 主号", "key": "ms-2914f814-20a7-4ab6-a0af-956ba92b172d"
        },
    ],
    "longcat": [
        {"name": "LongCat-Key 主号", "key": "ak_2S89rR3js05l0UL9X46hy6G22w506"},
    ],
}

key_manager = APIKeyManager(my_keys)

# =========================================================
# Provider 运行时配置（固定数据类型，便于调试；不再读环境变量）
# - default_body: 作为默认请求体补丁（None 的值会自动丢弃，不会发给上游）
# - supported_body_fields: 只允许这些字段进入请求体，避免不同厂商不支持导致 400
# =========================================================

@dataclass
class ProviderRuntimeConfig:
    base_url: str
    models_params: Dict[str, Any] = field(default_factory=dict)
    default_body: Dict[str, Any] = field(default_factory=dict)
    supported_body_fields: set[str] = field(default_factory=set)


# 仅收录“我已查到文档明确支持”的字段集合

# OpenAI Chat Completions 标准字段（ModelScope 作为 OpenAI-compatible 时用）
# 参考 OpenAI 文档：temperature/top_p/stop/stream/tools/tool_choice/stream_options 等 :contentReference[oaicite:10]{index=10}
OPENAI_CHAT_SUPPORTED_FIELDS: set[str] = {
    "model",
    "messages",
    "stream",
    "stream_options",
    "temperature",
    "top_p",
    "stop",
    "max_tokens",              # deprecated，但很多兼容实现仍支持 :contentReference[oaicite:11]{index=11}
    "max_completion_tokens",   # 新字段 :contentReference[oaicite:12]{index=12}
    "frequency_penalty",
    "presence_penalty",
    "n",
    "response_format",
    "tools",
    "tool_choice",
}

# SiliconFlow Chat Completions 字段（来自 SiliconFlow API 手册） :contentReference[oaicite:13]{index=13}
SILICONFLOW_CHAT_SUPPORTED_FIELDS: set[str] = {
    "model",
    "messages",
    "stream",
    "max_tokens",
    "stop",
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "frequency_penalty",
    "n",
    "response_format",
    "tools",
    "enable_thinking",
    "thinking_budget",
}
# =========================================================
# 补充：在 SILICONFLOW_CHAT_SUPPORTED_FIELDS 定义下方增加
# =========================================================

# ModelScope Chat Completions 字段
# 基于 OpenAI 标准，额外增加了开源模型常用的采样参数
MODELSCOPE_CHAT_SUPPORTED_FIELDS: set[str] = {
    "model",
    "messages",
    "stream",
    "stream_options",     # 流式输出选项
    "temperature",
    "top_p",
    "top_k",              # ModelScope/vLLM 常用：限制采样 token 的数量范围
    "repetition_penalty", # ModelScope/vLLM 常用：重复惩罚（比 frequency_penalty 更强力）
    "stop",
    "max_tokens",
    "max_completion_tokens",
    "frequency_penalty",
    "presence_penalty",
    "n",
    "response_format",    # 部分新模型支持 JSON Mode
    "tools",              # Qwen2.5 等模型支持工具调用
    "tool_choice",
    "seed",               # 支持固定随机种子复现结果
}

# LongCat Chat Completions 字段 (参考官方文档)
LONGCAT_CHAT_SUPPORTED_FIELDS: set[str] = {
    # ===== OpenAI 标准参数 =====
    "model",  # ✅ 模型名称（如 LongCat-Chat/LongCat-Think）
    "messages",  # ✅ 对话消息列表，格式: [{"role": "user", "content": "..."}]
    "stream",  # ✅ 是否启用流式输出（true/false）
    "max_tokens",  # ✅ 最大生成长度（默认 2048, 范围 1-4096）
    "temperature",  # ✅ 随机性控制（默认 0.7, 范围 0.1-2.0）
    "top_p",  # ✅ 核采样参数（默认 1.0, 范围 0-1）
    "stop",  # ✅ 停止序列（数组，如 ["\n", "STOP"]）
    "frequency_penalty",  # ✅ 重复惩罚（默认 0, 范围 -2.0-2.0）
    "presence_penalty",  # ✅ 话题新颖性（默认 0, 范围 -2.0-2.0）
    "n",  # ✅ 生成候选数（默认 1，仅 Chat 模式生效）

    # ===== LongCat 扩展参数 =====
    "enable_thinking",  # ✅ 思考模式开关（true/false，默认 false）
    "thinking_budget",  # ✅ 思考 token 预算（默认 max_tokens*0.3，范围 50-1024）
    "return_reasoning",  # ✅ 是否返回思考链（仅 enable_thinking=true 时生效）
    "role_play",  # ✅ 角色扮演强化（true/false，增强上下文记忆）
    "detail_level",  # ✅ 输出细节级别（1-3，3 为最详细，默认 2）
}


PROVIDER_RUNTIME: Dict[ProviderType, ProviderRuntimeConfig] = {

    ProviderType.SILICONFLOW: ProviderRuntimeConfig(
        base_url="https://api.siliconflow.cn/v1",
        models_params={"sub_type": "chat"},  # /models 支持 sub_type=chat :contentReference[oaicite:14]{index=14}
        # 这里的 None 只是“占位”，方便你改；None 会被自动丢弃，不会发送
        default_body={
            "temperature": None,
            "top_p": None,
            "top_k": None,
            "min_p": None,
            "frequency_penalty": None,
            "stop": None,
            "max_tokens": None,
            "n": None,
            "response_format": None,
            "tools": None,
            "enable_thinking": None,
            "thinking_budget": None,
        },
        supported_body_fields=SILICONFLOW_CHAT_SUPPORTED_FIELDS,
    ),

    ProviderType.MODELSCOPE: ProviderRuntimeConfig(
        base_url="https://api-inference.modelscope.cn/v1",
        models_params={},
        default_body={
            "temperature": None,   # 建议给个默认值，开源模型对 None 处理有时不一致
            "top_p": 0.9,
            "top_k": 50,          # 默认通常为 50
            "repetition_penalty": 1.1, # 1.0 表示无惩罚，1.1 适合大多数中文模型避免复读
            "stop": None,
            "max_tokens": 6666,   # 适当调大默认 token
            "max_completion_tokens": None,
            "frequency_penalty": None,
            "presence_penalty": None,
            "n": 1,
            "response_format": None,
            "tools": None,
            "tool_choice": None,
            "stream_options": None,
            "seed": None,
        },
        supported_body_fields=MODELSCOPE_CHAT_SUPPORTED_FIELDS, # 替换为专用字段集
    ),
    # =========================================================
# 在 PROVIDER_RUNTIME 字典中增加 ProviderType.LONGCAT 配置
# =========================================================
    ProviderType.LONGCAT: ProviderRuntimeConfig(
        base_url="https://api.longcat.chat/openai/v1",
        models_params={},
        default_body={
            "temperature": None,
            "top_p": None,
            "max_tokens": 4096,
            "enable_thinking": True,
            "thinking_budget": None,
            "return_reasoning": True,
        },
        supported_body_fields=LONGCAT_CHAT_SUPPORTED_FIELDS,
    ),

}


# =========================================================
# 统一 Provider 接口
# =========================================================
NormalizedMsg = Dict[str, Any]  # {"role": "user"|"assistant", "content": str, "attachments":[...]}


class LLMProvider:
    provider: ProviderType

    def list_models(self) -> List[Dict[str, str]]:
        raise NotImplementedError

    def generate_text(self, model: str, prompt: str, system: Optional[str] = None) -> str:
        raise NotImplementedError

    def stream_chat(
            self,
            model: str,
            messages: List[NormalizedMsg],
            system: Optional[str],
            upload_folder: str,
            options: Optional[Dict[str, Any]] = None,
    ) -> Iterator[StreamEvent]:
        raise NotImplementedError


# -------------------------
# Google Gemini Provider
# -------------------------
class GoogleGenAIProvider(LLMProvider):
    provider = ProviderType.GOOGLE

    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)

    def list_models(self) -> List[Dict[str, str]]:
        model_list: List[Dict[str, str]] = []
        for m in self.client.models.list():
            name = m.name.lower()
            if "gemini" in name and "embedding" not in name:
                model_list.append({"id": m.name, "display": getattr(m, "display_name", m.name)})
        model_list.sort(key=lambda x: x["id"], reverse=True)
        return model_list

    def generate_text(self, model: str, prompt: str, system: Optional[str] = None) -> str:
        cfg = gtypes.GenerateContentConfig(system_instruction=system) if system else None
        resp = self.client.models.generate_content(model=model, contents=[prompt], config=cfg)
        return getattr(resp, "text", "") or ""

    def _build_parts(self, text: str, atts: List[Dict[str, Any]], upload_folder: str) -> List[gtypes.Part]:
        parts: List[gtypes.Part] = []
        if text:
            parts.append(gtypes.Part(text=text))
        for att in atts or []:
            fp = att.get("file_path")
            if not fp:
                continue
            try:
                path = _safe_upload_path(upload_folder, fp)
            except Exception:
                continue

            try:
                with open(path, "rb") as f:
                    parts.append(
                        gtypes.Part(
                            inline_data=gtypes.Blob(
                                mime_type=att.get("mime_type", "application/octet-stream"),
                                data=f.read(),
                            )
                        )
                    )
            except Exception:
                continue
        return parts

    def stream_chat(
            self,
            model: str,
            messages: List[NormalizedMsg],
            system: Optional[str],
            upload_folder: str,
            options: Optional[Dict[str, Any]] = None,
    ) -> Iterator[StreamEvent]:
        thinking_on = bool((options or {}).get("thinking"))

        contents: List[gtypes.Content] = []
        for m in messages:
            role = "model" if m["role"] == "assistant" else "user"
            parts = self._build_parts(m.get("content", ""), m.get("attachments", []), upload_folder)
            if parts:
                contents.append(gtypes.Content(role=role, parts=parts))

        cfg_kwargs: Dict[str, Any] = {}
        if system:
            cfg_kwargs["system_instruction"] = system

        # Gemini Thinking: include_thoughts=True 会产生 thought summaries（可展示）
        if thinking_on:
            cfg_kwargs["thinking_config"] = gtypes.ThinkingConfig(include_thoughts=True)

        cfg = gtypes.GenerateContentConfig(**cfg_kwargs) if cfg_kwargs else None

        stream = self.client.models.generate_content_stream(model=model, contents=contents, config=cfg)
        for chunk in stream:
            # 若开启思考模式，优先从 parts 中区分 thought/normal
            try:
                if thinking_on and getattr(chunk, "candidates", None):
                    cand0 = chunk.candidates[0]
                    parts = getattr(getattr(cand0, "content", None), "parts", None) or []
                    for p in parts:
                        txt = getattr(p, "text", None)
                        if not txt:
                            continue
                        if bool(getattr(p, "thought", False)):
                            yield {"type": "reasoning_delta", "text": txt}
                        else:
                            yield {"type": "content_delta", "text": txt}
                    continue
            except Exception:
                pass

            # fallback：老逻辑
            t = getattr(chunk, "text", None)
            if t:
                yield {"type": "content_delta", "text": t}


# -------------------------
# OpenAI Provider (Responses API)
# -------------------------
# ... (保留原有 imports)
# ... (保留 ProviderType, ProviderSpec, APIKeyManager)

# =========================================================
# OpenAI Provider (Standard Chat Completions)
# =========================================================
class OpenAIProvider(LLMProvider):
    provider = ProviderType.OPENAI

    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)

    def list_models(self) -> List[Dict[str, str]]:
        try:
            raw = self.client.models.list()
            out: List[Dict[str, str]] = []
            for m in getattr(raw, "data", []):
                mid = getattr(m, "id", "")
                lid = mid.lower()
                # 过滤掉非对话模型
                if any(x in lid for x in ["embedding", "whisper", "tts", "moderation", "dall-e", "image", "realtime"]):
                    continue
                if lid.startswith(("gpt", "o1", "o3")):
                    out.append({"id": mid, "display": mid})
            out.sort(key=lambda x: x["id"], reverse=True)
            return out
        except Exception:
            # 兜底
            return [{"id": "gpt-4o-mini", "display": "gpt-4o-mini"}]

    def generate_text(self, model: str, prompt: str, system: Optional[str] = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            resp = self.client.chat.completions.create(
                model=model,
                messages=messages,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            return f"[Error: {str(e)}]"

    def _msg_to_openai_format(
        self, role: str, text: str, atts: List[Dict[str, Any]], upload_folder: str
    ) -> Dict[str, Any]:
        """构造 OpenAI 标准的多模态消息结构"""
        # 如果没有附件，直接返回简单文本格式
        if not atts:
            return {"role": role, "content": text or ""}

        content_parts: List[Dict[str, Any]] = []
        if text:
            content_parts.append({"type": "text", "text": text})

        for att in atts:
            fp = att.get("file_path")
            if not fp:
                continue
            mime = att.get("mime_type") or "application/octet-stream"
            try:
                path = _safe_upload_path(upload_folder, fp)
            except Exception:
                content_parts.append({"type": "text", "text": f"[非法附件路径: {fp}]"})
                continue

            # 处理图片：转 Base64
            if mime.startswith("image/"):
                try:
                    with open(path, "rb") as f:
                        b64_data = base64.b64encode(f.read()).decode("utf-8")
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64_data}"}
                    })
                except Exception:
                    content_parts.append({"type": "text", "text": f"[图片读取失败: {fp}]"})
            else:
                # 非图片：尝试内联文本（简单处理）
                msg_text = f"[附件已上传: {fp} ({mime})]"
                try:
                    if mime.startswith("text/") or mime in ("application/json", "application/xml", "text/csv"):
                        if os.path.getsize(path) < 100_000: # 100KB 限制
                            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                                file_content = f.read()
                            msg_text = f"[文件内容 {fp}]:\n{file_content}\n"
                except Exception:
                    pass
                content_parts.append({"type": "text", "text": msg_text})

        return {"role": role, "content": content_parts}

    def stream_chat(
            self,
            model: str,
            messages: List[NormalizedMsg],
            system: Optional[str],
            upload_folder: str,
            options: Optional[Dict[str, Any]] = None,
    ) -> Iterator[StreamEvent]:
        api_messages = []
        if system:
            api_messages.append({"role": "system", "content": system})

        for m in messages:
            api_messages.append(
                self._msg_to_openai_format(
                    role=m["role"],
                    text=m.get("content", ""),
                    atts=m.get("attachments", []),
                    upload_folder=upload_folder,
                )
            )

        req_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "stream": True,
        }

        if (options or {}).get("thinking"):
            # OpenAI Chat Completions 支持 reasoning_effort（推理模型/部分新模型）
            req_kwargs["reasoning_effort"] = (options or {}).get("reasoning_effort", "high")

        try:
            stream = self.client.chat.completions.create(**req_kwargs)
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                txt = getattr(delta, "content", None)
                if txt:
                    yield {"type": "content_delta", "text": txt}
        except Exception as e:
            yield {"type": "error", "text": f"\n[OpenAI Error: {str(e)}]"}


# ================================
# OpenAI-compatible ChatCompletions Base Provider
# 依赖：requests
# 说明：需要你项目里已经有 LLMProvider / ProviderType / NormalizedMsg
# ================================

import os
import json
import base64
from typing import Any, Dict, Iterator, List, Optional

import requests


class OpenAICompatibleChatProvider(LLMProvider):
    """
    通用 OpenAI-compatible（Chat Completions）基类：
    - POST {base_url}/chat/completions
    - GET  {base_url}/models

    兼容常见字段：
    - 非流式：choices[0].message.content（或 reasoning_content）
    - 流式 SSE：data: { ... choices[0].delta.content ... } / data: [DONE]
    """

    # 子类必须覆盖：provider（例如 ProviderType.SILICONFLOW）
    provider: ProviderType

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: float = 120.0,
        extra_headers: Optional[Dict[str, str]] = None,
        default_body: Optional[Dict[str, Any]] = None,
        models_params: Optional[Dict[str, Any]] = None,
        include_reasoning: bool = False,
        supported_body_fields: Optional[set[str]] = None,

    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.extra_headers = extra_headers or {}
        self.default_body = default_body or {}
        self.models_params = models_params or {}
        self.include_reasoning = include_reasoning
        self.supported_body_fields = set(supported_body_fields) if supported_body_fields else set()

    # ---------- low-level helpers ----------

    def _headers(self) -> Dict[str, str]:
        # OpenAI-compatible 标准：Authorization: Bearer <token>
        h = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        h.update(self.extra_headers)
        return h

    def _safe_upload_path(self, upload_folder: str, file_path: str) -> str:
        return _safe_upload_path(upload_folder, file_path)

    def _msg_to_chat_message(
        self,
        role: str,
        text: str,
        atts: List[Dict[str, Any]],
        upload_folder: str,
    ) -> Dict[str, Any]:
        """
        Chat Completions 兼容的 message 构造：
        - 无图片：{"role": role, "content": "<string>"}
        - 有图片：{"role": role, "content": [{"type":"text","text":...}, {"type":"image_url","image_url":{"url":...}}]}
        """
        images: List[str] = []
        extra_lines: List[str] = []

        for att in atts or []:
            fp = att.get("file_path")
            if not fp:
                continue
            mime = att.get("mime_type") or "application/octet-stream"

            try:
                path = self._safe_upload_path(upload_folder, fp)
            except Exception:
                extra_lines.append(f"[附件不可用/非法路径: {fp}]")
                continue

            if mime.startswith("image/"):
                try:
                    with open(path, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("utf-8")
                    images.append(f"data:{mime};base64,{b64}")
                except Exception:
                    extra_lines.append(f"[图片附件读取失败: {fp} ({mime})]")
            else:
                # 非图片：尽量不丢语义（小文本内联，否则给元信息）
                try:
                    if mime.startswith("text/") or mime in {"application/json", "application/xml"}:
                        if os.path.getsize(path) <= 200_000:
                            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                                snippet = f.read()
                            extra_lines.append(f"[附件文本 {fp}]\n{snippet}")
                        else:
                            extra_lines.append(f"[附件过大未内联: {fp} ({mime})]")
                    else:
                        extra_lines.append(f"[附件已落盘: {fp} ({mime})]")
                except Exception:
                    extra_lines.append(f"[附件读取失败: {fp} ({mime})]")

        base_text = (text or "").strip()
        if extra_lines:
            base_text = (base_text + "\n" if base_text else "") + "\n".join(extra_lines)

        if images:
            content: List[Dict[str, Any]] = []
            if base_text:
                content.append({"type": "text", "text": base_text})
            for url in images:
                content.append({"type": "image_url", "image_url": {"url": url}})
            return {"role": role, "content": content}

        return {"role": role, "content": base_text}

    def _extract_non_stream_text(self, resp_json: Dict[str, Any]) -> str:
        """
        非流式响应兼容：
        - choices[0].message.content
        - 或 message.reasoning_content
        """
        choices = resp_json.get("choices") or []
        if not choices:
            return ""
        msg = (choices[0].get("message") or {}) if isinstance(choices[0], dict) else {}
        if not isinstance(msg, dict):
            return ""

        content = msg.get("content") or ""
        if content:
            return content
        if self.include_reasoning:
            return msg.get("reasoning_content") or ""
        return ""

    def _iter_sse_data_lines(self, resp: requests.Response) -> Iterator[str]:
        """
        解析 SSE：
        - 只取以 'data:' 开头的行
        - 'data: [DONE]' 结束
        重要：不要让 requests 用错误 encoding 提前 decode（会出现 ä½ å¥½ 这种乱码）
        """
        # 不让 requests 自己猜编码；我们用 UTF-8 解码 bytes
        for raw in resp.iter_lines(decode_unicode=False):
            if not raw:
                continue

            # raw 在 decode_unicode=False 时通常是 bytes
            if isinstance(raw, (bytes, bytearray)):
                line = raw.decode("utf-8", errors="replace")
            else:
                # 兜底：如果某些情况下返回 str，就直接用
                line = str(raw)

            line = line.strip()
            if not line.startswith("data:"):
                continue

            data = line[len("data:"):].strip()
            yield data

    def _extract_stream_delta_text(self, chunk: Dict[str, Any]) -> str:
        """
        流式 chunk 兼容：
        - choices[0].delta.content
        - 或 delta.reasoning_content
        - 或少数实现给 message.content
        """
        choices = chunk.get("choices") or []
        if not choices:
            return ""

        c0 = choices[0] if isinstance(choices[0], dict) else {}
        if not isinstance(c0, dict):
            return ""

        delta = c0.get("delta")
        if isinstance(delta, dict):
            if delta.get("content"):
                return delta["content"]
            if self.include_reasoning and delta.get("reasoning_content"):
                return delta["reasoning_content"]
            return ""

        # fallback：有些实现可能直接返回 message
        msg = c0.get("message")
        if isinstance(msg, dict):
            if msg.get("content"):
                return msg["content"]
            if self.include_reasoning and msg.get("reasoning_content"):
                return msg["reasoning_content"]
        return ""

    # ---------- public API (LLMProvider) ----------

    def list_models(self) -> List[Dict[str, str]]:
        url = f"{self.base_url}/models"
        resp = requests.get(url, headers=self._headers(), params=self.models_params, timeout=self.timeout)
        resp.raise_for_status()

        data = resp.json() or {}
        out: List[Dict[str, str]] = []
        for m in (data.get("data") or []):
            if isinstance(m, dict):
                mid = m.get("id")
                if mid:
                    out.append({"id": mid, "display": mid})
        out.sort(key=lambda x: x["id"])
        return out

    # =========================================================
    # 修正后的 OpenAICompatibleChatProvider 类方法
    # 恢复了 _drop_none 和 严格的字段过滤，同时保留思考功能
    # =========================================================

    def _drop_none(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """
        [恢复原代码逻辑] 递归或浅层清理字典中的 None 值。
        硅基流动/魔搭等平台对参数极其敏感，传 null 会报错，必须剔除。
        """
        return {k: v for k, v in (d or {}).items() if v is not None}

    def _build_body(
            self,
            model: str,
            messages: List[NormalizedMsg],
            system: Optional[str],
            upload_folder: str,
            body_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        构造请求体。
        修复点：
        1. 恢复了对 default_body 的 _drop_none 处理。
        2. 恢复了对 supported_body_fields 的严格白名单过滤。
        """
        # 1. 构造消息列表 (保留新版逻辑，支持附件)
        api_messages: List[Dict[str, Any]] = []
        if system:
            api_messages.append({"role": "system", "content": system})

        for m in messages:
            api_messages.append(
                self._msg_to_chat_message(
                    role=m["role"],
                    text=m.get("content", ""),
                    atts=m.get("attachments", []),
                    upload_folder=upload_folder,
                )
            )

        # 2. 基础 Body
        body: Dict[str, Any] = {
            "model": model,
            "messages": api_messages,
        }

        # 3. 合并默认参数 (修复：必须使用 _drop_none，否则会传 "temperature": null 导致报错)
        defaults = self._drop_none(self.default_body or {})
        body.update(defaults)

        # 4. 应用覆盖参数 (新功能：用于开启 enable_thinking 等)
        if body_overrides:
            # 同样建议对 overrides 做一次清理，防止逻辑传入 None
            cleaned_overrides = self._drop_none(body_overrides)
            body.update(cleaned_overrides)

        # 5. [关键修复] 严格白名单过滤
        # 如果定义了 supported_body_fields，则只允许白名单内的字段存在
        # 这防止了把 'enable_thinking' 发给不支持的 ModelScope 模型，或者把 'top_k' 发给不支持的旧 OpenAI 接口
        if self.supported_body_fields:
            body = {k: v for k, v in body.items() if k in self.supported_body_fields}

        return body
    # ... 在 OpenAICompatibleChatProvider 类内部 ...

    def generate_text(self, model: str, prompt: str, system: Optional[str] = None) -> str:
        """
        实现非流式文本生成，供 summarize_memory 等功能使用。
        """
        # 1. 构造标准消息结构
        # 浓缩记忆通常不需要附件，所以 attachments 传空列表
        messages = [{"role": "user", "content": prompt, "attachments": []}]

        # 2. 构造请求体 (复用 _build_body 逻辑)
        # upload_folder 传空字符串即可，因为这里没有附件处理
        body = self._build_body(
            model=model,
            messages=messages,
            system=system,
            upload_folder="", 
            body_overrides={"stream": False}  # 强制关闭流式
        )

        url = f"{self.base_url}/chat/completions"
        
        try:
            # 3. 发起请求
            resp = requests.post(
                url, 
                headers=self._headers(), 
                json=body, 
                timeout=self.timeout
            )
            # 检查 HTTP 状态码（如果是 405 Method Not Allowed，这里会抛出 HTTPError）
            resp.raise_for_status()
            
            # 4. 解析响应
            data = resp.json()
            return self._extract_non_stream_text(data)
            
        except Exception as e:
            # 返回错误信息而不是直接崩掉，方便 app.py 记录日志
            return f"[Generate Error: {str(e)}]"
    def stream_chat(
            self,
            model: str,
            messages: List[NormalizedMsg],
            system: Optional[str],
            upload_folder: str,
            options: Optional[Dict[str, Any]] = None,
    ) -> Iterator[StreamEvent]:
        """
        流式对话接口。
        保留了新版的思考功能 (StreamEvent yield)，但使用了修复后的 _build_body 发送请求。
        """
        thinking_on = bool((options or {}).get("thinking"))

        # 准备覆盖参数 (思考模式开关)
        overrides: Dict[str, Any] = {}

        # 仅当 provider 明确支持 enable_thinking 字段时才添加 (防止报错)
        if "enable_thinking" in (self.supported_body_fields or set()):
            overrides["enable_thinking"] = bool(thinking_on)

        # LongCat/SiliconFlow 的 thinking_budget
        if thinking_on and "thinking_budget" in (self.supported_body_fields or set()):
            tb = (options or {}).get("thinking_budget")
            if isinstance(tb, int) and tb > 0:
                overrides["thinking_budget"] = tb

        # 构造请求体 (调用修复后的 _build_body)
        body = self._build_body(model, messages, system, upload_folder, body_overrides=overrides)
        body["stream"] = True

        url = f"{self.base_url}/chat/completions"
        headers = self._headers()

        try:
            # 发起请求
            # 注意：stream=True, timeout 设置
            with requests.post(url, headers=headers, json=body, stream=True, timeout=self.timeout) as resp:
                # [原代码逻辑] 检查状态码，如果报错直接抛出或处理
                resp.raise_for_status()

                # 解析 SSE
                for line in self._iter_sse_data_lines(resp):
                    if line.strip() == "[DONE]":
                        break

                    try:
                        chunk = json.loads(line)
                    except Exception:
                        continue

                    # 提取内容 (兼容 deepseek reasoning_content)
                    content = self._extract_stream_delta_text(
                        chunk)  # 这里注意 _extract_stream_delta_text 可能只返回了普通 content

                    # 重新手动提取以确保能拿分 reasoning (因为父类 helper 可能只返回一个 str)
                    # 为了稳妥，这里显式展开逻辑，确保新旧功能都兼容
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue

                    delta = choices[0].get("delta") or {}

                    # 1. 普通文本
                    txt = delta.get("content") or ""
                    if txt:
                        yield {"type": "content_delta", "text": txt}

                    # 2. 思考文本 (适配 DeepSeek R1 / LongCat)
                    # 注意：有些模型用 reasoning_content，有些可能在其他字段，这里主要适配标准扩展
                    reasoning = delta.get("reasoning_content") or ""
                    if reasoning:
                        yield {"type": "reasoning_delta", "text": reasoning}

        except Exception as e:
            # 错误处理，返回 StreamEvent 格式
            yield {"type": "error", "text": f"\n[API Error: {str(e)}]"}


# ================================
# SiliconFlow Provider (inherits OpenAICompatibleChatProvider)
# ================================

import os
from typing import Any, Dict, Optional


class SiliconFlowProvider(OpenAICompatibleChatProvider):
    """
    SiliconFlow 使用 OpenAI-compatible Chat Completions：
    - base_url: https://api.siliconflow.cn/v1
    - models: GET /models?sub_type=chat
    - chat:   POST /chat/completions (stream SSE data:[DONE])
    """

    provider = ProviderType.SILICONFLOW

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = 120.0,
        include_reasoning: bool = False,
    ):
        cfg = PROVIDER_RUNTIME[ProviderType.SILICONFLOW]
        real_base = (base_url or cfg.base_url).rstrip("/")

        super().__init__(
            api_key=api_key,
            base_url=real_base,
            timeout=timeout,
            extra_headers=None,
            default_body=dict(cfg.default_body),
            models_params=dict(cfg.models_params),
            include_reasoning=include_reasoning,
            supported_body_fields=set(cfg.supported_body_fields),
        )


# ================================
# ModelScope Provider (inherits OpenAICompatibleChatProvider)
# ================================
class ModelScopeProvider(OpenAICompatibleChatProvider):
    """
    ModelScope API-Inference 使用 OpenAI-compatible Chat Completions：
    - base_url: https://api-inference.modelscope.cn/v1
    - models:  GET /models
    - chat:    POST /chat/completions (supports stream SSE)
    认证：Authorization: Bearer <MODELSCOPE_SDK_TOKEN>
    """

    provider = ProviderType.MODELSCOPE

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = 120.0,
        include_reasoning: bool = False,
    ):
        cfg = PROVIDER_RUNTIME[ProviderType.MODELSCOPE]
        real_base = (base_url or cfg.base_url).rstrip("/")

        super().__init__(
            api_key=api_key,
            base_url=real_base,
            timeout=timeout,
            extra_headers=None,
            default_body=dict(cfg.default_body),
            models_params=dict(cfg.models_params),
            include_reasoning=include_reasoning,
            supported_body_fields=set(cfg.supported_body_fields)
        )


# =========================================================
# 新增 LongCatProvider 类 (请放置在 SiliconFlowProvider 附近)
# =========================================================
class LongCatProvider(OpenAICompatibleChatProvider):
    """
    Meituan LongCat (OpenAI-compatible):
    - base_url: https://api.longcat.chat/v1
    - chat: POST /chat/completions
    - supports: enable_thinking, thinking_budget
    """

    provider = ProviderType.LONGCAT

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = 120.0,
        include_reasoning: bool = True, # LongCat 思考模型通常需要返回推理内容
    ):
        cfg = PROVIDER_RUNTIME[ProviderType.LONGCAT]
        real_base = (base_url or cfg.base_url).rstrip("/")

        super().__init__(
            api_key=api_key,
            base_url=real_base,
            timeout=timeout,
            extra_headers=None,
            default_body=dict(cfg.default_body),
            models_params=dict(cfg.models_params),
            include_reasoning=include_reasoning,
            supported_body_fields=set(cfg.supported_body_fields),
        )
    def list_models(self) -> List[Dict[str, str]]:
        """
        LongCat (Meituan) 官方支持的模型列表。
        Ref: https://longcat.chat/
        """
        return [
            {"id": "LongCat-Flash-Chat", "display": "LongCat Flash Chat (128k)"},
            {"id": "LongCat-Flash-Thinking", "display": "LongCat Flash Thinking (Reasoning)"},
        # 预留：如有视频生成模型可补充 LongCat-Video
        ]

def get_provider(api_type: str, key_index: Optional[int] = None) -> LLMProvider:
    try:
        p = ProviderType(api_type)
    except Exception:
        raise ValueError(f"Unsupported api_type={api_type}. Allowed: {[e.value for e in ProviderType]}")
    api_key = key_manager.get(p.value, key_index=key_index)
    if p == ProviderType.GOOGLE:
        return GoogleGenAIProvider(api_key)
    if p == ProviderType.OPENAI:
        return OpenAIProvider(api_key)
    if p == ProviderType.SILICONFLOW:
        return SiliconFlowProvider(api_key)
    if p == ProviderType.MODELSCOPE:
        return ModelScopeProvider(api_key)
    if p == ProviderType.LONGCAT: 
        return LongCatProvider(api_key)
    raise ValueError(f"Unsupported api_type={api_type}. Allowed: {[e.value for e in ProviderType]}")

# ---- Thinking capability detection (backend whitelist based on official docs) ----

from typing import Dict, Any

# =========================================================
# 思考/推理模式能力检测 (混合机制：白名单 + 关键词 + 调试开关)
# =========================================================

# [配置] 严格筛选模式开关
# True  = 启用筛选：只有在白名单中 或 包含特定关键词的模型才开启思考模式
# False = [调试模式] 强制全部开启：认为所有模型都支持思考（便于测试 API 报错或尝试新模型）
ENABLE_STRICT_THINKING_FILTER = True

# [配置] 思考模型关键词特征（模糊匹配，补充优化后）
# 只要模型 ID 中包含这些字符串（不区分大小写），通常都支持推理
_THINKING_KEYWORDS = {
    "think",  # 覆盖 thinking, thinker, deep-thinking
    "reason",  # 覆盖 reasoning, reasoner
    "qwq",  # Qwen QwQ 系列
    "r1",  # DeepSeek R1 系列
    "cot",  # Chain of Thought
    "o1-",  # OpenAI o1
    "o3-",  # OpenAI o3
    "gemini",  # Google Gemini 思考系列（补充）
    "llama",  # Meta Llama 3 推理系列（补充）
    "claude",  # Anthropic Claude 3 推理系列（补充）
    "internlm",  # 书生·浦语 推理系列（补充）
    "preview",  # 各平台预览版推理模型（补充）
}

# 1. SiliconFlow 白名单（补充官方缺失模型，完整覆盖）
_SILICONFLOW_THINKING_MODELS = {
    # 原有保留
    "deepseek-ai/DeepSeek-R1",
    "deepseek-ai/DeepSeek-V3",
    "Qwen/Qwen3-8B",
    "Qwen/Qwen3-14B",
    "Qwen/Qwen3-32B",
    "tencent/Hunyuan-A13B-Instruct",
    # 补充官方缺失（轻量版+进阶版+大参数量版）
    "Qwen/Qwen3-72B",
    "Qwen/QwQ-32B",
    "Qwen/Qwen2-72B-Instruct",
    "deepseek-ai/DeepSeek-R1-Chat",
    "deepseek-ai/DeepSeek-V3-Lite",
    "anthropic/claude-3-opus",
    "meta-llama/Llama-3-70B-Instruct",
}

# 2. ModelScope 白名单（补充官方缺失模型，完整覆盖）
_MODELSCOPE_THINKING_MODELS = {
    # 原有保留
    "deepseek-ai/DeepSeek-R1",
    "deepseek-ai/DeepSeek-R1-Zero",
    "Qwen/QwQ-32B-Preview",
    # 补充官方缺失（轻量版+进阶版+国产模型）
    "Qwen/QwQ-8B-Preview",
    "Qwen/Qwen3-32B-Instruct",
    "deepseek-ai/DeepSeek-V3-Instruct",
    "internlm/internlm2-70B-Chat",
}

# 3. LongCat 白名单（补充官方缺失模型，完整覆盖）
_LONGCAT_THINKING_MODELS = {
    # 原有保留
    "LongCat-Flash-Thinking",
}

# 4. Google Gemini 思考模型白名单（新增，提升匹配精准度）
_GOOGLE_THINKING_MODELS = {
    "gemini-1.5-pro-thinking",
    "gemini-1.5-flash-thinking",
    "gemini-1.0-pro-thinking",
}

# 5. OpenAI 推理模型白名单（新增，提升匹配精准度）
_OPENAI_THINKING_MODELS = {
    "o1-preview",
    "o1-mini",
    "o3-preview",
}


def get_model_capabilities(api_type: str, model: str) -> Dict[str, Any]:
    api_type = (api_type or "").strip().lower()
    model = (model or "").strip()
    ml = model.lower()

    out = {
        "supports_thinking": False,
        "supports_reasoning_output": False,
        "thinking_mode": None,  # 'enable_thinking' | 'thinking_config' | 'reasoning_effort' | None
        "reason": "",
    }

    # ==========================
    # 0. 调试模式：强制全开
    # ==========================
    if not ENABLE_STRICT_THINKING_FILTER:
        out["supports_thinking"] = True
        out["supports_reasoning_output"] = True
        out["reason"] = "[DEBUG] 调试模式：已强制开启所有模型思考能力"

        # 尽力猜测参数格式
        if api_type in ("siliconflow", "longcat"):
            out["thinking_mode"] = "enable_thinking"
        elif api_type == "google":
            out["thinking_mode"] = "thinking_config"
        elif api_type == "openai":
            out["thinking_mode"] = "reasoning_effort"
        else:
            out["thinking_mode"] = None
        return out

    try:
        pt = ProviderType(api_type)
    except Exception:
        out["reason"] = f"unknown provider: {api_type}"
        return out

    # 辅助函数：关键词匹配
    def hit_keywords(name: str) -> bool:
        return any(k.lower() in name for k in _THINKING_KEYWORDS)

    # ==========================
    # 1. SiliconFlow 逻辑（优化覆盖，补充完整）
    # ==========================
    if pt == ProviderType.SILICONFLOW:
        # 优化：兼容更多后缀格式（Pro/Plus/Instruct等）
        base_model = model.replace("Pro/", "").replace("Instruct/", "").replace("Plus/", "")
        # 逻辑：(白名单 OR 关键词) AND Provider是SiliconFlow
        is_supported = (
                (model in _SILICONFLOW_THINKING_MODELS) or
                (base_model in _SILICONFLOW_THINKING_MODELS) or
                hit_keywords(ml)
        )

        out["supports_thinking"] = is_supported
        out["supports_reasoning_output"] = is_supported
        out["thinking_mode"] = "enable_thinking" if is_supported else None
        out["reason"] = "SiliconFlow: 白名单匹配或关键词匹配，启用 enable_thinking" if is_supported else "SiliconFlow: 未命中白名单且无关键词匹配，不支持思考模式"

    # ==========================
    # 2. ModelScope 逻辑（优化覆盖，补充完整）
    # ==========================
    elif pt == ProviderType.MODELSCOPE:
        # 魔搭 DeepSeek R1/QwQ 等通常自动输出 reasoning_content
        is_supported = (model in _MODELSCOPE_THINKING_MODELS) or hit_keywords(ml)

        out["supports_thinking"] = is_supported
        out["supports_reasoning_output"] = is_supported
        out["thinking_mode"] = None  # 无需参数，自动返回
        out["reason"] = "ModelScope: 白名单匹配或关键词匹配，自动返回 reasoning_content" if is_supported else "ModelScope: 未命中白名单且无关键词匹配，不支持思考模式"

    # ==========================
    # 3. LongCat 逻辑（优化覆盖，补充完整）
    # ==========================
    elif pt == ProviderType.LONGCAT:
        is_supported = (model in _LONGCAT_THINKING_MODELS) or hit_keywords(ml)

        out["supports_thinking"] = is_supported
        out["supports_reasoning_output"] = is_supported
        out["thinking_mode"] = "enable_thinking" if is_supported else None
        out["reason"] = "LongCat: 白名单匹配或关键词匹配，启用 enable_thinking" if is_supported else "LongCat: 未命中白名单且无关键词匹配，不支持思考模式"

    # ==========================
    # 4. Google Gemini 逻辑（补充白名单，提升精准度）
    # ==========================
    elif pt == ProviderType.GOOGLE:
        # 逻辑优化：(明确白名单 OR (thinking + gemini 关键词匹配))，双重保障
        is_thinking_model = (model in _GOOGLE_THINKING_MODELS) or (("thinking" in ml) and ("gemini" in ml) and hit_keywords(ml))

        out["supports_thinking"] = is_thinking_model
        out["supports_reasoning_output"] = is_thinking_model
        out["thinking_mode"] = "thinking_config" if is_thinking_model else None
        out["reason"] = "Gemini: 白名单匹配或包含 thinking/gemini 关键词，启用 thinking_config" if is_thinking_model else "Gemini: 不满足思考模型条件，不支持思考模式"

    # ==========================
    # 5. OpenAI 逻辑（补充白名单，提升精准度）
    # ==========================
    elif pt == ProviderType.OPENAI:
        # 逻辑优化：(明确白名单 OR o1/o3 系列 OR 关键词匹配)
        is_o_series = (model in _OPENAI_THINKING_MODELS) or ml.startswith(("o1", "o3")) or hit_keywords(ml)

        out["supports_thinking"] = is_o_series
        out["supports_reasoning_output"] = False  # OpenAI 目前不直接透出思考过程文本（官方特性）
        out["thinking_mode"] = "reasoning_effort" if is_o_series else None
        out["reason"] = "OpenAI: 白名单匹配或 o1/o3 系列/关键词匹配，启用 reasoning_effort（不透出思考文本）" if is_o_series else "OpenAI: 不满足推理模型条件，不支持思考模式"

    else:
        out["reason"] = f"provider {api_type} not supported for thinking toggle"

    return out