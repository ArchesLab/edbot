"""Shared chat-client and DGX Spark serving settings. Model selection lives here.

SGLang runs the chat model; Ollama still serves the existing embedding model.
The launcher imports this module with only the Python standard library installed.
"""
from pathlib import Path

# Change this one code setting to switch the app, installer and launcher together.
MODEL_PRESET = "flash-next"  # "flash-next" or "27b"
ENABLE_SPECULATION = True  # Disable here for a controlled same-model baseline.
BUFFER_TOOL_RESPONSES = True  # Use SGLang's full-response tool parser; plain text can still stream.
DIRECT_CONTENT_DELIVERY = True  # Deliver validated CGA-only replies without a second generation.
REDUCED_TUTOR_HARNESS = True  # Keep course reads and context recovery, omit file-editing tools/instructions.
REUSE_COURSE_EVIDENCE = True  # Pass this turn's actual source results to children before another search.
DETERMINISTIC_ASSESSMENT_SAVE = True  # Persist validated UCAOutput once, without a model write generation.
PREFETCH_ASSESSMENT_PRIOR = False  # Experiment: fresh code-owned UCA prior read before generation.
REQUIRE_CONTENT_AFTER_ASSESSMENT = True  # A completed assessment must route through CGA before the parent can reply.
SERIAL_CHILD_TOOL_CALLS = True  # CGA and code-persisted UCA: one tool per generation, including searches.

MODEL_PRESETS = {
    "flash-next": {
        "MODEL_NAME": "Qwen3.8-Flash-Next-FP4-Local",
        "MODEL_PATH": "nvidia/Qwen3.8-Flash-Next-NVFP4",
        "MODEL_REVISION": "fc694b54fb0174e0913e6adf86691ef85a4ead47",
        "DRAFT_MODEL_PATH": None,
        "DRAFT_MODEL_REVISION": None,
        "SGLANG_VERSION": "0.5.21",
        "SGLANG_SOURCE_REVISION": None,
        "FLASHINFER_VERSION": "0.6.18",
        # Official ARM64 CUDA 13.0 AOT cache; SM120-family cubins support GB10.
        "FLASHINFER_CACHE_PACKAGE": (
            "https://github.com/flashinfer-ai/flashinfer/releases/download/v0.6.18/"
            "flashinfer_jit_cache-0.6.18%2Bcu130-cp39-abi3-manylinux_2_28_aarch64.whl"
            "#sha256=c97664eab2f21a01f6b8d24d10ba33631a1a64b981f788c3f61d81ebbf905970"
        ),
        "SGLANG_PYTHON": str(Path.home() / ".local/share/edbot/sglang-flash-next/bin/python"),
        "SGLANG_IMAGE": None,  # This preset has been verified for native installation only.
        "INSTALL_DISK_GIB": 260,
        "MEM_FRACTION_STATIC": 0.85,
        "MAX_RUNNING_REQUESTS": 2,
        "MAX_TOTAL_TOKENS": 131072,  # Two active 32K contexts plus retained prefixes.
        "KV_CACHE_DTYPE": "auto",
        "MAMBA_RADIX_CACHE_STRATEGY": "extra_buffer",
        "MAMBA_CACHE_SLOTS_PER_REQUEST": 10,
        "SPECULATIVE_ALGORITHM": "NEXTN",
        "TOOL_STRICT_LEVEL": 2,  # Enforce tool schemas while preserving optional fields.
    },
    "27b": {
        "MODEL_NAME": "qwen3.8-27b",
        "MODEL_PATH": "RadixArk/Qwen3.8-27B-NVFP4",
        "MODEL_REVISION": "319f741cce68d7914884900c138a1fbb70a42f30",
        "DRAFT_MODEL_PATH": "RadixArk/Qwen3.8-27B-DSpark",
        "DRAFT_MODEL_REVISION": "b9a5dbdf03bc999c6c73c426b19c2d9041cea393",
        "SGLANG_VERSION": "0.5.19",
        "SGLANG_SOURCE_REVISION": None,
        "FLASHINFER_VERSION": None,
        "FLASHINFER_CACHE_PACKAGE": None,
        "SGLANG_PYTHON": str(Path.home() / ".local/share/edbot/sglang/bin/python"),
        # Pinned CUDA 13.0 image includes linux/arm64 for the GB10.
        "SGLANG_IMAGE": "lmsysorg/sglang:v0.5.19-cu130@sha256:d6e7288627be8b02be88e4bba38e73f6d50e2826869f753c13a4c4385ab3eda9",
        "INSTALL_DISK_GIB": 80,
        "MEM_FRACTION_STATIC": 0.70,
        "MAX_RUNNING_REQUESTS": 4,
        "MAX_TOTAL_TOKENS": None,
        "KV_CACHE_DTYPE": "fp8_e4m3",
        "MAMBA_RADIX_CACHE_STRATEGY": "extra_buffer_lazy",
        "MAMBA_CACHE_SLOTS_PER_REQUEST": 4,
        "SPECULATIVE_ALGORITHM": "DSPARK",
        "TOOL_STRICT_LEVEL": 0,  # Retain the 27B DSpark path until grammar decoding is benchmarked.
    },
}
_preset = MODEL_PRESETS[MODEL_PRESET]
MODEL_NAME = _preset["MODEL_NAME"]
MODEL_PATH = _preset["MODEL_PATH"]
MODEL_REVISION = _preset["MODEL_REVISION"]
DRAFT_MODEL_PATH = _preset["DRAFT_MODEL_PATH"]
DRAFT_MODEL_REVISION = _preset["DRAFT_MODEL_REVISION"]
SGLANG_VERSION = _preset["SGLANG_VERSION"]
SGLANG_SOURCE_REVISION = _preset["SGLANG_SOURCE_REVISION"]
SGLANG_PACKAGE = f"sglang=={SGLANG_VERSION}"
FLASHINFER_VERSION = _preset["FLASHINFER_VERSION"]
FLASHINFER_CACHE_PACKAGE = _preset["FLASHINFER_CACHE_PACKAGE"]
SGLANG_PYTHON = _preset["SGLANG_PYTHON"]
SGLANG_IMAGE = _preset["SGLANG_IMAGE"]
INSTALL_DISK_GIB = _preset["INSTALL_DISK_GIB"]
MEM_FRACTION_STATIC = _preset["MEM_FRACTION_STATIC"]
MAX_RUNNING_REQUESTS = _preset["MAX_RUNNING_REQUESTS"]
MAX_TOTAL_TOKENS = _preset["MAX_TOTAL_TOKENS"]
KV_CACHE_DTYPE = _preset["KV_CACHE_DTYPE"]
MAMBA_RADIX_CACHE_STRATEGY = _preset["MAMBA_RADIX_CACHE_STRATEGY"]
MAMBA_CACHE_SLOTS_PER_REQUEST = _preset["MAMBA_CACHE_SLOTS_PER_REQUEST"]
SPECULATIVE_ALGORITHM = _preset["SPECULATIVE_ALGORITHM"]
TOOL_STRICT_LEVEL = _preset["TOOL_STRICT_LEVEL"]
ENABLE_DSPARK = ENABLE_SPECULATION and SPECULATIVE_ALGORITHM == "DSPARK"
PLE_OFFLOAD_BASE = Path.home() / ".cache/edbot/ple"

OLLAMA_BASELINE_MODEL = "qwen3.8:27b"  # Only used by the comparison profiler.
EMBEDDING_MODEL_NAME = "qwen3-embedding:8b"
EMBEDDING_CONTEXT_LENGTH = 8192  # Allocation cap; oversized inputs raise instead of truncating.
CONTEXT_LENGTH = 32768
MAX_OUTPUT_TOKENS = 4096
ENABLE_THINKING = False  # Latency preset; enable here when evaluating reasoning quality.
GENERATION_TEMPERATURE = 0.0  # Match the sampling policy used in the paired evaluations.
BASE_URL = "http://127.0.0.1:30000/v1"
CHUNKED_PREFILL_SIZE = 2048
COMPILER_JOBS = 1  # CUDA compiler workers share the Spark's memory with resident models.
CONTAINER_NAME = "edbot-sglang"
# CDI works on DGX OS without registering the legacy NVIDIA Docker runtime.
# For a host using that runtime instead, set this to ("--gpus", "all").
DOCKER_GPU_ARGS = ("--device", "nvidia.com/gpu=all")
