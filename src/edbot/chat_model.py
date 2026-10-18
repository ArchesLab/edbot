"""One SGLang chat client shared by the orchestrator and its subagents."""
import os

import httpx
from langchain_openai import ChatOpenAI

from edbot import model_config as config


def create_chat_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=config.MODEL_NAME,
        base_url=os.environ.get("EDBOT_CHAT_BASE_URL", config.BASE_URL),
        api_key=os.environ.get("EDBOT_CHAT_API_KEY", "sglang-local"),
        # SGLang implements Chat Completions, not OpenAI's Responses API.
        use_responses_api=False,
        stream_usage=False,
        # Avoid the pinned qwen3_coder streaming parser's duplicate closing brace.
        # This public option retains streaming for calls without tool schemas.
        disable_streaming="tool_calling" if config.BUFFER_TOOL_RESPONSES else False,
        max_tokens=config.MAX_OUTPUT_TOKENS,
        temperature=config.GENERATION_TEMPERATURE,
        # Buffered responses have no body until generation ends. The service's
        # 600-second turn deadline still bounds the whole graph, including retries.
        timeout=httpx.Timeout(120.0, read=300.0 if config.BUFFER_TOOL_RESPONSES else 120.0),
        max_retries=1,
        profile={
            "max_input_tokens": config.CONTEXT_LENGTH,
            "max_output_tokens": config.MAX_OUTPUT_TOKENS,
            "tool_calling": True,
        },
        extra_body={"chat_template_kwargs": {"enable_thinking": config.ENABLE_THINKING}},
    )
