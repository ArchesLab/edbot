#!/usr/bin/env bash
# User-local DGX Spark installer. Python keeps paths, downloads and cleanup safe.
set -euo pipefail
exec python3 - "$0" "$@" <<'PY'
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import runpy
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

SCRIPT = Path(sys.argv.pop(1)).resolve()
ROOT = SCRIPT.parent.parent
UV_VERSION = "0.13.1"
UV_SHA256 = "9041c73c99fdc5892cf128140beb354eca9231d502068cc36e6cb53a8e59ad14"
OLLAMA_VERSION = "0.35.0"
OLLAMA_SHA256 = "cb627d332b1fe5055bd5485ca10d595da8429e447648209e375390ec3bd09374"
CUDA_VERSION = "13.0.3"
# Archive digests published by the official GitHub releases, verified 2026-10-18.
UV_URL = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-aarch64-unknown-linux-gnu.tar.gz"
OLLAMA_URL = f"https://github.com/ollama/ollama/releases/download/v{OLLAMA_VERSION}/ollama-linux-arm64.tar.zst"
DATA = Path.home() / ".local/share/edbot"
UV_HOME = DATA / "tools" / f"uv-{UV_VERSION}"
OLLAMA_HOME = DATA / "tools" / f"ollama-{OLLAMA_VERSION}"
OLLAMA_URL_LOCAL = "http://127.0.0.1:11434"


def run(command, **kwargs):
    command = [str(value) for value in command]
    print("+ " + shlex.join(command), flush=True)
    return subprocess.run(command, check=True, **kwargs)


def fail(message):
    raise RuntimeError(message)


def download(url, destination, expected_sha256):
    print(f"Downloading {url}", flush=True)
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": "Edbot-Spark-installer"})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
        while chunk := response.read(8 * 1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        fail(f"SHA-256 verification failed for {url}; nothing from that archive was installed.")


def install_uv():
    existing = shutil.which("uv")
    if existing:
        version = subprocess.run([existing, "--version"], text=True, capture_output=True, check=True).stdout.split()
        if len(version) > 1 and version[1] == UV_VERSION:
            return Path(existing)
    executable = UV_HOME / "uv"
    if executable.is_file():
        version = subprocess.run([str(executable), "--version"], text=True, capture_output=True, check=True).stdout.split()
        if len(version) > 1 and version[1] == UV_VERSION:
            return executable
        fail(f"Unexpected uv installation at {UV_HOME}; refusing to replace it.")
    if UV_HOME.exists() or UV_HOME.is_symlink():
        fail(f"Existing incomplete directory {UV_HOME}; inspect it before retrying.")
    UV_HOME.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".uv-install-", dir=UV_HOME.parent) as temporary:
        staging = Path(temporary)
        archive = staging / "uv.tar.gz"
        download(UV_URL, archive, UV_SHA256)
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(staging, filter="data")
        unpacked = staging / "uv-aarch64-unknown-linux-gnu"
        if not (unpacked / "uv").is_file():
            fail("The verified uv archive has an unexpected layout.")
        unpacked.rename(UV_HOME)
    return executable


def preflight(download_models, config):
    if platform.system() != "Linux" or platform.machine() not in {"aarch64", "arm64"}:
        fail("Run installation on the Linux ARM64 DGX Spark; --dry-run works elsewhere.")
    if os.geteuid() == 0:
        fail("Run this installer as your normal user, without sudo.")
    if sys.version_info < (3, 12):
        fail("The bootstrap requires Python 3.12 or newer (included with DGX OS).")
    if not (ROOT / "uv.lock").is_file():
        fail("Run this script from a complete Edbot checkout containing uv.lock.")
    smi = shutil.which("nvidia-smi")
    if not smi:
        fail("nvidia-smi is missing. The NVIDIA driver must already be installed.")
    details = subprocess.run(
        [smi, "--query-gpu=driver_version,name", "--format=csv,noheader"],
        text=True, capture_output=True, check=True,
    ).stdout.strip()
    if "GB10" not in details:
        fail(f"This preset targets the DGX Spark GB10; detected: {details}")
    if any(int(line.split(".", 1)[0]) < 580 for line in details.splitlines()):
        fail(f"CUDA 13 requires an NVIDIA 580-series or newer driver; detected: {details}")
    print("GPU: " + details)
    def compatible(home):
        nvcc = home / "bin/nvcc"
        try:
            if not nvcc.is_file():
                return False
            output = subprocess.run([str(nvcc), "--version"], text=True,
                                    capture_output=True, check=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return False
        return "release 13.0," in output

    # Match the launcher: an explicit setting must work, even if a fallback exists.
    explicit = os.environ.get("CUDA_HOME")
    if explicit is not None:
        if not explicit or not compatible(Path(explicit)):
            fail("CUDA_HOME must point to a working CUDA Toolkit 13.0 installation (bin/nvcc).")
        cuda_home = Path(explicit)
    else:
        cuda_home = next((home for home in (Path("/usr/local/cuda-13.0"), Path("/usr/local/cuda"))
                          if compatible(home)), None)
        if cuda_home is None:
            nvcc = shutil.which("nvcc")
            if nvcc:
                candidate = Path(nvcc).resolve().parent.parent
                if compatible(candidate):
                    cuda_home = candidate
    if cuda_home is None:
        fail("CUDA Toolkit 13.0 (nvcc) is required. Set CUDA_HOME to its existing installation.")
    if not shutil.which("c++") and not shutil.which("g++"):
        fail("A host C++ compiler is required for CUDA kernel compilation.")
    if config.get("SGLANG_SOURCE_REVISION") and not shutil.which("git"):
        fail("Git is required to install the pinned SGLang source revision.")
    required = (config["INSTALL_DISK_GIB"] if download_models else 40) * 1024**3
    for location in {Path.home(), ROOT}:
        free = shutil.disk_usage(location).free
        if free < required:
            fail(f"Need at least {required // 1024**3} GiB free for installation at {location}; found {free // 1024**3} GiB.")
    return cuda_home


def check_python_headers(python, environment):
    check = subprocess.run(
        [str(python), "-c", "import sys, sysconfig; from pathlib import Path; "
         "header = Path(sysconfig.get_path('include')) / 'Python.h'; "
         "print(header); sys.exit(0 if header.is_file() else 1)"],
        env=environment, text=True, capture_output=True,
    )
    if check.returncode:
        header = check.stdout.strip() or "the interpreter's configured include directory"
        fail(f"Python.h is missing at {header}. Triton needs Python development headers. "
             f"If you own this environment, rename {python.parent.parent} to a backup and rerun "
             "the installer to create it with managed Python; otherwise choose a separate "
             "SGLANG_PYTHON in model_config.py. No SGLang packages were installed or updated.")
    print("Python development headers: " + check.stdout.strip())


def sglang_matches_config(python, environment, config):
    check = subprocess.run(
        [str(python), "-c", "import importlib.metadata, json, sys; "
         "d = importlib.metadata.distribution('sglang'); "
         "assert d.version == sys.argv[1]; "
         "source = json.loads(d.read_text('direct_url.json') or '{}'); "
         "assert not sys.argv[2] or "
         "source.get('vcs_info', {}).get('commit_id') == sys.argv[2]",
         config["SGLANG_VERSION"], config.get("SGLANG_SOURCE_REVISION") or ""],
        env=environment, text=True, capture_output=True,
    )
    return check.returncode == 0


def check_flashinfer_cache(python, environment, config):
    if not config.get("FLASHINFER_CACHE_PACKAGE"):
        return
    # A load failure must stop installation rather than silently trigger a large
    # compilation. Disable JIT only in this check, not in the serving environment.
    run([python, "-c", "import sys; from importlib.metadata import version; "
         "assert version('flashinfer-python') == sys.argv[1], 'FlashInfer version mismatch'; "
         "assert version('flashinfer-jit-cache') == sys.argv[1] + '+cu130', 'FlashInfer cache version mismatch'; "
         "from flashinfer.jit.fused_moe import gen_cutlass_fused_moe_sm120_module; "
         "spec = gen_cutlass_fused_moe_sm120_module(); "
         "assert spec.is_aot, f'Precompiled fused_moe_120 missing: {spec.aot_path}'; "
         "spec.load(spec.aot_path); print('Precompiled FlashInfer MoE loaded:', spec.aot_path)",
         config["FLASHINFER_VERSION"]],
        env={**environment, "FLASHINFER_DISABLE_JIT": "1"})


def install_sglang(uv, python, environment, config):
    venv = python.parent.parent
    marker = venv / ".edbot-sglang-environment"
    if not venv.resolve().is_relative_to(Path.home().resolve()):
        fail(f"SGLANG_PYTHON must point inside your home directory for this user-local installer: {python}")
    if venv.exists():
        if not (venv / "pyvenv.cfg").is_file() or not python.is_file():
            fail(f"{venv} already exists but is not a Python virtual environment; refusing to replace it.")
        if not marker.is_file():
            # Adopt only an existing, compatible SGLang installation at the
            # application's configured location. Never clear an unrelated env.
            if not sglang_matches_config(python, environment, config):
                fail(f"Unrecognized environment at {venv}; choose a separate SGLANG_PYTHON in model_config.py.")
    else:
        run([uv, "venv", "--managed-python", "--python", "3.12", venv], env=environment)
    check_python_headers(python, environment)
    run([python, "-c", "import sys; assert sys.version_info[:2] == (3, 12), 'SGLang requires Python 3.12'"], env=environment)
    marker.write_text("Managed by Edbot's scripts/install_spark.sh\n")
    build_environment = dict(environment)
    if config.get("SGLANG_SOURCE_REVISION"):
        # Git-derived versions otherwise depend on which tags the checkout has.
        # These optional Rust modules serve gRPC and multimodal paths; this
        # application uses the Python OpenAI-compatible HTTP text endpoint.
        build_environment["SETUPTOOLS_SCM_PRETEND_VERSION_FOR_SGLANG"] = config["SGLANG_VERSION"]
        build_environment["SGLANG_BUILD_RUST_EXTS"] = "none"
    packages = [config["SGLANG_PACKAGE"], f"cuda-toolkit[nvcc,nvrtc]=={CUDA_VERSION}"]
    if config.get("FLASHINFER_VERSION"):
        packages.append(f"flashinfer-python=={config['FLASHINFER_VERSION']}")
    run([uv, "pip", "install", "--python", python, "--prerelease=if-necessary", *packages],
        env=build_environment)
    if not sglang_matches_config(python, environment, config):
        fail("Installed SGLang does not match the configured version/source commit. Check the installation output.")
    if config.get("FLASHINFER_CACHE_PACKAGE"):
        # uv verifies the URL's SHA-256 fragment. The cache must not resolve or
        # upgrade Torch, FlashInfer, or any of SGLang's other runtime packages.
        run([uv, "pip", "install", "--python", python, "--no-deps", config["FLASHINFER_CACHE_PACKAGE"]],
            env=environment)
        check_flashinfer_cache(python, environment, config)
    run([python, "-c", "import torch, flashinfer; "
         "assert torch.cuda.is_available(), 'CUDA unavailable'; "
         "assert torch.cuda.get_device_capability() == (12, 1), 'Expected GB10 SM121'; "
         "print('CUDA:', torch.__version__, torch.version.cuda, torch.cuda.get_device_name()); "
         "x=torch.ones((32,32), device='cuda'); assert (x @ x)[0,0].item() == 32; "
         "print('GPU computation passed; FlashInfer', flashinfer.__version__)"], env=environment)
    run([python, "-c", "from triton.runtime import driver; "
         "print('Triton CUDA initialization:', driver.active.get_current_target())"], env=environment)


def install_ollama(python, environment):
    executable = OLLAMA_HOME / "bin/ollama"
    marker = OLLAMA_HOME / ".edbot-verified-archive"
    stable = DATA / "ollama"
    if stable.exists() or stable.is_symlink():
        if not stable.is_symlink() or stable.resolve() != OLLAMA_HOME.resolve():
            fail(f"Existing installation at {stable}; refusing to replace it. Inspect it before retrying.")
    if executable.is_file() and marker.is_file() and marker.read_text().strip() == OLLAMA_SHA256:
        if not stable.is_symlink():
            stable.symlink_to(OLLAMA_HOME, target_is_directory=True)
        return stable / "bin/ollama"
    if OLLAMA_HOME.exists() or OLLAMA_HOME.is_symlink():
        fail(f"Existing unrecognized directory {OLLAMA_HOME}; refusing to overwrite it.")
    OLLAMA_HOME.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ollama-install-", dir=OLLAMA_HOME.parent) as temporary:
        staging = Path(temporary)
        archive = staging / "ollama.tar.zst"
        download(OLLAMA_URL, archive, OLLAMA_SHA256)
        unpacked = staging / "unpacked"
        unpacked.mkdir()
        # zstandard is supplied by the isolated SGLang env; the host needs no
        # zstd package or administrator-installed extraction utilities.
        run([python, "-c", "import sys, tarfile, zstandard; "
             "f=open(sys.argv[1], 'rb'); r=zstandard.ZstdDecompressor().stream_reader(f); "
             "t=tarfile.open(fileobj=r, mode='r|'); t.extractall(sys.argv[2], filter='data'); "
             "t.close(); r.close(); f.close()", archive, unpacked], env=environment)
        if not (unpacked / "bin/ollama").is_file():
            fail("The verified Ollama archive has an unexpected layout.")
        (unpacked / ".edbot-verified-archive").write_text(OLLAMA_SHA256 + "\n")
        unpacked.rename(OLLAMA_HOME)
    if not stable.is_symlink():
        stable.symlink_to(OLLAMA_HOME, target_is_directory=True)
    return stable / "bin/ollama"


def ollama_ready():
    try:
        with urllib.request.urlopen(OLLAMA_URL_LOCAL + "/api/version", timeout=2) as response:
            return isinstance(json.load(response).get("version"), str)
    except (OSError, ValueError, AttributeError):
        return False


def pull_embedding(ollama, model, environment):
    local_env = {**environment, "OLLAMA_HOST": OLLAMA_URL_LOCAL}
    owned_process = None
    log = None
    try:
        if not ollama_ready():
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", 11434))
                except OSError:
                    fail("Port 11434 is occupied but is not a healthy Ollama server; no existing process was changed.")
            log_path = DATA / "installer-ollama.log"
            log = log_path.open("ab")
            print(f"Starting a temporary local Ollama server; log: {log_path}", flush=True)
            owned_process = subprocess.Popen([str(ollama), "serve"], env=local_env,
                                             stdout=log, stderr=subprocess.STDOUT)
            for _ in range(60):
                if owned_process.poll() is not None:
                    fail(f"Temporary Ollama server exited; inspect {log_path}.")
                if ollama_ready():
                    break
                time.sleep(1)
            else:
                fail(f"Temporary Ollama did not become ready; inspect {log_path}.")
        run([ollama, "pull", model], env=local_env)
    finally:
        if owned_process is not None and owned_process.poll() is None:
            owned_process.terminate()
            try:
                owned_process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                owned_process.kill()
                owned_process.wait()
        if log is not None:
            log.close()


def model_downloads(config):
    models = [(config["MODEL_PATH"], config["MODEL_REVISION"])]
    if config.get("DRAFT_MODEL_PATH"):
        if not config.get("DRAFT_MODEL_REVISION"):
            fail("A separate draft model needs DRAFT_MODEL_REVISION in model_config.py.")
        models.append((config["DRAFT_MODEL_PATH"], config["DRAFT_MODEL_REVISION"]))
    return models


def main():
    parser = argparse.ArgumentParser(prog=SCRIPT.name, description=(
        "Install Edbot's pinned native SGLang, uv and Ollama in your user account. "
        "No sudo, Docker, profile changes or persistent services. Requires DGX OS, "
        "Python 3.12+, NVIDIA driver 580+ and CUDA Toolkit 13.0."))
    parser.add_argument("--dry-run", action="store_true", help="Show the plan without downloading, executing tools or writing files")
    parser.add_argument("--download-models", action="store_true", help="Also cache the pinned chat/draft weights and pull embeddings (temporarily starts Ollama if needed)")
    args = parser.parse_args()
    config = runpy.run_path(str(ROOT / "src/edbot/model_config.py"))
    python = Path(config["SGLANG_PYTHON"]).expanduser()
    print(f"SGLang environment: {python.parent.parent}")
    print(f"Install uv {UV_VERSION} and Ollama {OLLAMA_VERSION} from checksum-verified official ARM64 archives.")
    print("Create new SGLang environments with managed Python 3.12; check Python.h before installing packages.")
    print(f"Install SGLang ({config['SGLANG_PACKAGE']}) and cuda-toolkit[nvcc,nvrtc]=={CUDA_VERSION} "
          "with --prerelease=if-necessary; verify GPU computation and Triton initialization.")
    if config.get("FLASHINFER_VERSION"):
        print(f"Pin flashinfer-python=={config['FLASHINFER_VERSION']} in the SGLang environment.")
    if config.get("FLASHINFER_CACHE_PACKAGE"):
        print(f"Install checksum-pinned precompiled kernels with --no-deps: {config['FLASHINFER_CACHE_PACKAGE']}")
        print("Verify fused_moe_120 loads from the installed cache with JIT disabled.")
    if config.get("SGLANG_SOURCE_REVISION"):
        print(f"Build source version {config['SGLANG_VERSION']} without optional Rust extensions; verify Git commit {config['SGLANG_SOURCE_REVISION']}.")
    print(f"Install Edbot with uv sync --locked --python 3.13 in {ROOT}.")
    if args.download_models:
        for model, revision in model_downloads(config):
            print(f"Cache {model} @ {revision}.")
        print(f"Require {config['INSTALL_DISK_GIB']} GiB free for software, model downloads and runtime files.")
        print(f"Pull {config['EMBEDDING_MODEL_NAME']} using localhost Ollama; stop only a server started by this installer.")
    else:
        print("Model downloads are deferred; use --download-models to prefetch them.")
    if args.dry_run:
        return
    cuda_home = preflight(args.download_models, config)
    uv = install_uv()
    environment = {**os.environ, "CUDA_HOME": str(cuda_home),
                   "PATH": f"{python.parent}:{cuda_home / 'bin'}:{uv.parent}:{os.environ.get('PATH', '')}"}
    install_sglang(uv, python, environment, config)
    app_env = {**environment, "UV_PROJECT_ENVIRONMENT": str(ROOT / ".venv")}
    app_env.pop("VIRTUAL_ENV", None)
    run([uv, "sync", "--locked", "--python", "3.13"], cwd=ROOT, env=app_env)
    ollama = install_ollama(python, environment)
    if args.download_models:
        for model, revision in model_downloads(config):
            run([python, "-c", "import sys; from huggingface_hub import snapshot_download; "
                 "snapshot_download(repo_id=sys.argv[1], revision=sys.argv[2])",
                 model, revision], env=environment)
        pull_embedding(ollama, config["EMBEDDING_MODEL_NAME"], environment)
    print("\nInstallation, GPU computation and Triton initialization checks completed. In separate terminals:")
    print("  " + shlex.join(["env", "OLLAMA_HOST=" + OLLAMA_URL_LOCAL, str(ollama), "serve"]))
    if not args.download_models:
        print("  " + shlex.join(["env", "OLLAMA_HOST=" + OLLAMA_URL_LOCAL, str(ollama), "pull", config["EMBEDDING_MODEL_NAME"]]))
    print("  " + shlex.join(["python3", str(ROOT / "scripts/start_sglang.py")]))
    print("\nThen, from the repository:")
    print("  " + shlex.join([str(uv), "run", "python", "scripts/check_sglang.py"]))
    print("See README.md for the application's .env and login setup.")
    print(f"Optional shell PATH: export PATH={shlex.quote(str(uv.parent) + ':' + str(ollama.parent))}:\"$PATH\"")


try:
    main()
except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
    print(f"\nInstallation stopped: {error}", file=sys.stderr)
    sys.exit(1)
except KeyboardInterrupt:
    print("\nInstallation interrupted; completed downloads/environments can be reused.", file=sys.stderr)
    sys.exit(130)
PY
