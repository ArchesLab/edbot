# EdBot

## 1. Start the local model servers

EdBot uses **SGLang 0.5.21 + native MTP** to serve Qwen3.8-Flash-Next on the
DGX Spark, using NVIDIA's pinned NVFP4 checkpoint. Its large N-gram table is
served from local NVMe storage so the model fits the Spark's unified memory.
Ollama serves only `qwen3-embedding:8b` for course-material retrieval.
See [the Spark setup guide](docs/dgx-spark.md) for prerequisites, first-time
installation, SSH access, verification, and troubleshooting.

On the Spark, from this repository:
```bash
bash scripts/install_spark.sh --download-models
# Start Ollama using the command printed by the installer, then:
python3 scripts/start_sglang.py
```

Allow **260 GiB free disk space** for installation, weights, and runtime files.
The installer downloads weights when requested; startup compiles GPU kernels and
creates a fresh roughly 48 GiB N-gram table file. Startup can take several minutes.
The launcher removes only its own temporary table directory after normal shutdown.
Wait for the server to become ready before starting EdBot. The chat endpoint is
`http://127.0.0.1:30000/v1`; port 8000 remains available for Chainlit.

Chat model selection and performance settings are defined in **one code file**,
`src/edbot/model_config.py`, shared by the client and server launcher. The
orchestrator and both subagents inherit the same chat client. The embedding model
is also selected in that shared configuration.
Set `MODEL_PRESET = "27b"` there to select the retained Qwen3.8-27B + DSpark
configuration, which uses its separate SGLang 0.5.19 environment. Flash-Next uses
the native installer; `--docker` is supported only by the 27B preset.

## 2. Start the Chainlit UI

Install dependencies (first time only):

```bash
uv sync --locked
```

Create a `.env` file in the repo root with at least:

```bash
CHAINLIT_AUTH_SECRET=...                # generate one with: uv run chainlit create-secret
EDBOT_TEST_ACCOUNTS=alice:pw1,bob:pw2   # test logins, as username:password pairs
```

Then, from the repo root (Chainlit reads `.env` and `.chainlit/config.toml` from the current directory):

```bash
uv run chainlit run src/edbot/ui/chainlit_app.py --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 and log in with one of the `EDBOT_TEST_ACCOUNTS`. Each username is its own
student, with its own conversation.

The first startup can take a while: EdBot clones the SEBook and builds its embeddings before the UI is ready.

Profiling tools compare warm inference and complete agent turns; see
[the profiling procedure](docs/dgx-spark.md#profile-the-change). No speedup is
assumed until comparable measurements and quality checks have been run.

The terminal interface uses the same backend: `uv run edbot --student dev-cli -v`.

## Verification

```bash
uv run python -m unittest discover -s tests -v
python3 scripts/start_sglang.py --dry-run
```

The tests exercise streaming, tool calls, and structured subagent output against
a local HTTP fixture. Real model correctness and performance must also be checked
on the Spark; see the setup guide.

The latest [tutoring quality review](docs/tutoring-quality-candidate-v7.md) records
successful execution of all nine synthetic turns, but unresolved answer disclosure,
technical accuracy, and assessment issues. The current configuration is a measured
performance candidate, not an accepted tutoring-quality release.

The [selected tutoring policy](docs/tutoring-quality.md#selected-tutoring-policy)
retains concise explanations, Socratic practice and hints, and open-ended replies
with the observed quality limits reported. Study-assignment handling remains as
it is; a restricted reviewed-content delivery path is not selected.
