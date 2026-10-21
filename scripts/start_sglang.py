#!/usr/bin/env python3
"""Launch the selected Qwen preset on a DGX Spark. Model selection lives in code."""
import argparse
import os
from pathlib import Path
import platform
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

# Previewing commands needs only the Python standard library.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from edbot import model_config as config


def server_arguments(host: str, ple_directory: str | None = None) -> list[str]:
    port = str(urlparse(config.BASE_URL).port)
    arguments = [
        "--host", host, "--port", port,
        "--model-path", config.MODEL_PATH, "--revision", config.MODEL_REVISION,
        "--served-model-name", config.MODEL_NAME,
        "--context-length", str(config.CONTEXT_LENGTH),
        "--mem-fraction-static", str(config.MEM_FRACTION_STATIC),
        "--max-running-requests", str(config.MAX_RUNNING_REQUESTS),
        "--cuda-graph-max-bs-decode", str(config.MAX_RUNNING_REQUESTS),
        "--chunked-prefill-size", str(config.CHUNKED_PREFILL_SIZE),
        "--kv-cache-dtype", config.KV_CACHE_DTYPE,
        "--mamba-ssm-dtype", "float32",
        "--mamba-radix-cache-strategy", config.MAMBA_RADIX_CACHE_STRATEGY,
        "--max-mamba-cache-size", str(config.MAMBA_CACHE_SLOTS_PER_REQUEST * config.MAX_RUNNING_REQUESTS),
        "--reasoning-parser", "qwen3", "--tool-call-parser", "qwen3_coder",
        "--grammar-backend", "xgrammar",
        "--enable-cache-report",
    ]
    if config.MAX_TOTAL_TOKENS is not None:
        arguments += ["--max-total-tokens", str(config.MAX_TOTAL_TOKENS)]
    if config.MODEL_PRESET == "flash-next":
        arguments += [
            "--moe-runner-backend", "flashinfer_cutlass",
            "--fp4-gemm-backend", "flashinfer_cutlass", "--page-size", "64",
            "--ple-offload-embedding", "--ple-offload-backend", "file",
            "--ple-offload-dir", ple_directory or str(config.PLE_OFFLOAD_BASE / "<new-session>"),
        ]
        # Let SGLang choose Flash-Next's QSA attention path. Its mixed precision
        # checkpoint selects its own quantization; there is no separate drafter.
        if config.ENABLE_SPECULATION:
            arguments += [
                "--speculative-algorithm", "NEXTN",
                "--speculative-num-steps", "3", "--speculative-eagle-topk", "1",
                "--speculative-num-draft-tokens", "4",
            ]
    else:
        arguments += ["--attention-backend", "flashinfer"]
    if config.MODEL_PRESET == "27b" and config.ENABLE_SPECULATION:
        arguments += [
            "--speculative-algorithm", "DSPARK",
            "--speculative-draft-model-path", config.DRAFT_MODEL_PATH,
            "--speculative-draft-model-revision", config.DRAFT_MODEL_REVISION,
            "--speculative-draft-model-quantization", "unquant",
            "--speculative-draft-attention-backend", "flashinfer",
            "--speculative-num-steps", "1", "--speculative-eagle-topk", "1",
            "--speculative-dspark-block-size", "7",
        ]
    return arguments


def docker_command() -> list[str]:
    if not config.SGLANG_IMAGE:
        raise ValueError("This model preset requires native installation; no matching Docker image is configured.")
    port = str(urlparse(config.BASE_URL).port)
    return [
        "docker", "run", "--detach", "--restart", "unless-stopped",
        "--name", config.CONTAINER_NAME, "--platform", "linux/arm64",
        *config.DOCKER_GPU_ARGS, "--ipc", "host",
        "--publish", f"127.0.0.1:{port}:{port}",
        "--volume", "edbot-sglang-cache:/root/.cache",
        "--env", "SGLANG_RAGGED_VERIFY_MODE=static",
        "--env", f"SGLANG_TOOL_STRICT_LEVEL={config.TOOL_STRICT_LEVEL}",
        "--entrypoint", "python3", config.SGLANG_IMAGE,
        "-m", "sglang.launch_server", *server_arguments("0.0.0.0"),
    ]


def native_command(ple_directory: str | None = None) -> list[str]:
    return [config.SGLANG_PYTHON, "-m", "sglang.launch_server",
            *server_arguments("127.0.0.1", ple_directory)]


def discover_cuda_home() -> Path:
    """Use the CUDA 13.0 compiler required by the pinned server installation."""
    def compatible(home: Path) -> bool:
        nvcc = home / "bin/nvcc"
        try:
            if not nvcc.is_file():
                return False
            result = subprocess.run([str(nvcc), "--version"], text=True,
                                    capture_output=True, check=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return False
        return "release 13.0," in result.stdout

    explicit = os.environ.get("CUDA_HOME")
    if explicit is not None:
        if explicit and compatible(Path(explicit)):
            return Path(explicit)
        raise ValueError("CUDA_HOME must point to a working CUDA Toolkit 13.0 installation (bin/nvcc).")

    # Match installation's preference, even when PATH contains a newer toolkit.
    for home in (Path("/usr/local/cuda-13.0"), Path("/usr/local/cuda")):
        if compatible(home):
            return home
    nvcc = shutil.which("nvcc")
    if nvcc:
        home = Path(nvcc).resolve().parent.parent
        if compatible(home):
            return home
    raise ValueError("CUDA Toolkit 13.0 (nvcc) is required. Set CUDA_HOME to its existing installation.")


def supervise(command: list[str]) -> int:
    """Forward shutdown to our server process group before removing its PLE files."""
    process = subprocess.Popen(command, start_new_session=True)
    shutdown = {}

    def send(signum):
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass

    def forward(signum, frame):
        if shutdown:
            send(signal.SIGKILL)
        else:
            shutdown.update(signal=signum, started=time.monotonic())
            send(signum)

    handlers = {signum: signal.signal(signum, forward) for signum in (signal.SIGINT, signal.SIGTERM)}
    try:
        while True:
            try:
                code = process.wait(timeout=0.5)
                return 128 + shutdown["signal"] if shutdown else (code if code >= 0 else 128 - code)
            except subprocess.TimeoutExpired:
                if shutdown and time.monotonic() - shutdown["started"] >= 30:
                    send(signal.SIGKILL)
    finally:
        # Workers may outlive a failed server leader. This group belongs only to
        # the process we launched, so no unrelated model servers are touched.
        send(signal.SIGKILL)
        process.wait()
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def run_native() -> int:
    if config.MODEL_PRESET != "flash-next":
        os.execv(config.SGLANG_PYTHON, native_command())
        return 0
    config.PLE_OFFLOAD_BASE.mkdir(parents=True, exist_ok=True)
    # Existing PLE files can turn startup into an expensive rewrite. Always use
    # a fresh private directory; delete only this launch's files after shutdown.
    with tempfile.TemporaryDirectory(prefix="session-", dir=config.PLE_OFFLOAD_BASE) as directory:
        print(f"PLE offload directory: {directory}", flush=True)
        return supervise(native_command(directory))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print the command without starting a server")
    parser.add_argument("--docker", action="store_true", help="Use the pinned container instead of the user Python environment")
    args = parser.parse_args()
    try:
        command = docker_command() if args.docker else native_command()
    except ValueError as error:
        parser.error(str(error))
    if args.dry_run:
        print(shlex.join(command))
        return 0
    if platform.system() != "Linux" or platform.machine() not in {"aarch64", "arm64"}:
        parser.error("Run this launcher on the Linux ARM64 Spark; use --dry-run to preview elsewhere.")
    if args.docker:
        # Existing containers are never stopped or replaced implicitly.
        return subprocess.run(command, check=False).returncode
    if not Path(config.SGLANG_PYTHON).is_file():
        parser.error("SGLang's user Python environment is missing; follow docs/dgx-spark.md.")
    os.environ.setdefault("SGLANG_RAGGED_VERIFY_MODE", "static")
    os.environ.setdefault("MAX_JOBS", str(config.COMPILER_JOBS))
    # Schema enforcement is application policy, so the code setting takes precedence.
    os.environ["SGLANG_TOOL_STRICT_LEVEL"] = str(config.TOOL_STRICT_LEVEL)
    os.environ["PATH"] = str(Path(config.SGLANG_PYTHON).parent) + os.pathsep + os.environ.get("PATH", "")
    try:
        os.environ["CUDA_HOME"] = str(discover_cuda_home())
    except ValueError as error:
        parser.error(str(error))
    return run_native()


if __name__ == "__main__":
    sys.exit(main())
