"""Installer previews and failed preflights must leave the account untouched."""
import ast
from contextlib import ExitStack
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import sysconfig
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import venv


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install_spark.sh"


def installer_functions():
    """Load the embedded Python's functions without running its installer main."""
    source = INSTALLER.read_text().split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    parsed = ast.parse(source)
    parsed.body = [node for node in parsed.body if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef))]
    namespace = {}
    exec(compile(parsed, str(INSTALLER), "exec"), namespace)
    return namespace


def cuda_preflight(environment, compilers, path_nvcc=None):
    """Exercise real preflight discovery without requiring a Linux GPU host."""
    installer = installer_functions()
    installer["ROOT"] = ROOT

    def command(arguments, **kwargs):
        if arguments[0] == "/fixture/nvidia-smi":
            output = "580.123, NVIDIA GB10\n"
        else:
            version = compilers[arguments[0]]
            if isinstance(version, Exception):
                raise version
            output = f"Cuda compilation tools, release {version}, V{version}.88\n"
        return subprocess.CompletedProcess(arguments, 0, stdout=output)

    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, environment, clear=True))
        stack.enter_context(patch("platform.system", return_value="Linux"))
        stack.enter_context(patch("platform.machine", return_value="aarch64"))
        stack.enter_context(patch("os.geteuid", return_value=1000))
        stack.enter_context(patch("shutil.which", side_effect=lambda name: {
            "nvidia-smi": "/fixture/nvidia-smi", "c++": "/fixture/c++", "nvcc": path_nvcc,
        }.get(name)))
        stack.enter_context(patch("shutil.disk_usage", return_value=SimpleNamespace(free=400 * 1024**3)))
        stack.enter_context(patch.object(Path, "is_file", lambda path: path == ROOT / "uv.lock" or str(path) in compilers))
        stack.enter_context(patch("subprocess.run", side_effect=command))
        return installer["preflight"](False, {})


class SparkInstallerTest(unittest.TestCase):
    def run_installer(self, *arguments, platform_override=False):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "a user home"
            home.mkdir()
            hooks = base / "hooks"
            hooks.mkdir()
            # Network and subprocess execution are the dangerous boundaries of a
            # preview. Fail immediately if it reaches either of them.
            code = (
                "import subprocess, urllib.request\n"
                "def forbidden(*args, **kwargs):\n"
                "    raise AssertionError('preview executed an external operation')\n"
                "subprocess.run = forbidden\n"
                "subprocess.Popen = forbidden\n"
                "urllib.request.urlopen = forbidden\n"
            )
            if platform_override:
                code += "import platform\nplatform.system = lambda: 'Darwin'\n"
            (hooks / "sitecustomize.py").write_text(code)
            result = subprocess.run(
                ["bash", str(INSTALLER), *arguments],
                env={**os.environ, "HOME": str(home), "PYTHONPATH": str(hooks),
                     "PYTHONDONTWRITEBYTECODE": "1"},
                text=True, capture_output=True,
            )
            self.assertEqual(list(home.iterdir()), [], "Installer changed the account during a preview or failed preflight")
            return result

    def test_preview_performs_no_network_process_or_file_mutations(self):
        result = self.run_installer("--dry-run", "--download-models")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Install SGLang", result.stdout)
        self.assertIn("uv sync --locked", result.stdout)
        self.assertIn("qwen3-embedding:8b", result.stdout)
        self.assertIn("a user home", result.stdout)
        self.assertIn("flashinfer-python==0.6.18", result.stdout)
        self.assertIn("flashinfer_jit_cache-0.6.18%2Bcu130", result.stdout)
        self.assertIn("--no-deps", result.stdout)
        self.assertIn("JIT disabled", result.stdout)

    def test_help_is_available_without_cuda_or_installation(self):
        result = self.run_installer("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--download-models", result.stdout)

    def test_unsupported_host_fails_before_installing_anything(self):
        result = self.run_installer(platform_override=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Linux ARM64", result.stderr)
        self.assertNotIn("AssertionError", result.stderr)

    def test_invalid_explicit_cuda_home_does_not_fall_back(self):
        for explicit in ("", "/missing/cuda", "/wrong/cuda"):
            with self.subTest(explicit=explicit), self.assertRaisesRegex(RuntimeError, "CUDA_HOME"):
                cuda_preflight({"CUDA_HOME": explicit}, {
                    "/wrong/cuda/bin/nvcc": "13.4", "/usr/local/cuda-13.0/bin/nvcc": "13.0",
                })

    def test_absent_cuda_home_uses_resolved_path_compiler(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            compiler = root / "cuda/bin/nvcc"
            compiler.parent.mkdir(parents=True)
            compiler.touch()
            link = root / "nvcc"
            link.symlink_to(compiler)
            self.assertEqual(cuda_preflight({}, {str(compiler): "13.0"}, str(link)), compiler.parent.parent)

    def test_cuda_discovery_preserves_explicit_then_standard_precedence(self):
        compilers = {"/chosen/cuda/bin/nvcc": "13.0", "/usr/local/cuda-13.0/bin/nvcc": "13.0",
                     "/newer/cuda/bin/nvcc": "13.4"}
        self.assertEqual(cuda_preflight({"CUDA_HOME": "/chosen/cuda"}, compilers), Path("/chosen/cuda"))
        self.assertEqual(cuda_preflight({}, compilers, "/newer/cuda/bin/nvcc"), Path("/usr/local/cuda-13.0"))
        with self.assertRaisesRegex(RuntimeError, "CUDA Toolkit 13.0"):
            cuda_preflight({}, {"/newer/cuda/bin/nvcc": "13.4"}, "/newer/cuda/bin/nvcc")

    def test_cuda_compiler_failures_allow_only_implicit_fallback(self):
        for error in (OSError("cannot execute"), subprocess.CalledProcessError(1, "nvcc"),
                      subprocess.TimeoutExpired("nvcc", 10)):
            with self.subTest(error=type(error).__name__):
                compilers = {"/usr/local/cuda-13.0/bin/nvcc": error, "/usr/local/cuda/bin/nvcc": "13.0"}
                with self.assertRaisesRegex(RuntimeError, "CUDA_HOME"):
                    cuda_preflight({"CUDA_HOME": "/usr/local/cuda-13.0"}, compilers)
                self.assertEqual(cuda_preflight({}, compilers), Path("/usr/local/cuda"))

    def test_missing_headers_stop_an_existing_environment_before_package_changes(self):
        installer = installer_functions()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            environment = home / "sglang"
            venv.EnvBuilder(with_pip=False).create(environment)
            marker = environment / ".edbot-sglang-environment"
            marker.write_text("Original environment marker\n")
            hooks = home / "hooks"
            hooks.mkdir()
            missing_include = home / "missing-python-include"
            (hooks / "sitecustomize.py").write_text(
                "import sysconfig\n"
                "original = sysconfig.get_path\n"
                f"sysconfig.get_path = lambda name, *a, **k: {str(missing_include)!r} if name == 'include' else original(name, *a, **k)\n"
            )
            runtime_env = {**os.environ, "HOME": str(home), "PYTHONPATH": str(hooks)}
            with patch.dict(os.environ, {"HOME": str(home)}):
                with self.assertRaisesRegex(RuntimeError, "Python.h.*managed Python"):
                    installer["install_sglang"](
                        home / "uv-must-not-be-invoked", environment / "bin/python", runtime_env,
                        {"SGLANG_VERSION": "test", "SGLANG_SOURCE_REVISION": None},
                    )
            self.assertEqual(marker.read_text(), "Original environment marker\n")

    def test_header_check_accepts_a_real_python_include_directory(self):
        if not (Path(sysconfig.get_path("include")) / "Python.h").is_file():
            self.skipTest("The test interpreter has no development headers")
        installer = installer_functions()
        installer["check_python_headers"](Path(sys.executable), dict(os.environ))

    def test_source_installation_requires_the_expected_commit(self):
        installer = installer_functions()
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "sglang-1.2.3.dist-info"
            package.mkdir()
            (package / "METADATA").write_text("Metadata-Version: 2.1\nName: sglang\nVersion: 1.2.3\n")
            (package / "direct_url.json").write_text(json.dumps({
                "url": "https://github.com/sgl-project/sglang.git",
                "vcs_info": {"vcs": "git", "commit_id": "b" * 40},
            }))
            environment = {**os.environ, "PYTHONPATH": directory}
            config = {"SGLANG_VERSION": "1.2.3", "SGLANG_SOURCE_REVISION": "a" * 40}
            self.assertFalse(installer["sglang_matches_config"](Path(sys.executable), environment, config))
            config["SGLANG_SOURCE_REVISION"] = "b" * 40
            self.assertTrue(installer["sglang_matches_config"](Path(sys.executable), environment, config))

    def test_one_checkpoint_plan_needs_no_external_draft(self):
        installer = installer_functions()
        config = {"MODEL_PATH": "nvidia/example", "MODEL_REVISION": "a" * 40,
                  "DRAFT_MODEL_PATH": None, "DRAFT_MODEL_REVISION": None}
        self.assertEqual(installer["model_downloads"](config), [("nvidia/example", "a" * 40)])

    def test_27b_preset_does_not_install_a_cache_or_pin_flashinfer(self):
        config = runpy.run_path(str(ROOT / "src/edbot/model_config.py"))
        fallback = config["MODEL_PRESETS"]["27b"]
        self.assertIsNone(fallback["FLASHINFER_VERSION"])
        self.assertIsNone(fallback["FLASHINFER_CACHE_PACKAGE"])
        installer = installer_functions()
        with patch.dict(installer, {"run": lambda *args, **kwargs: self.fail("27B attempted a cache check")}):
            installer["check_flashinfer_cache"](Path(sys.executable), dict(os.environ), fallback)

    def test_cache_check_requires_matching_versions_and_a_loadable_aot_module(self):
        installer = installer_functions()
        config = {"FLASHINFER_VERSION": "0.6.18", "FLASHINFER_CACHE_PACKAGE": "configured"}
        # Stub only the external GPU package. Execute the installer's real check
        # in a subprocess, so missing AOTs cannot silently fall back to a build.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, version in [("flashinfer_python", "0.6.18"), ("flashinfer_jit_cache", "0.6.18+cu130")]:
                metadata = root / f"{name}-{version}.dist-info"
                metadata.mkdir()
                (metadata / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
            package = root / "flashinfer/jit"
            package.mkdir(parents=True)
            (package.parent / "__init__.py").touch()
            (package / "__init__.py").touch()
            (package / "fused_moe.py").write_text(
                "import os\nfrom pathlib import Path\n"
                "class Spec:\n"
                "    aot_path = Path(os.environ['TEST_AOT_PATH'])\n"
                "    is_aot = aot_path.is_file()\n"
                "    def load(self, path):\n"
                "        assert os.environ.get('FLASHINFER_DISABLE_JIT') == '1'\n"
                "        assert path == self.aot_path\n"
                "        assert path.read_text() == 'loadable', 'incompatible AOT module'\n"
                "def gen_cutlass_fused_moe_sm120_module(): return Spec()\n"
            )
            aot = root / "fused_moe_120.so"
            environment = {**os.environ, "PYTHONPATH": directory, "TEST_AOT_PATH": str(aot)}
            for state in [None, "incompatible", "loadable"]:
                with self.subTest(state=state):
                    if state is not None:
                        aot.write_text(state)
                    if state == "loadable":
                        installer["check_flashinfer_cache"](Path(sys.executable), environment, config)
                    else:
                        with self.assertRaises(subprocess.CalledProcessError):
                            installer["check_flashinfer_cache"](Path(sys.executable), environment, config)
            metadata = root / "flashinfer_python-0.6.18.dist-info/METADATA"
            metadata.write_text("Metadata-Version: 2.1\nName: flashinfer-python\nVersion: 0.7.0\n")
            with self.assertRaises(subprocess.CalledProcessError):
                installer["check_flashinfer_cache"](Path(sys.executable), environment, config)


if __name__ == "__main__":
    unittest.main()
