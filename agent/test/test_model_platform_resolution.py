"""Smoke tests for CAMEL model platform resolution."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from camel.types import ModelPlatformType

from src.camel_runtime import CamelRuntimeConfig, resolve_model_platform


def main() -> None:
    modelscope_config = CamelRuntimeConfig(
        model="Qwen/Qwen3-32B",
        api_key="ms-demo",
        base_url="https://api-inference.modelscope.cn/v1/",
    )
    openrouter_config = CamelRuntimeConfig(
        model="openrouter/demo",
        api_key="or-demo",
        base_url="https://openrouter.ai/api/v1",
    )
    explicit_config = CamelRuntimeConfig(
        model="demo",
        api_key="demo",
        model_platform="OPENAI_COMPATIBLE_MODEL",
        base_url="https://api-inference.modelscope.cn/v1/",
    )

    assert resolve_model_platform(modelscope_config) == ModelPlatformType.MODELSCOPE
    assert resolve_model_platform(openrouter_config) == ModelPlatformType.OPENROUTER
    assert (
        resolve_model_platform(explicit_config)
        == ModelPlatformType.OPENAI_COMPATIBLE_MODEL
    )
    print("model platform resolution smoke test passed")


if __name__ == "__main__":
    main()
