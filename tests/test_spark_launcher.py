"""The launcher's previews must not start servers or download model weights."""
import os
import importlib.util
import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import subprocess
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def launcher():
    spec = importlib.util.spec_from_file_location("start_sglang", ROOT / "scripts/start_sglang.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def selected_preset(module, name, speculation=True):
    """Choose the fixture explicitly; operator tuning must not select a test case."""
    return patch.multiple(module.config, **module.config.MODEL_PRESETS[name],
                          MODEL_PRESET=name, ENABLE_SPECULATION=speculation,
                          ENABLE_DSPARK=speculation and name == "27b")


class SparkLauncherTest(unittest.TestCase):
    def test_flash_preview_uses_native_mtp_without_the_27b_draft(self):
        module = launcher()
        output = io.StringIO()
        environment = dict(os.environ)
        with selected_preset(module, "flash-next"), \
                patch.object(sys, "argv", ["start_sglang.py", "--dry-run"]), redirect_stdout(output):
            result = module.main()
        self.assertEqual(result, 0)
        self.assertEqual(dict(os.environ), environment)
        command = output.getvalue()
        self.assertIn("--served-model-name Qwen3.8-Flash-Next-FP4-Local", command)
        self.assertIn("--speculative-algorithm NEXTN", command)
        self.assertIn("--speculative-num-draft-tokens 4", command)
        self.assertIn("--ple-offload-backend file", command)
        self.assertIn("--max-total-tokens 131072", command)
        self.assertNotIn("--speculative-draft-model-path", command)
        self.assertNotIn("--kv-cache-dtype fp8", command)
        self.assertNotIn("--attention-backend flashinfer", command)

    def test_disabling_speculation_removes_all_draft_flags(self):
        module = launcher()
        with patch.object(module.config, "ENABLE_SPECULATION", False):
            command = module.native_command()
        self.assertFalse(any(argument.startswith("--speculative-") for argument in command))

    def test_flash_refuses_the_old_model_docker_image(self):
        module = launcher()
        with selected_preset(module, "flash-next"), self.assertRaisesRegex(ValueError, "requires native installation"):
            module.docker_command()

    def test_dry_run_does_not_execute_docker(self):
        module = launcher()
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "docker-was-executed"
            docker = Path(directory) / "docker"
            docker.write_text('#!/bin/sh\nprintf executed > "$DOCKER_TEST_MARKER"\nexit 99\n')
            docker.chmod(0o755)
            output = io.StringIO()
            with selected_preset(module, "27b"), \
                    patch.dict(os.environ, {"PATH": directory, "DOCKER_TEST_MARKER": str(marker)}), \
                    patch.object(sys, "argv", ["start_sglang.py", "--docker", "--dry-run"]), redirect_stdout(output):
                environment = dict(os.environ)
                result = module.main()
                self.assertEqual(dict(os.environ), environment)
            self.assertEqual(result, 0)
            self.assertTrue(output.getvalue().startswith("docker run "), output.getvalue())
            self.assertIn("--speculative-algorithm DSPARK", output.getvalue())
            self.assertIn("--env SGLANG_TOOL_STRICT_LEVEL=0", output.getvalue())
            self.assertNotIn("--ple-offload", output.getvalue())
            self.assertNotIn("--max-total-tokens", output.getvalue())
            self.assertFalse(marker.exists(), "A preview must not execute Docker")

    def test_native_preview_works_without_the_sglang_environment(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/start_sglang.py"), "--dry-run"],
            env={**os.environ, "PATH": ""}, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("-m sglang.launch_server", result.stdout)
        self.assertNotIn("docker", result.stdout)

    def test_native_launch_prefers_cuda_13_over_incompatible_path_compiler(self):
        module = launcher()
        observed = []

        def run():
            observed.append(os.environ.get("CUDA_HOME"))
            return 17

        def version(command, **kwargs):
            release = "13.0" if command[0] == "/usr/local/cuda-13.0/bin/nvcc" else "13.4"
            return subprocess.CompletedProcess(command, 0, stdout=f"Cuda compilation tools, release {release}, V{release}.88\n")

        with patch.dict(os.environ, {"PATH": "/fixture/cuda-13.4/bin"}, clear=True), \
                patch.object(module.platform, "system", return_value="Linux"), \
                patch.object(module.platform, "machine", return_value="aarch64"), \
                patch.object(module.Path, "is_file", return_value=True), \
                patch.object(module.shutil, "which", return_value="/fixture/cuda-13.4/bin/nvcc"), \
                patch.object(module.subprocess, "run", side_effect=version), \
                patch.object(module, "run_native", side_effect=run), \
                patch.object(sys, "argv", ["start_sglang.py"]):
            result = module.main()
        self.assertEqual(result, 17)
        self.assertEqual(observed, ["/usr/local/cuda-13.0"])

    def test_invalid_explicit_cuda_home_fails_before_starting_server(self):
        module = launcher()
        error = io.StringIO()
        with patch.dict(os.environ, {"CUDA_HOME": "/fixture/cuda-13.4"}, clear=True), \
                patch.object(module.platform, "system", return_value="Linux"), \
                patch.object(module.platform, "machine", return_value="aarch64"), \
                patch.object(module.Path, "is_file", return_value=True), \
                patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 0, stdout="Cuda compilation tools, release 13.4, V13.4.88\n")), \
                patch.object(module, "run_native") as run, \
                patch.object(sys, "argv", ["start_sglang.py"]), redirect_stderr(error):
            with self.assertRaises(SystemExit) as raised:
                module.main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("CUDA_HOME", error.getvalue())
        self.assertIn("13.0", error.getvalue())
        run.assert_not_called()

    def test_native_launch_limits_compiler_jobs_and_preserves_operator_override(self):
        module = launcher()
        for override, expected in ((None, "1"), ("2", "2")):
            with self.subTest(override=override):
                environment = {"CUDA_HOME": "/fixture-cuda"}
                if override is not None:
                    environment["MAX_JOBS"] = override
                observed = []

                def run():
                    observed.append(os.environ.get("MAX_JOBS"))
                    return 17

                with patch.dict(os.environ, environment, clear=True), \
                        patch.object(module.platform, "system", return_value="Linux"), \
                        patch.object(module.platform, "machine", return_value="aarch64"), \
                        patch.object(module.Path, "is_file", return_value=True), \
                        patch.object(module, "discover_cuda_home", return_value=Path("/fixture-cuda")), \
                        patch.object(module, "run_native", side_effect=run), \
                        patch.object(sys, "argv", ["start_sglang.py"]):
                    result = module.main()
                self.assertEqual(result, 17)
                self.assertEqual(observed, [expected])

    def test_native_launch_uses_configured_tool_strictness_over_ambient_environment(self):
        module = launcher()
        for preset, configured, ambient in (("flash-next", 2, None), ("flash-next", 2, "0"), ("27b", 0, "2")):
            with self.subTest(preset=preset, ambient=ambient):
                environment = {"CUDA_HOME": "/fixture-cuda"}
                if ambient is not None:
                    environment["SGLANG_TOOL_STRICT_LEVEL"] = ambient
                observed = []

                def run():
                    observed.append(os.environ.get("SGLANG_TOOL_STRICT_LEVEL"))
                    return 17

                with patch.dict(os.environ, environment, clear=True), \
                        selected_preset(module, preset), \
                        patch.object(module.platform, "system", return_value="Linux"), \
                        patch.object(module.platform, "machine", return_value="aarch64"), \
                        patch.object(module.Path, "is_file", return_value=True), \
                        patch.object(module, "discover_cuda_home", return_value=Path("/fixture-cuda")), \
                        patch.object(module, "run_native", side_effect=run), \
                        patch.object(sys, "argv", ["start_sglang.py"]):
                    result = module.main()
                self.assertEqual(result, 17)
                self.assertEqual(observed, [str(configured)])

    def test_native_exit_cleans_only_its_own_ple_directory(self):
        module = launcher()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            ple = base / "ple"
            existing = ple / "existing-session"
            existing.mkdir(parents=True)
            (existing / "keep").write_text("another session")
            marker = base / "session-path"
            server = base / "fake-server"
            server.write_text(
                f"#!{sys.executable}\nimport pathlib, sys\n"
                "directory = pathlib.Path(sys.argv[sys.argv.index('--ple-offload-dir') + 1])\n"
                f"pathlib.Path({str(marker)!r}).write_text(str(directory))\n"
                "(directory / 'weights').write_text('owned files')\nsys.exit(7)\n"
            )
            server.chmod(0o755)
            with selected_preset(module, "flash-next"), patch.object(module.config, "PLE_OFFLOAD_BASE", ple), \
                    patch.object(module.config, "SGLANG_PYTHON", str(server)), redirect_stdout(io.StringIO()):
                code = module.run_native()
            self.assertEqual(code, 7)
            owned = Path(marker.read_text())
            self.assertEqual(owned.parent, ple)
            self.assertFalse(owned.exists())
            self.assertEqual((existing / "keep").read_text(), "another session")

    def test_sigterm_reaches_server_before_owned_ple_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            ready, received = base / "ready", base / "received"
            server = base / "fake-server"
            server.write_text(
                f"#!{sys.executable}\nimport pathlib, signal, sys, time\n"
                "directory = pathlib.Path(sys.argv[sys.argv.index('--ple-offload-dir') + 1])\n"
                "def stop(signum, frame):\n"
                f"    pathlib.Path({str(received)!r}).write_text(str(signum) + ':' + str(directory.exists()))\n"
                "    sys.exit(0)\n"
                "signal.signal(signal.SIGTERM, stop)\n"
                f"pathlib.Path({str(ready)!r}).write_text(str(directory))\n"
                "while True: time.sleep(1)\n"
            )
            server.chmod(0o755)
            code = (
                "import pathlib, sys; sys.path.insert(0, sys.argv[1]); import start_sglang as launch; "
                "vars(launch.config).update(launch.config.MODEL_PRESETS['flash-next']); "
                "launch.config.MODEL_PRESET='flash-next'; launch.config.ENABLE_SPECULATION=True; "
                "launch.config.SGLANG_PYTHON=sys.argv[2]; launch.config.PLE_OFFLOAD_BASE=pathlib.Path(sys.argv[3]); "
                "sys.exit(launch.run_native())"
            )
            process = subprocess.Popen(
                [sys.executable, "-c", code, str(ROOT / "scripts"), str(server), str(base / "ple")],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), "fixture server never became ready")
                process.send_signal(signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 143, stdout + stderr)
                self.assertEqual(received.read_text(), "15:True")
                self.assertFalse(Path(ready.read_text()).exists())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


class CudaDiscoveryTest(unittest.TestCase):
    def test_honors_valid_explicit_cuda_home_with_spaces(self):
        module = launcher()
        home = Path("/custom toolkit/cuda")
        with patch.dict(os.environ, {"CUDA_HOME": str(home)}, clear=True), \
                patch.object(module.Path, "is_file", return_value=True), \
                patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 0, stdout="Cuda compilation tools, release 13.0, V13.0.88\n")) as probe, \
                patch.object(module.shutil, "which") as which:
            self.assertEqual(module.discover_cuda_home(), home)
        probe.assert_called_once_with([str(home / "bin/nvcc"), "--version"],
                                      text=True, capture_output=True, check=True, timeout=10)
        which.assert_not_called()

    def test_invalid_explicit_home_never_falls_back(self):
        module = launcher()
        for home, exists, failure in (("", False, None), ("/missing", False, None),
                                     ("/broken", True, OSError("not executable")),
                                     ("/slow", True, subprocess.TimeoutExpired("nvcc", 10))):
            with self.subTest(home=home), \
                    patch.dict(os.environ, {"CUDA_HOME": home}, clear=True), \
                    patch.object(module.Path, "is_file", return_value=exists), \
                    patch.object(module.subprocess, "run", side_effect=failure), \
                    patch.object(module.shutil, "which") as which:
                with self.assertRaisesRegex(ValueError, "CUDA_HOME.*13.0"):
                    module.discover_cuda_home()
                which.assert_not_called()

    def test_accepts_cuda_13_from_standard_symlink_or_nonstandard_path(self):
        module = launcher()
        for compatible in ("/usr/local/cuda", "/custom/cuda"):
            with self.subTest(compatible=compatible):
                def version(command, **kwargs):
                    release = "13.0" if command[0] == compatible + "/bin/nvcc" else "13.4"
                    return subprocess.CompletedProcess(command, 0, stdout=f"release {release},\n")

                with patch.dict(os.environ, {}, clear=True), \
                        patch.object(module.Path, "is_file", return_value=True), \
                        patch.object(module.subprocess, "run", side_effect=version), \
                        patch.object(module.shutil, "which", return_value="/custom/cuda/bin/nvcc"):
                    self.assertEqual(module.discover_cuda_home(), Path(compatible))

    def test_missing_compatible_toolkit_has_actionable_error(self):
        module = launcher()
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(module.Path, "is_file", return_value=False), \
                patch.object(module.shutil, "which", return_value=None), \
                patch.object(module.subprocess, "run") as probe:
            with self.assertRaisesRegex(ValueError, "CUDA Toolkit 13.0.*CUDA_HOME"):
                module.discover_cuda_home()
        probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
