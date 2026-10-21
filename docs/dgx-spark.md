# DGX Spark installation and performance checks

Publication scope: raw profiling captures, transcripts, server logs, and memory traces are retained locally and omitted from this public branch. `output/profiling/` paths and named review artifacts identify local evidence, not downloadable files. Hashes preserve evidence identifiers; the raw captures are unavailable for independent inspection in this repository.

EdBot defaults to Qwen3.8-Flash-Next through SGLang 0.5.21, using NVIDIA's NVFP4
checkpoint and its built-in multi-token prediction (MTP) head. The large N-gram
embedding table is backed by a file on local NVMe storage. Ollama serves the
separate retrieval embedding model. Parent and child agents share one chat client.
The Qwen3.8-27B + DSpark setup remains available as a code preset with its own
server environment. The student store and Chainlit API remain compatible; the
candidate tutoring harness reduces unnecessary model work as described below.

## Install as a normal user

Clone this repository into a directory owned by your account and run:

```bash
bash scripts/install_spark.sh --dry-run
bash scripts/install_spark.sh --download-models
```

The installer contains the complete native installation procedure. It uses the
current user's home directory and repository location; it contains no lab account
or SSH hostname. It requires Linux ARM64 on a DGX Spark, an installed compatible
NVIDIA 580-series or newer driver and CUDA 13.0 toolkit, build tools, Internet
access, and **260 GiB free disk space** when downloading the Flash-Next preset.
This covers dependencies, its roughly 133 GB checkpoint, and the roughly 48 GiB
runtime table file. Use local NVMe storage for the table. It cannot install a
kernel driver or
change GPU access permissions without an administrator.

The default command without `--download-models` installs software and checks CUDA.
Chat weights then download when the server first starts; pull the embedding model
separately as shown below. The download option prefetches the
pinned Hugging Face checkpoints and the Ollama embedding model. The installer
uses a temporary Ollama process only when a healthy local server is absent; it
leaves existing services alone. Run `--help` for its exact options.

The installations are separate:

- The app uses the repository's `.venv` and `uv.lock` (Python 3.13).
- Flash-Next uses `~/.local/share/edbot/sglang-flash-next` (uv-managed Python 3.12,
  including development headers needed by Triton).
- The optional 27B preset uses `~/.local/share/edbot/sglang`; switching presets
  does not replace the other environment or delete its cached checkpoints.
- Ollama and the installer-managed uv executable live under your home directory.
- Hugging Face weights and JIT kernels use the normal user cache directories;
  Ollama uses its normal user model cache.
- Each Flash-Next launch creates its own table directory under
  `~/.cache/edbot/ple/session-*` and removes it after the launched processes stop.

The selected preset pins SGLang 0.5.21 (0.5.19 for 27B), and the installer pins
CUDA compiler packages to 13.0.3. The compiler
pin matters: unconstrained dependencies can otherwise install CUDA 13.4 components
alongside a CUDA 13.0 driver/toolkit. It verifies the official uv and Ollama
archives against recorded SHA-256 checksums. Python dependencies come from their
package indexes; the server environment is separate from the app's locked environment.
The installer prints an optional `PATH` export for the installed `uv` and Ollama
commands; use it before following examples that invoke those commands by name.
No system packages, shell startup files, Docker permissions, or login policies
are changed. The installer and launcher use the same CUDA discovery policy: an
explicit `CUDA_HOME` must contain a working CUDA 13.0 compiler; otherwise they
check the standard CUDA directories, then the resolved `nvcc` on `PATH`. An invalid
explicit setting stops before installation rather than silently selecting a
different toolkit.

For Flash-Next, the installer also pins `flashinfer-python==0.6.18` and installs
the official `flashinfer-jit-cache` 0.6.18 CUDA 13.0 ARM64 wheel, verified against
its recorded SHA-256. The cache is installed with `--no-deps` to preserve the
resolved runtime dependencies. Its precompiled `fused_moe_120` module avoids the
large first-start MoE build; installation checks that this module loads with
JIT compilation disabled. The wheel uses SM120-family cubins, which this
[FlashInfer release explicitly supports on DGX Spark](https://flashinfer.ai/releases/#v0-6-18),
as recorded in the [versioned build matrix](https://github.com/flashinfer-ai/flashinfer/blob/v0.6.18/ci/cuda-versions.json).
The [official cache wheel](https://github.com/flashinfer-ai/flashinfer/releases/download/v0.6.18/flashinfer_jit_cache-0.6.18%2Bcu130-cp39-abi3-manylinux_2_28_aarch64.whl)
adds about 1.13 GB of download. It covers common kernels, not every operation;
uncached kernels can still compile with the launcher's default `MAX_JOBS=1` to
bound compiler memory use. Existing JIT caches remain reusable. The optional
27B preset retains its previous dependency and cache-installation behavior.

## Start both services

In one Spark terminal, use the Ollama executable path printed by the installer:

```bash
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_KEEP_ALIVE=-1 \
  "$HOME/.local/share/edbot/ollama/bin/ollama" serve
```

If an Ollama service already responds on port 11434, reuse it. In another terminal,
pull the embedding model if the installer did not already do so:

```bash
"$HOME/.local/share/edbot/ollama/bin/ollama" pull qwen3-embedding:8b
```

Then, from the repository, start chat inference:

```bash
python3 scripts/start_sglang.py --dry-run
python3 scripts/start_sglang.py
```

The native launcher binds to `127.0.0.1:30000`, adds the server environment's tools
to `PATH`, and verifies a CUDA 13.0 compiler, matching the installer. A valid
explicit `CUDA_HOME` takes precedence; an invalid one stops launch with an error.
Otherwise it checks `/usr/local/cuda-13.0`, `/usr/local/cuda`, then the compiler on
`PATH`, accepting only CUDA 13.0. Set `CUDA_HOME` for a nonstandard location.
The first start can spend several minutes downloading
weights and compiling GPU kernels. Cached restarts in the chunk-size experiment
still took roughly 12–13 minutes on this host, including the main weights and MTP
head. Keep this startup cost separate from replies served by the resident model.
Every Flash-Next start also writes the N-gram
table to a fresh roughly 48 GiB file under the configured `PLE_OFFLOAD_BASE`.
Wait for readiness before sending requests. The launcher forwards Ctrl+C and
SIGTERM to its own server process group before removing that launch's table
directory; stop the launcher normally so workers finish before cleanup.

Flash-Next has more weights than fit in one Spark's unified memory. Moving its
table to ordinary CPU memory would still consume the same pool; the file-backed
backend is required here. A fresh directory also avoids the upstream slow rewrite
of a previously populated table. After a forced kill or power loss, an old
`session-*` directory can remain. It is not reused or automatically removed by a
different launch; remove it only after confirming no process is using it.

For a background process instead of a foreground terminal:

```bash
mkdir -p "$HOME/.local/state/edbot"
nohup python3 scripts/start_sglang.py \
  > "$HOME/.local/state/edbot/sglang.log" 2>&1 < /dev/null &
echo $! > "$HOME/.local/state/edbot/sglang.pid"
tail -f "$HOME/.local/state/edbot/sglang.log"
```

Check an existing PID and port before starting a second instance. `nohup` is not
a reboot service and cannot override a host policy that kills user processes on
logout. On hosts without user lingering, do not assume a user systemd service
will survive the last login session. Automatic restart is a separate deployment
choice.

Once ready:

```bash
curl --fail http://127.0.0.1:30000/health
curl --fail http://127.0.0.1:30000/v1/models
uv run python scripts/check_sglang.py
```

The smoke check verifies streamed chat and both structured child output schemas
using synthetic content. It does not access student conversations and is not a
quality or performance benchmark. Use `--output output/profiling/smoke.json`
after creating that directory to retain timings, tool arguments, and validation
errors; it runs all three checks and refuses to overwrite an existing report.
Follow the README to configure Chainlit
credentials and start the UI. Keep inference ports private; use an SSH tunnel
when the app runs on another computer:

```bash
ssh -N -L 30000:127.0.0.1:30000 -L 8000:127.0.0.1:8000 USER@SPARK
```

`EDBOT_CHAT_BASE_URL` overrides the client endpoint (include `/v1`), and
`EDBOT_CHAT_API_KEY` can supply a proxy key. The local setup needs no OpenAI
account or real OpenAI API key. A remotely running app also needs access to the
Ollama embedding endpoint; running EdBot on the Spark avoids that extra tunnel.

## Shared configuration

Edit `src/edbot/model_config.py`; model selection is a code setting shared by the
app, launcher, installer, and profiling tools. There is no model selection flag
on the app command line.

| Setting | Default | Purpose |
| --- | --- | --- |
| Code preset | `MODEL_PRESET = "flash-next"` | Shared model selection |
| Target | `nvidia/Qwen3.8-Flash-Next-NVFP4` | NVIDIA mixed-precision export |
| Target revision | `fc694b54fb0174e0913e6adf86691ef85a4ead47` | Reproducible checkpoint |
| Server | SGLang 0.5.21, native Python 3.12 | Flash-Next and GB10 support |
| Draft | Built-in MTP head; no separate checkpoint | `NEXTN` speculative decoding |
| Embeddings | `qwen3-embedding:8b` | Existing course-material retrieval |
| Embedding context | `EMBEDDING_CONTEXT_LENGTH = 8192` | Bound allocation; oversized inputs fail with `truncate=False` |
| Context | 32,768 tokens | Shared server/client context budget |
| Output cap | 4,096 tokens per model call | Bound output generation |
| Thinking | Disabled | Latency preset; `ENABLE_THINKING` controls it |
| Sampling | `GENERATION_TEMPERATURE = 0.0` | Keep application sampling aligned with the evaluation |
| Tool transport | `BUFFER_TOOL_RESPONSES = True` | Use the complete-response tool parser; calls without tool schemas can still stream |
| Content delivery | `DIRECT_CONTENT_DELIVERY = True` | Deliver a complete validated CGA-only response without a parent rewrite |
| Tutor harness | `REDUCED_TUTOR_HARNESS = True` | Keep course reads and context recovery; restrict delegation to declared course specialists |
| Source reuse | `REUSE_COURSE_EVIDENCE = True` | Supply bounded, successful current-turn retrieval results to children; search again when evidence is insufficient |
| Assessment persistence | `DETERMINISTIC_ASSESSMENT_SAVE = True` | Save the final validated assessment in code, removing the model's separate write call |
| Assessment prior prefetch | `PREFETCH_ASSESSMENT_PRIOR = False` | Disabled experiment: read the fresh UCA prior in code before generation |
| Content after assessment | `REQUIRE_CONTENT_AFTER_ASSESSMENT = True` | Require a later matching CGA task before the parent can answer an assessed turn |
| Child tool policy | `SERIAL_CHILD_TOOL_CALLS = True` | Prevent multiple final outputs per generation; also serializes independent child searches |
| Speculation | Enabled | `ENABLE_SPECULATION` permits a same-model comparison |
| Static memory fraction | 0.85 | Budget resident weights and inference pools |
| Concurrent requests | 2 | Limit memory use for this teaching workload |
| Total KV capacity | `MAX_TOTAL_TOKENS = 131072` | Two active 32K contexts plus retained prefixes; about 3 GiB of BF16 KV |
| Prefill chunk | 2,048 tokens | Limit decode stalls during prompt processing |
| Cache | Automatic KV dtype; FP32 GDN state | Preserve model defaults and recurrent precision |
| Recurrent-state slots | 20, under `extra_buffer` | Ten slots per running request; preserved the tested parent prefix after four child calls |
| Cache reporting | Enabled | `--enable-cache-report` reports cached prompt tokens |
| Tool schema enforcement | `TOOL_STRICT_LEVEL = 2` | Constrain tool parameters using the existing schemas |
| CUDA compiler jobs | `COMPILER_JOBS = 1` | Bound build-time RAM while weights remain resident; explicit `MAX_JOBS` overrides it |
| N-gram table | File-backed on local NVMe | Keep the large table outside resident weight memory |

The launcher lets SGLang select Flash-Next's QSA attention and mixed-precision
loader. It pins the FP4 GEMM and MoE backends to `flashinfer_cutlass`, and includes
the Qwen reasoning parser, `qwen3_coder` tool parser, and XGrammar for structured
output. Native MTP uses three speculative steps, top-k one, and four draft tokens.
The 27B DSpark checkpoint is not compatible with this target and is not downloaded
or loaded for Flash-Next.

For Flash-Next, the launcher exports `SGLANG_TOOL_STRICT_LEVEL=2` from the shared
code setting.
SGLang's parameter-level grammar uses the tool schemas supplied by LangChain,
including nullable fields and optional properties. This avoids changing tool APIs
or making every optional field required through client-side `strict=True` schema
conversion. The initial live UCA smoke test returned the string `"None"` for a
nullable tier instead of JSON `null`; ordinary named tool selection did not enforce
its parameter schema. Keep the app's Pydantic validation and retries: grammar
cannot guarantee assessment quality or validate JSON embedded inside the string
`task.description`. See the [versioned enforcement code](https://github.com/sgl-project/sglang/blob/v0.5.21/python/sglang/srt/function_call/function_call_parser.py).
Restart the server after changing this setting. No LangChain upgrade is required;
all previously locked package versions are preserved.
The retained 27B preset keeps level zero: parameter grammars can disable DSpark's
folded acceptance path, so that separate correctness/performance comparison has
not been applied silently to the fallback.

The [pinned NVIDIA chat template](https://huggingface.co/nvidia/Qwen3.8-Flash-Next-NVFP4/blob/fc694b54fb0174e0913e6adf86691ef85a4ead47/chat_template.jinja)
explicitly supports `enable_thinking=false`, which
the client sends for this latency preset. This was checked in the checkpoint's
actual template; the cookbook's statement that this model always reasons is stale
for the selected template. `ENABLE_THINKING` remains the shared code switch.

The same pinned template defaults enabled reasoning to `reasoning_effort="xhigh"`.
It also accepts `"medium"` and `"low"` through `chat_template_kwargs`; the low
setting requests brief reasoning. Thus changing only `ENABLE_THINKING` to true
also activates the template's highest default effort. This is a prompt setting,
not a guaranteed token budget. Compare the complete content task, including any
extra source searches, before selecting a reasoning mode for its quality/cost
tradeoff. The production preset still disables thinking.

The memory and concurrency settings are conservative starting values, not measured
optima. Check available memory with embeddings loaded before increasing them.
Disabling thinking and changing weight/cache precision can affect assessment
quality. Compare rubric adherence and tool success on representative answers;
fast but incorrect assessments are not an improvement. The embedding model and
vector-store fingerprint are unchanged, so a valid existing index remains reusable.

To use the retained 27B preset, set `MODEL_PRESET = "27b"` in the same file and
rerun the installer if its environment is not installed. Stop the current chat
server, launch the selected preset, and restart EdBot. This selects SGLang 0.5.19,
the pinned RadixArk NVFP4 target and DSpark draft, static memory fraction 0.70,
four requests, FP8 KV cache, and 16 recurrent-state slots under `extra_buffer_lazy`.
Its DSpark block size is seven and the draft runs unquantized. Both presets retain
their own environments and cached weights; run only one chat server at a time.

## Profile the change

Use two levels of measurement: direct inference separates server behavior, while
complete EdBot turns include routing, tools, retrieval, subagents, and final
synthesis. Run on an otherwise idle Spark and record server settings, logs,
versions, available memory, and model identity with each comparison. Never run
baseline and optimized chat models simultaneously for a single-model comparison.
Leave embeddings in the same state across both runs.

The repository provides `scripts/profile_inference.py` for streaming inference
and `scripts/profile_agent.py` for complete app turns. Their `--help` output lists
all options. Both write machine-readable results; the app profiler isolates its
student histories in temporary databases. The shared textbook index can be built
or refreshed during startup, which is reported separately.

For the optimized server, once the smoke check passes:

```bash
mkdir -p output/profiling
python3 scripts/profile_inference.py --backend sglang --thinking off \
  --max-tokens 512 --output output/profiling/flash-next-prefix-reuse.json
python3 scripts/profile_inference.py --backend sglang --thinking off \
  --cache-mode isolated --max-tokens 512 \
  --output output/profiling/flash-next-prefix-miss.json
uv run python scripts/profile_agent.py --backend sglang \
  --repetitions 3 --warmups 1 --output output/profiling/agent-flash-next.json
```

The profiler's Ollama baseline is still `qwen3.8:27b`. For a 27B stack comparison,
first select `MODEL_PRESET = "27b"` and collect its SGLang results. Stop the SGLang
process you started, pull `qwen3.8:27b` into Ollama, and repeat with
`--backend ollama` and new report names. After the baseline, unload that chat model
with `ollama stop qwen3.8:27b` before restarting SGLang. Perform these service
changes only when no one is using them. Comparing Flash-Next with this Ollama
baseline changes both the model and serving stack; it cannot isolate an engine
speedup. Record the active preset and checkpoint with every report.
The profilers never stop services or unload models automatically. Both profilers
refuse to overwrite reports. A nonzero exit means at least one request failed or
was truncated; inspect the JSON instead of treating it as a fast successful run.

The inference script defaults to one initial request plus three measured repeats
for each short/long prompt, a 256-token output budget, and temperature zero. The
app script uses the configured 4,096-token cap and an explanation → practice
question → answer conversation, with fresh synthetic student state per repetition.
It sets temperature zero and requests streaming token usage for profiling. Its
Ollama mode runs the current agent workflow with the same context/output/thinking
settings; it does not reconstruct the unrecorded historical two-minute run.
Generated questions and agent paths can differ between conditions.

The long direct-inference prompt has about 6,539 tokens with the pinned tokenizer,
so it crosses multiple 2,048-token prefill chunks. `--cache-mode reuse` repeats
the same prefix; `--cache-mode isolated` sends a fresh recorded SGLang `cache_salt`
for every request, including warmups. This measures a resident model with prefix
misses, not cold weights or a cold filesystem. It does not flush the shared cache;
new entries can still consume cache capacity. Cache isolation is unsupported in
the Ollama comparison. Inspect `cached_prompt_tokens` rather than assuming a
particular hit rate.

Four controlled comparisons answer different questions:

1. **Flash-Next without versus with MTP:** change `ENABLE_SPECULATION` in the code
   configuration, restart the server, and repeat the same workload. Keep the
   checkpoint, other settings, and available memory constant.
2. **27B Ollama versus SGLang + DSpark:** hold prompts, context, output cap, thinking
   mode, and concurrency constant. This compares the deployed stacks, including
   their different checkpoint quantization; it does not isolate DSpark's effect.
3. **27B SGLang without versus with DSpark:** change `ENABLE_SPECULATION` in the code
   configuration, restart the server, and repeat the same workload. Keep the
   target checkpoint, other settings, and available memory constant.
4. **Reasoning versus latency preset:** compare thinking enabled versus
   disabled separately and review answer quality. Do not attribute that difference
   to a faster inference engine.

Keep initial requests separate from warm measurements: a first request is not
necessarily cold if another client has already warmed the model. Allow warm-ups,
repeat each condition, and alternate condition order if possible. Record both
first visible text and completion latency. Throughput is meaningful only with
actual output token counts, and shorter responses can reduce total latency
without increasing decoding speed. Retain failed or truncated runs as failures.

For full turns, compare model-call counts as well as their durations. Nested tool
and model timings can overlap, so summing them or subtracting their sum from total
latency is not a reliable overhead calculation. A faster decoder cannot remove
serial routing and subagent generations. The candidate direct-delivery path
removes the final parent generation only for complete CGA-only turns. It does
not introduce a small decision model or replace routing and assessment.
The profiler's success flag means a visible, nontruncated completion; recovered
tool errors can still occur. Middleware-rejected routing calls can bypass tool
callbacks, and LangChain's structured-output retries need not mark their returned
messages with an error status. Tool error spans are therefore not a complete
retry count. Review console diagnostics and model-call counts together.

## Measured Flash-Next results

On 2026-10-18, the lab Spark completed paired Flash-Next runs using SGLang 0.5.21,
the pinned NVIDIA checkpoint, thinking disabled, and a 131,072-token KV cap. The
baseline full-agent report (local capture `output/profiling/agent-flash-next-mtp-off.json`)
began at 09:22 UTC; the optimized report (local capture `output/profiling/agent-flash-next-mtp-on-strict.json`)
enabled MTP and level-2 tool-schema enforcement. Each contains **one sample per
scenario, no warmup**, in an explanation → practice → answer conversation.
Application startup is excluded; the baseline spent 2.61 seconds starting,
including 2.16 seconds for SEBook setup. This does not reconstruct the original
unrecorded Ollama run. The comparison report (local capture `output/profiling/flash-next-comparison.json`)
retains paired metrics and hashes of its source reports.

Every cell below shows **baseline → optimized**:

| Turn | Total (s) | Model generations | First visible text (s) | Final parent rewrite (s) |
| --- | ---: | ---: | ---: | ---: |
| Explanation | 102.65 → 63.60 | 7 → 6 | 81.64 → 52.47 | 27.96 → 17.44 |
| Practice question | 135.63 → 77.28 | 6 → 5 | 121.40 → 72.56 | 22.17 → 11.61 |
| Submitted answer | 181.70 → 105.26 | 11 → 12 | 157.43 → 95.60 | 33.16 → 17.61 |

These sampled full turns completed 38–43% sooner. Both runs produced visible,
nontruncated replies in all three scenarios. Output tokens across all model calls
were 1,294 → 1,371, 2,023 → 2,035, and 2,594 → 2,564 respectively. The
environment check (local capture `output/profiling/environment-flash-next-mtp-on.json`)
confirmed unchanged profiled application files, corpus fingerprint, and embedding
residency. Agent paths and generated questions still differed, and the optimized
run also changed grammar policy; these full-turn differences do not isolate MTP
or establish average user latency. MTP remains enabled based on the completed
direct and full-turn measurements.

Across the conversation, elapsed time fell from 419.98 to 246.14 seconds (41.4%),
while output tokens rose from 5,911 to 5,970 and model calls fell from 24 to 23.
The initial parent input was 7,709 tokens in both runs. Shorter total output does
not explain this gain. The optimized assessment made one additional content-agent
retrieval round; its extra generation is not evidence of a validation retry.

In the baseline, model spans account for 95.0%, 99.2%, and 99.4% of elapsed time. Non-task
tools occupied about 4.86, 0.90, and 0.91 seconds respectively, after merging
overlapping intervals. Nested `task` spans include child generations and must
not be added to model time. The three turns generated 1,294, 2,023, and 2,594
output tokens across all calls. Repeated generation, including the final rewrite
of already student-facing child content, dominates this baseline.

Timing places four parent and three content-agent calls in the explanation.
Practice has three parent and three content-agent calls; a runtime validation
rejection precedes the accepted delegation, but the rejected call has no tool
error span in the report. The answer has four parent, four assessment-agent,
and three content-agent calls. Child roles are inferred from tool sets and
timing; task arguments are not retained. A reported successful turn can therefore
include recovered errors, and these counts do not establish complete retry counts.

Direct inference was much shorter, and its paired MTP comparison is complete.
The reports cover prefix reuse with MTP off (local capture `output/profiling/flash-next-mtp-off-reuse.json`)
and MTP on (local capture `output/profiling/flash-next-mtp-on-reuse.json`), plus isolated
prefixes with MTP off (local capture `output/profiling/flash-next-mtp-off-isolated.json`)
and MTP on (local capture `output/profiling/flash-next-mtp-on-isolated.json`). Each condition
excludes one initial warmup and measures three successful requests per prompt.
Prompt hashes and request settings match between paired conditions: a 512-token
output cap, temperature zero, seed 42, and thinking disabled. Server metadata
verified the selected checkpoint and serving settings. No direct-inference
request supplied tools, so the tool-schema strictness policy introduced for the
MTP run was inert for these plain-text calls.

Every cell below shows the median **MTP off → on**. The rate is the median of
each request's completion tokens divided by its entire elapsed time, including
prefill and transport; it is not pure decoding throughput.

| Prompt | Cache mode | Total (s) | First visible text (s) | Output tokens | Completion tokens / elapsed second |
| --- | --- | ---: | ---: | ---: | ---: |
| Short, 58 tokens | Reuse | 11.08 → 6.78 | 0.221 → 0.264 | 179 → 165 | 16.16 → 24.35 |
| Short, 58 tokens | Isolated | 10.38 → 6.59 | 0.224 → 0.266 | 172 → 160 | 16.57 → 25.88 |
| Long, 6,539 tokens | Reuse | 10.25 → 6.28 | 0.160 → 0.200 | 169 → 165 | 15.93 → 23.28 |
| Long, 6,539 tokens | Isolated | 12.98 → 11.32 | 2.977 → 3.146 | 167 → 198 | 12.77 → 17.76 |

On these prompts, the median whole-request token rate improved by 39–56% with
MTP. First visible text arrived slightly later: about 40 ms for short or cached
prompts and 170 ms for the long isolated prompt. The reused long prompt reported
6,528 cached tokens in both conditions. Other missing cache counts remain
unknown, not zero. Isolated requests keep the model resident and use a fresh
cache salt; they do not measure cold weights or filesystem caches.

The server's `raw_metadata.sglext.spec_tokens_details` reported 1,215 accepted
draft tokens out of 2,493 proposed across the twelve measured MTP requests,
about 49%. Outputs varied despite the fixed temperature and seed; differing
lengths explain part of the elapsed-time changes. Decode and prefill durations
were not reported, so these measurements do not establish a pure decoding
speedup or predict complete-agent latency.

Quality review found no visible agent, tier, confidence, rubric, or answer-key
leakage in either three-turn conversation. However, the baseline final answer says preserving the
interface requires deleting `getRecords()`, claims clients stay untouched, and
then acknowledges changing one client. It mixes an API migration with a
storage-only swap. A `Map` return type also need not expose the backing storage:
an adapter or snapshot could preserve that interface, depending on its contract.
The optimized question preserves the public interface and avoids that particular
deletion contradiction, but changes the scenario to a CSV-to-SQL migration. It
therefore does not establish that the baseline misconception was corrected. It
still has three subtasks and overstates what passing implementation-swap tests
can prove. The same canned learner answer was assessed against different generated
questions, so the assessment scores are not a controlled quality comparison.
Both runs produce lengthy replies and omit source citations;
retrieved passages and internal rubrics are unavailable for a full grounding or
grading audit. Completion success is not a quality certification.

The baseline smoke report (local capture `output/profiling/smoke-flash-next-mtp-off.json`)
reproduced the invalid string `"None"` in `UCAOutput.prior_tier`. The
optimized smoke report (local capture `output/profiling/smoke-flash-next-mtp-on-strict.json`)
returned JSON `null` and passed streaming, UCA, and CGA validation. Actual server
environment inspection confirmed strict level 2; the optimized server log showed
no matching schema-construction or grammar-fallback errors during these runs.
This validates the exercised formats and tool paths, not every possible schema
or the semantic accuracy of assessments.

## Further optimization candidates

Keep the recorded baseline and distinguish implemented experiments from accepted
improvements. Change one serving setting at a time and retain quality failures.

- **Retain useful prompt prefixes.** The controlled
  [capacity experiment](#parentchild-prefix-cache-experiment) now supports twenty
  Mamba cache states at two running requests: all three interleaved final parent
  requests retained 8,960 cached tokens, removing the roughly 3.94-second
  first-text penalty observed with ten states. KV capacity remained 131,072
  tokens. This synthetic result does not establish full-turn tutoring speed or
  memory headroom; measure both with the embedding model resident.
  The subsequent [chunk-size experiment](#prefill-chunk-size-experiment) compared
  2048 with 4096 while holding concurrency, model, output budget, and embedding
  residency fixed. The larger setting passed the numerical screen but remains
  unadopted because quality preservation is unestablished; settings live in
  [model_config.py](../src/edbot/model_config.py) and
  [start_sglang.py](../scripts/start_sglang.py).
- **Count serial generations and repeated retrieval.** The parent checks sources,
  the CGA searches again, and the parent synthesizes the CGA's student-facing text.
  UCA assessment adds prior lookup, retrieval, persistence, and structured output.
  See the [parent](../src/edbot/prompts/orchestrator_prompt.md),
  [CGA](../src/edbot/prompts/cga_prompt.md), and [UCA](../src/edbot/prompts/uca_prompt.md)
  contracts. Direct CGA delivery, current-turn evidence reuse, and deterministic
  UCA persistence are enabled and evaluated below. The optional Human-message
  prior prefetch remains disabled after its copied-answer calibration regression.
  A code-owned lookup preserving the original tool-result transcript is a separate
  diagnostic, not an enabled replacement. Mechanical savings do not establish
  grounding or assessment quality.
- **Expose typed child inputs.** The current SGLang path advertises typed task
  branches while preserving DeepAgents' executable string API and existing
  [input validation](../src/edbot/middleware/validate_input.py). The v7 run has no
  invalid child inputs; its semantic failures remain. Ollama retains its original
  string schema because its installed client drops the needed outer union.
- **Bound child evidence deliberately.** Role-separated public history and
  current-turn source evidence now initialize fresh children before compaction.
  The parallel child-state repair and v7 review are documented below. A character
  limit on retrieved passages alone does not bound the whole context; long-history
  continuity and resume behavior still need broader evaluation.
- **Review unnecessary harness tools.** [Agent construction](../src/edbot/edbot_agent.py)
  inherits DeepAgents filesystem tools and its default general-purpose subagent.
  The reduced harness now removes model-facing writes and rejects undeclared
  subagent targets while preserving reads for skills and summary recovery.
  Exact-query retrieval caching remains unimplemented. In the recorded v7
  "still stuck" turn, one repeated query returns identical course text and takes
  0.266 seconds, only 0.075% of the nine-turn total. Eliminating that entire call
  would be an upper bound before cache overhead, not a measured speedup. That
  opportunity does not currently justify another cache layer; any future cache
  must distinguish path filters and invalidate with the loaded corpus/embedding
  snapshot.
  A local synthetic capture (local capture `output/profiling/prompt-overhead.json`) measured
  20,419 parent system-message characters plus 11,500 characters of compact tool-schema
  JSON; seven inherited filesystem tool schemas account for 7,418 characters.
  These are character counts, not model tokens or measured speedups; retain `read_file`
  for currently used skills and offloaded-history recovery when narrowing the tool set.
- **Preserve the visible-output boundary.** [service.py](../src/edbot/service.py)
  buffers each complete parent message until its finish reason and tool-call
  status are known, and hides child output. A fixed character holdback cannot
  suppress arbitrarily long tool preambles. The event API remains compatible,
  but text arrives as a completed message, delaying first visible text without
  adding inference. Direct CGA delivery avoids a parent rewrite where eligible.
- **Control routing when interpreting results.** The prompt requires a study
  condition, but [EdbotContext](../src/edbot/interface_def.py) currently contains
  only `student_id`. Different UCA call counts can reflect an undefined routing
  condition rather than a faster backend; compare agent paths and answer quality.

### Application candidate-v1

The six-case, nine-turn baseline (local capture `output/profiling/tutoring-baseline-v1.json`)
and candidate-v1 (local capture `output/profiling/tutoring-candidate-v1.json`) used the same
resident ten-state MTP server, temperature zero, and one pass per case. Candidate-v1
enabled direct content delivery, the reduced harness, and prompt/output-boundary
repairs. It did not yet include retrieved-evidence reuse or role-separated child
history. First parent input fell from 7,731 to 5,867 tokens.

| Metric across nine turns | Baseline | Candidate-v1 |
| --- | ---: | ---: |
| Total elapsed seconds | 430.95 | 403.82 |
| Model generations | 56 | 72 |
| Output tokens across model calls | 10,300 | 9,656 |
| Persisted UCA assessments | 0 | 4 |

The sampled total fell 6.3%, with large per-turn variation and more assessment
calls. This does not isolate the forwarding speedup or establish typical latency.
The first three eligible candidate replies exactly match child content, confirming
that a parent rewrite was avoided. Undefined study-condition routing confounds
the overall comparison.

Neither run meets the quality acceptance criteria. The [baseline review](tutoring-quality-baseline.md)
and [candidate review](tutoring-quality-candidate-v1.md) retain complete locators:
candidate-v1 repairs the explicit Map-contract answer but still discloses an answer
after a Socratic request, gives an answer-bearing prerequisite explanation, and
generates a contradictory private practice rubric. Schema validation cannot detect
these semantic failures. Faster completion alone does not justify adoption.

The isolated eight-case UCA baseline (local capture `output/profiling/assessment-baseline-v1.json`)
removes parent routing variation. All eight cases returned structured results and
made one update, but every result failed exact saved/returned rationale equality;
tier and confidence matched. The run is therefore recorded as failed, not a
successful assessment benchmark. Its separate update-only generations took a
total of 44.10 seconds. Moving persistence into code is a measured opportunity to
remove those generations and prevent independently generated audit records.

### Code-owned assessment persistence

`DETERMINISTIC_ASSESSMENT_SAVE` controls an independently testable candidate in
[assessment_result.py](../src/edbot/middleware/assessment_result.py). When enabled,
the UCA still fetches the prior and retrieves evidence, but has no write tool.
The parent task boundary validates the completed output against its actual input,
current student identity and prior, then saves the exact tier, confidence and
rationale returned to the parent. It does not decide whether to assess, assign a
study condition, or change the assessment schema or tier policy.

The entry and a private replay receipt are written in one SQLite statement. A
replayed task with the same identity and input returns the saved result without
another generation, count increment, or timestamp change. A stale task cannot
overwrite a newer assessment. The completion guard rejects malformed/truncated
output and failed evidence tools; output emitted alongside pending tools is
deferred until their results arrive. Receipts are outside the student-model
namespace exposed by the existing API.

This relies on the current single-process SQLite service. A process-local lock
serializes assessments for the same student; it is not a database compare-and-swap
for future multi-worker deployments or arbitrary replacement stores. If two
same-concept assessments in one parent batch both commit before a crash, replay
of the older one is conservatively rejected as stale. This avoids overwriting
newer evidence but does not transparently reconstruct that whole batch. The
enabled path uses the application's existing async API; synchronous non-assessment
and disabled-mode calls retain their previous tool behavior.

Local tests cover exact persistence, isolated identities, SQLite reconnect and
replay, lost commit acknowledgement, concurrent tasks, stale results, and
incomplete/tool-failed child output. Live timing and semantic assessment remain
separate acceptance checks. The component evaluator records actual committed
student-model writes separately from model `update_student_model` tool calls,
so removing the tool does not disguise a missing or duplicate write.

The paired eight-case component run with saving off (local capture `output/profiling/assessment-save-off-v3.json`)
and on (local capture `output/profiling/assessment-save-on-v3.json`) used the same resident
ten-state server and otherwise identical application files. Calls fell from 28
to 20, output tokens from 3,824 to 2,815, and summed assessment time from 138.37
to 105.93 seconds (23.4%). Every case saved exactly once in both conditions;
exact saved/returned agreement improved from 0/8 to 8/8. The off run fails the
mechanical agreement check, so its timing is not a successful-assessment baseline.

These are one sample per case per setting, with the necessarily different write
instructions and tool set. Generated assessments and retrieval paths varied;
this is neither a repeated latency distribution nor proof that all saved time
comes from one removed generation. The [semantic review](tutoring-quality-candidate-v2.md#separate-v3-uca-component-comparison-model-save-versus-code-save)
accepted exact persistence in this sample, but found copied-answer promotion and
incorrect attribution of earlier assistance in the model's judgments. The code
flag remains enabled for exact saving; it does not certify the assessment model
or the full tutor.

### Fresh assessment prior before generation

`PREFETCH_ASSESSMENT_PRIOR` defaults to `False`. The optional
[assessment-prior middleware](../src/edbot/middleware/assessment_prior.py) applies
only to the code-persisted UCA path. Before the child starts, it validates the
single internal `UCAInput`, normalizes its concept, and freshly reads the entry
from the runtime store using the trusted runtime student identity. The parent
assessment wrapper already holds its student lock across child execution; the
child neither reacquires that lock nor reuses a parent snapshot. Missing entries
are represented explicitly as `entry: null`; missing identity/store, invalid
input, and read failures stop the assessment rather than inventing an empty
prior. There is no cross-invocation prior cache or additional write.

The actual child messages contain public Human/AI history, optional course
evidence, the application-supplied prior as a Human JSON message, then the
unchanged internal task. Request instructions identify the prior by that
position, and keep lookalike JSON in learner history untrusted. A public
`PrivateStateAttr` marker remains inside the child; it is absent from child task
results and parent state. Ordinary tool continuation retains the prior and
tool-call/result pairing. Re-entering an already prefetched child fails closed
and requires a fresh task, avoiding stale injected data. The existing parent
receipt replay can still return a completed assessment without invoking the
child.

The canonical UCA prompt file is unchanged. Exact request-only substitutions
replace the lookup instructions and remove only the model-facing
`fetch_student_data` descriptor. Rich system-message blocks and metadata are
preserved; unfamiliar, split, or ambiguous prompt spans retain the original
prompt/tool path. The executable lookup tool stays registered. Assessment
policy, evidence rules, output schema, prior validation, stale-result rejection,
and atomic entry/receipt persistence are unchanged. The implementation uses the
existing public LangChain/LangGraph APIs (`abefore_agent`, runtime context/store,
`Overwrite`, `PrivateStateAttr`, and `ModelRequest.override`), without a library
upgrade or service API change. Like deterministic saving, the enabled path uses
`ainvoke`/`astream`.

The [eight focused tests](../tests/test_assessment_prior.py) exercise actual
mocked HTTP roles, tool continuation, trusted student/concept isolation, rich
message fallback, private-state boundaries, and a real graph with parallel
same-student assessments. In that graph the second child reads the first child's
committed result; replay produces no new generation or write, and a changed
store still triggers the existing stale-prior guard. The related 52-test suite
passed; after the input-provenance wording and component-report metadata change,
18 focused tests passed. Both profiling scripts record the effective flag.

The paired component report (local capture `output/profiling/assessment-prior-prefetch-paired.json`)
(SHA-256 `79d031a893ddb51d51b483bb794ad6ff746b95055712c2a3efcd9b01b5e3f96e`)
contains four sequential runs in OFF/ON, ON/OFF order. Each run assessed the same
three synthetic cases once, using fresh isolated student stores and checkpoints.
The captured case inputs, source manifests, and resident twenty-state server
configuration match across runs; no model/server restart occurred. The
temporary in-process flag override is recorded in each profile and restored
after each run; source manifests describe the unchanged disabled file default.
The evaluator uses a deterministic parent and produces no learner-facing reply.

| Six assessments per condition | Prefetch off | Prefetch on |
| --- | ---: | ---: |
| Summed component time (`total_s`, excluding startup) | 71.703 s | 65.235 s |
| Model generations | 19 | 12 |
| Input tokens | 113,979 | 71,626 |
| Output tokens | 1,803 | 1,703 |
| Exactly one consistent student-model write | 6/6 | 6/6 |

All twelve observations completed without tool/model errors, truncation, or
invalid tool calls. Every enabled model request contained exactly the current
stored prior (or explicit null) for the target concept and omitted the lookup
descriptor; each disabled assessment performed one successful lookup of the
same prior. Each write matched the returned assessment and incremented the
correct student's assessment count once. Mean component times over two samples
per condition were 9.903→8.905 seconds for cold start, 11.753→11.365 for a copied
answer, and 14.195→12.347 for a changed item after support.

**Keep the flag off: the observed calibration regression fails semantic
acceptance.** Both enabled copied-answer assessments retained the seeded
`Understand` tier but returned `medium` confidence, whereas both disabled
assessments returned `low`. The captured confidence rule requires `low` when an
estimate mostly carries the prior forward. One enabled rationale additionally
says the explicitly copied answer “confirms the prior Understand estimate”
despite acknowledging that it cannot be attributed to the student's reasoning.
Correct persistence does not make this evidence attribution sound. The cold
start's provisional `Understand`/`Apply` values are not themselves failures: the
fixture specifies no gold initial tier, and both enabled results retain low
confidence and a next probe rather than claiming demonstrated attainment.

The 9.0% lower summed component time and seven fewer generations are observations
from this small comparison, not an accepted optimization or a whole-tutor
speedup. There are only two samples per case and setting; cache occupancy and
generated text varied. Prefetch also changes the prompt and prior's message
position, so this comparison cannot isolate why calibration changed or assign
all timing differences to the removed lookup generation. The raw report's
`quality: not_reviewed` is preserved; the semantic decision is documented here.

#### Tool-result-shaped prior: copied-answer diagnostic

The follow-up report (local capture `output/profiling/assessment-tool-seeded-prior-v1.json`)
(SHA-256 `8d33ac8dc1b91b3b40b76aff95f2910df90ca854a785966527882dd9507017d0`)
compares OFF, the existing Human-message prefetch, and a temporary tool-result
loader on the same copied-answer case. Order was OFF/Human/tool, then
tool/Human/OFF, with two isolated observations per condition. The fixture hash is
`3f531d4e58fd9c0ab055f5c1990cc22d53fc62d20007a34715df1d236e124216`;
all six captured case inputs and seeded priors are identical. This is a separate
in-process diagnostic, not an enabled production implementation of the tool arm.
The report records the effective flags and temporary loader source hash separately
from production source manifests.

The tool arm executes the registered `fetch_student_data` through public
`ToolRuntime`/`BaseTool.ainvoke`, then appends an application-authored assistant
tool request and its actual `ToolMessage` result after the unchanged history and
internal task. It retains the canonical UCA instructions and lookup descriptor.
`runs[2]` and `runs[3].application_lookups` record the application origin, actual
result, and `model_generation: false`; the inserted messages have no invented
model-response metadata or token usage. Parent locking, stale-prior validation,
and deterministic single-write persistence remain active.

Independent comparison of `runs[2/3].http_attempts[0].payload` with both live
OFF post-fetch payloads (`runs[0/5].http_attempts[1].payload`) found exact equality
after normalizing **only the fetch tool-call IDs**. System text, roles, content,
argument formatting, tool descriptors, and sampling options match. The actual
prior result also matches the OFF lookup result. Thus this arm skips the lookup
request generation without introducing the Human arm's changed prior position,
prompt wording, or tool set. Every model generation corresponds to one recorded
HTTP request; no retry or uncounted model lookup occurred.

| Two copied-answer assessments per condition | OFF | Human prior | Tool-result prior |
| --- | ---: | ---: | ---: |
| Summed component `total_s` | 25.869 s | 25.441 s | 21.653 s |
| Model generations | 6 | 4 | 4 |
| Input tokens | 35,400 | 24,111 | 24,632 |
| Output tokens | 670 | 633 | 632 |
| Exactly one consistent student-model write | 2/2 | 2/2 | 2/2 |

All six outputs grade the answer `correct`, retain `Understand`, and return
`low` confidence. Each saved concept, tier, confidence, and rationale matches
the typed output exactly, with one write and the correct assessment count.
The tool arm makes one application lookup and two model calls per observation;
OFF makes three model calls, including the lookup request.

**The tool arm passed this narrow copied-answer check, which justified the
cold-start and changed-item controls below; it did not approve production
adoption.** Assessments
are at `runs[i].profile.cases[0].observations[0].uca_output`. Tool run 2 says the
copy “evidences no independently attributable reasoning beyond the prior
Understand seed” and sets low confidence because the only new signal is copied.
Tool run 3 says it “cannot establish independent Apply-level attainment” and
explicitly disclaims attribution. Its phrase “consistent with the prior
Understand seed” denotes compatibility in that context, not fresh confirmation
of attainment. Neither tool output promotes the learner or claims no learning
occurred.

Run 2's prospective phrase “a genuinely independent attempt at this Apply-level
transfer would justify promotion” needs a qualification if used beyond this
assessment: attributable **correct reasoning**, not merely making an attempt,
would be evidence for an update. No such update occurs in this record. The
current copied-answer decision is sound, but the wording does not establish a
general promotion policy.

The Human arm's confidence difference from the earlier comparison did not repeat:
both new Human outputs use low confidence. Nevertheless, Human run 1 still says
the copy “confirms but does not raise the prior Understand estimate”, an
unsupported corroboration despite its explicit acknowledgment of copied text.
Human run 4 avoids that mistake. These variations preclude treating the prior
encoding as a proven sole cause of calibration behavior.

The lower tool-arm elapsed total is descriptive. Cache occupancy was uncontrolled;
the first OFF observation has missing cached-token usage, while the last OFF
observation reports a warm cache. Generated text and retrieval results also
vary. Verified removal of one model call does not causally explain every timing
difference or establish a whole-tutor speedup. Before any adoption, the tool path
must also preserve honest unassessed cold-start behavior and credit new reasoning
on the changed item without carrying forward the old copy label. Neither this
single-case comparison nor its exact persistence certifies the complete UCA or
the tutor's pedagogical quality. `PREFETCH_ASSESSMENT_PRIOR` remains disabled.

#### Tool-prior coverage: changed-item attribution fails

**Do not adopt the tool-prior optimization.** The subsequent
bounded coverage report (local capture `output/profiling/assessment-tool-prior-coverage-v1.json`)
(SHA-256 `1e3851f291fd651b87dc343bf4d152c16ed8e09cb67d601f6be7b655f61f43d0`)
contains eight assessments: cold-start and changed-item cases in each of four
OFF/tool/tool/OFF runs, two observations per case and condition. It uses the same
fixture hash and frozen temporary loader as the copied-answer diagnostic. The
loader source hash is
`7019cc69b6a059be18ed9fc78b34d168cb8f049e40fb9cd30463d1737d2852b0`.
No prompt, schema, routing policy, or production runtime source changed.

All eight observations complete with one consistent student-model write. The
saved concept, tier, confidence, and rationale match the returned typed output;
counts and target-student isolation checks pass. Independent comparison again
finds both tool-arm first requests equal to both OFF post-fetch requests for
each case after normalizing only fetch tool-call IDs. The captured public
history is complete and unchanged. These are mechanical guarantees, not proof
that later generated assessments will interpret that history correctly.

| Four assessments per condition | OFF | Tool-result prior |
| --- | ---: | ---: |
| Summed component `total_s` | 46.900 s | 39.372 s |
| Model generations | 13 | 9 |
| Input tokens | 78,330 | 56,255 |
| Output tokens | 1,270 | 1,081 |
| Exactly one consistent student-model write | 4/4 | 4/4 |

For cold start (`profile.cases[0]` in each run), all four outputs have null prior,
low confidence, no answer judgment, and next probe `Apply`. Their rationales
explicitly state that the practice request supplies no attainment evidence and
that the tier is provisional. The emitted `Remember`/`Apply` differences are not
failures against this fixture: it supplies no unique initial provisional tier.
The schema's inability to express an unassessed tier remains a separate limit.

The changed-item history (`profile.cases[1].case.conversation`) first contains
a `find_by_email` question, a copy declaration, the tutor's supplied answer, and
the student's identical repetition at indices 0–3. Index 4 then explicitly
introduces a different `StockDirectory` question. The new answer at index 5
selects a detached ID-to-quantity snapshot over a SQL cursor and explains why
the numeric quantity belongs in the public contract. That answer is **not**
identical to the earlier tutor solution, and the tutor never supplies it in
this record. Prior support remains relevant, but the earlier copy declaration
does not establish that this new response was copied.

Both tool-arm changed-item assessments fail that distinction. Exact locators
are `runs[i].profile.cases[1].observations[0].uca_output`:

- **Run 1, `Understand`/low:** claims “the pasted text is verbatim identical to
  the earlier supplied solution” and calls the current answer “copied/supplied
  content, not attributable independent reasoning”. This is a false claim about
  the recorded texts. It then says the answer “confirms coherent Understand-level
  paraphrase”, mischaracterizing the new scenario-specific reasoning. Correct
  content grading does not repair that attribution error.
- **Run 2, `Apply`/medium:** correctly identifies both rubric criteria, but then
  says “the student stated they pasted the answer unchanged rather than working
  it out, so attribution of this reasoning to the student is uncertain”. The
  quoted declaration belongs to the earlier question. General caution about a
  single supported response is reasonable; citing that old declaration as
  evidence about this target response is not.

The unchanged request instructions already say, “Do not carry an earlier
copied-answer declaration onto fresh reasoning about a changed item.” These
failures therefore occur despite the explicit rule and available history;
neither is a missing-instruction or persistence defect. They also show why
conservative-looking low confidence cannot substitute for accurate evidence
attribution.

Both OFF changed-item outputs credit the new dependency reasoning and intentional
public data while bounding the evidence to one scaffolded vignette. Run 0 uses
`Evaluate`/medium and run 3 `Apply`/medium. No exact Bloom label or automatic
confidence increase is prescribed by the fixture, so that difference alone is
not counted as a failure. The decisive contrast is their correct attribution
of the new answer, not agreement with a preferred tier.

Initial wire equivalence does not explain the later divergence: searches and
generated text vary, including an extra search in one changed-item observation
per condition, and cache state is uncontrolled. The lower elapsed total and four
fewer model calls are descriptive component observations, not proof that skipping
the lookup caused either the time difference or the semantic error. Two samples
per case/condition do not establish a general failure rate or whole-tutor effect.
Nevertheless, these confirmed task-attribution failures prevent acceptance of
the tested tool path. The Human prefetch flag remains disabled, the temporary
tool loader is not adopted, and no further prompt tuning follows from this
diagnostic. The earlier copied-answer pass remains a narrow finding, not a
system-quality certification.

### Preserve the content role after assessment

The v2 Socratic-pressure failure came from the parent answering after UCA without
calling CGA. A child-only prompt repair cannot cover that path. The narrow
[routing guard](../src/edbot/middleware/content_after_assessment.py) matches actual
current-turn task calls and successful typed results. After an assessment, it
restricts the next model request to the existing CGA task for that concept. A
parallel sibling or a previous turn's CGA does not count as content produced
after the assessment. The executable task and existing input validation stay
unchanged; two malformed/failed content attempts end the turn with an error.

If the model ignores the restriction, the wrapper rejects its response before
returning it to the graph. There is no hidden retry that could flush a rejected
answer to the student when a later model message arrives. Tests exercise both
buffered and streamed transport, public history, causal ordering and retry bounds.
The ordinary stop path and CGA-only shortcut keep their existing call counts.
The component UCA evaluator explicitly disables this parent-routing requirement
because its deterministic parent emits no student reply; full tutoring profiles
record and exercise the configured flag.

This enforces an existing division of responsibilities, not study assignment or
semantic quality. A mistakenly assessed stop still reaches CGA, whose contract
requires a brief closure. Post-CGA parent synthesis remains, so the guard alone
cannot establish Socratic compliance. Correct existing UCA→CGA paths gain no
generations; a formerly skipped CGA path now incurs the necessary content work.
Full conversation timing and content review must account for that cost.

### Prevent duplicate structured child outputs

`SERIAL_CHILD_TOOL_CALLS=True` sets `parallel_tool_calls=False` through the public
`ModelRequest.override(model_settings=...)` API in `CompleteContentMiddleware`:
it applies to CGA and, when deterministic assessment saving is enabled, UCA.
The parent routing policy remains independent. This also serializes legitimate
multiple child searches, potentially adding generations. The v4 pressure case
spent 18.651 seconds correcting duplicate CGA outputs; preventing that failure
is a candidate improvement, not a measured net speedup. Existing rejection and
correction of duplicate or premature mixed-tool output remains active if a
server ignores the setting; the code never silently selects one duplicate.

The CPU grammar proof (local capture `output/profiling/serial-child-grammar-proof-v1.json`)
records exact inputs, settings, versions, source pointers and SHA-256 hashes.
With XGrammar 0.2.7 and the pinned SGLang 0.5.21 parser contract, the required
Qwen tool grammar accepted one output and rejected two when parallel calls
were disabled. CUDA was not initialized; a synthetic byte vocabulary means
this is grammar compatibility evidence, not production-tokenizer or inference
validation. The local 149-test suite passed, including actual HTTP serialization
of the setting, flag rollback, duplicate-output correction and mixed-tool
deferral. No dependency upgrade was needed.

For SGLang, the reduced tutor harness now advertises a typed model-facing `task` schema.
Reference-free outer `anyOf` branches pair each literal specialist name with its
existing input model; an independent union for `description` would not enforce
that pairing. This addresses observed CGA-shaped inputs sent to UCA, which caused
an avoidable rejection and correction generation. It does not decide which
specialist should handle a student's request.

Only the model-facing descriptor changes. DeepAgents' executable string-valued
task API remains intact: the existing validator normalizes typed objects and
legacy JSON strings before dispatch. The post-assessment guard selects the
complete CGA branch. Nine focused tests cover actual HTTP serialization,
sync/async dispatch, crossed inputs, legacy strings, defaults, call identities,
and assessment receipt replay across both representations. The complete local
suite passes 164 tests; no dependency upgrade was needed.

The parameter schema exactly matches the CPU-compiled proof (canonical SHA-256
`b29bb379f8e8a033f9ea2dae1ac21c73831a7097f378167fb9321a0153a155fa`).
Its compact UTF-8 JSON grows from 422 to 2,735 bytes. Grammar compatibility and
client tests do not establish a net latency improvement or compatibility with
every OpenAI-compatible provider; the larger schema and changed routing still
require live evaluation.

The first typed-dispatch live run (local capture `output/profiling/tutoring-candidate-v6-typed.json`)
on 2026-10-18 exposed a separate concurrency defect. All three initial turns
produced valid UCA and CGA task objects in the same parent generation. Both
children completed, but DeepAgents returned the inherited `conversation` field
in both task updates; LangGraph rejected the simultaneous writes to that
single-value channel. The exact
trace (local capture `output/profiling/tutoring-candidate-v6-typed.log`) records
`InvalidUpdateError: At key 'conversation': Can receive only one value per step`.
The dependent pressure, still-stuck and stop turns were not attempted. These
three failed replies are not a latency improvement or a quality pass.

Report SHA-256:
`bd1f4bde5224f4688dfb014e2303b739924f597dcf4570c6ad9f8c1ffe05a0ff`;
trace SHA-256:
`6c3cf05680785407699857c7e776b223001c4736a96e0eb82a665770fcab3d3a`.
This interaction was not exercised by the preceding sequential HTTP tests.
Parent-owned read-only context must reach each child without being written back
by every child. Separately, a CGA launched alongside UCA cannot observe that
assessment and must not satisfy the existing post-assessment content requirement.

### Keep inherited context read-only on child return

The [parent conversation middleware](../src/edbot/middleware/conversation_history.py)
now removes only `conversation` and `course_evidence` from a returned `task`
`Command` with a dictionary update. It copies the command and update dictionary,
preserving messages, tool-call identities, files, routing and resume fields.
Other tools and result forms retain their existing behavior. Parent-to-child
propagation is unchanged: every specialist still receives the public history
and captured course passages. The parent remains responsible for refreshing
these fields, so parallel children cannot submit duplicate writes to them.
This uses no state-merging reducer and leaves parent parallelism available.

Deterministic assessment saving still validates and saves the exact UCA result
before this return filter runs. All task result messages reach the parent, so
the causal guard still requires a fresh matching CGA after UCA; a parallel
sibling does not satisfy that requirement. The
[focused regression](../tests/test_parallel_child_context.py) reproduces the
original collision with typed and legacy string inputs, then checks genuinely
overlapping UCA/CGA requests through the production graph using local HTTP
mocks. It verifies unchanged child context and public history, independent
parallel searches, one saved assessment, the later CGA, and sync/async command
preservation. These local checks do not establish live latency or teaching
quality after the fix.

The Ollama comparison client needs the legacy task descriptor. In the installed
`ollama` 0.6.2 serializer, `Tool.Function.Parameters` discards a root `anyOf`:
an actual mock-transport request retained only `{"type":"object"}` and lost the
task's parameter definitions. Adding an explicit root object type does not
preserve the branches. The installed OpenAI client retains the correlated
schema for SGLang; that does not certify acceptance by every hosted provider.
The ChatOllama path therefore retains the original string parameters. It also
omits the added `parallel_tool_calls` option, which the installed Ollama client
rejects as an unknown argument. Actual sync/async mock-transport tests cover
both behaviors. Ollama ignores `tool_choice`; the runtime post-assessment guard
still rejects an answer that skips the required content specialist. These
compatibility changes do not require a LangChain upgrade.

## Select only the assigned content instructions

The reduced harness now gives CGA only the mode and tier instructions selected
by its existing validated internal task. The shared teaching contract, source
rules and output constraints remain unchanged. An explanation task retains its
Socratic probe branch; a question or probe omits unrelated explanation styles.
This neither selects a study condition nor changes the supplied tier, and it
adds no model generation.

Selection happens before public history is injected. It is private to that child
invocation and cannot propagate to the parent or another specialist. The model
wrapper replaces only the exact known CGA prompt span and preserves surrounding
system content and metadata. Malformed tasks, re-entry without a fresh internal
task, unfamiliar prompt structure, or a missing/ambiguous span keep the complete
original prompt. Parent and UCA instructions are unaffected.

For the exact captured v5 pressure request, the system text shrinks from 16,906
to 12,102 characters (28.42%), or 2,638 to 1,896 whitespace-delimited words.
The focused text SHA-256 is
`b393f8f1d7f0ccd2281adc008519c417923c37d3e9f9f99292ce17b52fad6054`.
This offline size comparison is not a tokenizer, latency, cache-reuse or quality
measurement. Ten focused tests cover all eighteen mode/tier variants, rich
system messages, fallback/reset behavior, tool continuation, and real graph
dispatch with no private-selector propagation. The combined local candidate
suite passes 180 tests, including typed dispatch, Ollama wire compatibility, and
parallel context ownership. Live semantic evaluation remains required; fewer
instructions do not guarantee faithful tutoring.

## V7 nine-turn application measurement

The complete v7 report (local capture `output/profiling/tutoring-candidate-v7.json`), SHA-256
`0fc763d19028500f784b49b57c311c50f1832d19851a76fb52d59290dd7b2f0e`,
records six synthetic cases and nine turns on 2026-10-18. All nine execute
successfully. This is a mechanical result, not acceptance of the generated
teaching. The first four cases are parsed-equal to the earlier partial report;
the totals below include the four later turns as well.

All six case profiles report the same SGLang 0.5.21 configuration: pinned
Flash-Next NVFP4, 32,768 context, 131,072 KV-token cap, two running requests,
2,048-token prefill chunks, native MTP with three steps/top-k one/four draft
tokens, and twenty persistent Mamba states. All 56 captured model requests use
buffered transport, temperature zero, thinking disabled, and a 4,096-token
output cap. All child requests retain required tool calling and
`parallel_tool_calls=false`.

The v5 report (local capture `output/profiling/tutoring-candidate-v5.json`), SHA-256
`fd8364af4bb69e53cd748bb22921213c33676086f38af5c9629f8d3a400158da`,
contains identical case definitions and learner-input hashes. It is a descriptive
comparison: task schemas, prompt selection, and resulting routes differ; cache
occupancy and generated content are uncontrolled. These are one observation per
turn, not a controlled estimate of the focused prompt's latency effect.

| Turn | V5 seconds / calls | V7 seconds / calls |
| --- | ---: | ---: |
| Concise explanation | 42.236 / 5 | 35.338 / 5 |
| Practice question | 32.302 / 3 | 39.843 / 5 |
| Map contract review | 56.187 / 7 | 82.849 / 9 |
| Socratic selection | 47.418 / 10 | 36.096 / 7 |
| Answer pressure | 32.461 / 4 | 34.286 / 5 |
| Missing prerequisite | 51.524 / 11 | 58.655 / 12 |
| Still stuck | 38.409 / 9 | 41.937 / 8 |
| Spanish one-question help | 47.973 / 9 | 24.653 / 4 |
| Stop | 2.276 / 1 | 1.877 / 1 |
| **Sum** | **350.785 / 59** | **355.534 / 56** |

V7 records **391,130 input tokens and 9,113 output tokens**, versus v5's 427,218
and 8,731. V7's median turn is 36.096 seconds, versus 42.236; the summed time is
nevertheless 4.749 seconds higher. Startup is outside these turn totals. Model
intervals account for 348.987 seconds: parent 108.490 seconds/27 generations,
CGA 186.381/18, and UCA 54.116/11. There are eighteen course searches, nine
student lookups, and thirteen task executions. Nested task durations include
child generations and must not be added to model time. Text becomes visible
near completion because complete parent messages are buffered.

The Map regression is sequential, with **no UCA/CGA sibling batch**. V5 sends
the content task directly. V7 first generates a lengthy assessment task with
an `answer_submission` and rubric (17.570 seconds/449 output tokens), runs UCA,
then requests the required fresh CGA and synthesizes the parent reply. Parent
model time rises from 17.376 to 35.760 seconds; UCA adds 16.586 seconds; CGA time
falls from 37.459 to 29.330 seconds. This accounts for the observed 26.662-second
turn increase without attributing it to a slower kernel or duplicate sibling.
It does not validate the parent-authored rubric or assessment judgment.

The mechanical audit finds:

- All thirteen model-facing task descriptions are objects valid for their
  selected UCA/CGA input schema. All 56 generations have valid completion
  metadata and no invalid tool calls, output truncation, or model error. No tool,
  capture, or framework exception is recorded.
- Four UCA outputs match the resulting stored concept, tier, confidence, and
  rationale exactly. Map and Socratic selection each record count one/turn one;
  the prerequisite case advances from count one/turn one to count two/turn two.
  The pressure follow-up leaves its assessment unchanged. These are resulting
  state observations; this harness does not capture an independent write-event
  or receipt log.
- Each of the four post-UCA parent requests is narrowed to the named CGA task
  with serial calls, and each receives a later matching CGA result. No
  UCA/CGA sibling batch appears anywhere in these nine turns.
- All eighteen CGA requests contain the exact selected mode/tier variant,
  including tool continuations. System lengths are 12,102/12,120/12,160
  characters for explanation at Apply/Evaluate/Understand, 12,945 for an Apply
  question, and 10,434/10,443 for Apply/Understand probes. Every explanation
  variant retains its Socratic probe dependency. The canonical prompt hash
  matches the recorded manifest.
- Direct delivery supplies the concise and accessibility replies exactly from
  CGA content. Six other content turns use a final parent generation, totaling
  33.860 seconds/1,239 output tokens; four reproduce CGA content exactly. Schema
  and delivery checks do not establish content accuracy or answer privacy.

Two generation reductions have concrete trace support. The first is now a
disabled implementation candidate; neither has accepted measured savings:

1. **Supply a fresh student lookup to UCA before generation.** Map, Socratic
   selection, and the first prerequisite turn already fetched the same
   student's same concept in the parent, then UCA used another generation only
   to request the same empty-state result. Those three child generations total
   11.891 seconds (3.989/3.958/3.944); local lookup execution itself is only
   milliseconds. Prefer a fresh deterministic child read under the existing
   assessment lock over caching a parent snapshot. The read must retain the
   correct student, canonical concept, turn and current-entry version, represent
   absence explicitly, and invalidate after an assessment write. Never reuse
   another learner's result or a stale prior-turn snapshot. The still-stuck
   child's lookup has no parent duplicate and needs a fresh read; its lookup-only
   model generation takes another 3.339 seconds. Those four observed generation
   durations are not a counterfactual latency saving. The bounded implementation
   and its default-off flag are described in
   [Fresh assessment prior before generation](#fresh-assessment-prior-before-generation).
2. **Permit direct delivery after a successful read-only sibling lookup.** The
   practice turn batches `fetch_student_data` with its sole CGA task. The
   existing single-call gate therefore declines direct delivery, and a
   5.260-second/195-token parent generation adds only “Here's your question:”
   before the unchanged content. Any extension should require exactly one CGA
   in the turn, a specifically allowed successful lookup, no UCA or other
   outstanding work, and all existing completeness, source, privacy and format
   checks. This case supports testing that narrower gate, not removing parent
   synthesis from all turns.

   **Review clarification: do not adopt this shortcut yet.** Read-only does not
   mean irrelevant to routing. This lookup returns no prior assessment, while
   its sibling CGA has already selected `generate_question` at `Apply`. The
   prompt uses that lookup for cold start, tier and reassessment cadence;
   `EdbotContext` supplies only `student_id`, not an authoritative condition or
   resolved routing decision. No observed UCA call does not prove none was
   required. Matching the returned tier alone cannot settle these obligations.
   A safe extension needs trusted routing authorization tied to the current
   learner, concept, turn and prior version before dispatch. The cosmetic
   rewrite therefore demonstrates overhead, not permission to bypass routing.

The first prerequisite turn also invokes the same valid CGA task twice
sequentially. Its first result is complete with no coverage gap; the parent
voluntarily requests another version, which searches again and changes the
support wording. No validation error or post-UCA guard forces that repetition.
The second dispatch and child span take 15.934 seconds, but removing them could
remove a useful revision; semantic review must precede such a policy change.
Similarly, sibling-CGA deferral would have saved no generation in this v7 trace.

## Parent/child prefix-cache experiment

The simple one-child probe (local capture `output/profiling/cache-mtp-10-states.json`)
preserved 8,064 cached parent tokens in all three paired comparisons. Switching
roles alone therefore did not unconditionally discard the parent's prefix on the
running ten-state MTP configuration.

The extended probe follows the pattern seen in full tutor traces: three parent
requests, four growing child requests, then the identical final parent request.
The parent-only control omits the child requests. Run it against the currently
configured server with:

```sh
python3 scripts/profile_cache.py --parent-rounds 3 --child-rounds 4 \
  --output output/profiling/cache-extended.json
```

The ten-state run (local capture `output/profiling/cache-mtp-10-states-extended.json`) and
twenty-state run (local capture `output/profiling/cache-mtp-20-states-extended.json`) on
2026-10-18 each completed all 36 requests without errors or truncation. Every
request returned `ACK`, two completion tokens, and `finish_reason="stop"` under
the same 16-token output cap. All 36 corresponding unsalted payload hashes were
independently recomputed and matched across runs; their API-reported prompt
counts also matched. Parent prompts contained 8,126 → 8,861 → 8,990 → 9,528
tokens; the child branch contained 5,704 → 7,753 → 9,802 → 11,851 tokens.

| Mamba states | Final parent condition, three repetitions | Cached tokens in every final request | Median first-text latency | Median request elapsed |
| ---: | --- | ---: | ---: | ---: |
| 10 | Parent only | 8,960 | 0.514 s | 0.607 s |
| 10 | After four child calls | Omitted by API | 4.449 s | 4.539 s |
| 20 | Parent only | 8,960 | 0.527 s | 0.610 s |
| 20 | After four child calls | 8,960 | 0.512 s | 0.603 s |

An omitted cache count is unknown, not a measured zero. With ten states, the
paired interleaving penalties were 3.922–3.943 seconds; with twenty they were
−0.015 to −0.009 seconds. The 3.937-second reduction in interleaved median
first-text latency supports retaining twenty states for this branch pattern.
It does not show a model reload or establish the exact eviction path internally.

Both reports verified all allowlisted server settings with no missing fields or
mismatches. The only observed setting difference was `max_mamba_cache_size`
10 → 20; the only requested serving-configuration difference was
`MAMBA_CACHE_SLOTS_PER_REQUEST` 5 → 10. Concurrency remained two, total KV capacity
131,072, prefill chunk 2,048, FP32 recurrent state, and the same model revision,
SGLang 0.5.21, and MTP settings. These reports contain no memory measurements;
additional state-pool memory estimates must not be read as measured host usage.

A separate memory observation (local capture `output/profiling/cache-20-state-memory-observation.json`)
records 19.1 GiB available host memory and 4.94 GiB swap used while the subsequent
full tutoring evaluation was running. This is one observation, not peak memory or
a controlled host-memory delta. Exact startup log excerpts show the persistent
convolution/SSM pools increasing from `0.02GB + 1.16GB` to `0.04GB + 2.21GB`, as
the logger labels them; intermediate pools remain `1.27GB + 0.01GB`. The snapshot
preserves separate observation times for memory and allocation-log extraction.

The script uses predetermined transcripts, identical parent payloads across each
pair apart from their cache salts, alternating pair order, and no shared-cache
flush. It records request hashes and actual server settings. Capacity settings
were tested in separate runs, not randomized across restarts; three short-output
pairs do not characterize concurrent traffic or every cache pressure pattern.
This result is separate from complete tutoring latency and teaching quality.

Report SHA-256 values:

- Ten states: `5b4146a81cff26dc29de719af728913c60abf0c3674bc5819afc37726a1ab753`.
- Twenty states: `fe9e832da19d9487f90afb00594bc98fe4e3f74bae35b88f6c8f4aa92c4dd1d6`.

The final parent's unsalted payload SHA-256 is identical in all twelve final
requests: `0cb063b23b9b727fca91f3e728ce2ddf10386bd885f321434b010f7e3a2c7f3f`.

## Prefill chunk-size experiment

**The timing screen passes; 4,096-token chunks remain an unadopted performance
candidate because tutoring-quality preservation is unestablished.** The
predeclared comparison (local capture `output/profiling/prefill-chunk-comparison.json`)
completed A1:2048 → B:4096 → A2:2048. The source setting and healthy server are
restored to 2,048. These are buffered one-token diagnostics,
not pure prefill measurements, visible TTFT, complete tutoring turns, or quality
acceptance. The frozen helper SHA-256 is
`8356efa6d733587681eda0464c52749c290353d6e391b232bf2c00563f011a73`.

A1 (local capture `output/profiling/prefill-chunk-a1-2048.json`) and
clean B (local capture `output/profiling/prefill-chunk-b-clean-4096.json`), and
A2 (local capture `output/profiling/prefill-chunk-a2-2048.json`) each completed
22 requests: two warmup prefix/target pairs and three repetitions of each
family/condition. Every request generated exactly one token with the expected
length finish. Corresponding unsalted HTTP payloads, prompt counts, cache counts,
client versions, and tool bindings match. Fourteen unique salts per block isolate
reuse; each partial prefix/target pair shares one salt. The only observed serving
change is chunk size; the configuration-file hash difference also matches exactly
that edit. Salts do not reset global cache occupancy.

| Target condition | Prompt / cached tokens | A1 median (s) | Clean B median (s) | A2 median (s) |
| --- | ---: | ---: | ---: | ---: |
| Parent, fresh | 9,668 / 0 | 4.641 | 4.192 | 4.649 |
| Parent, partial | 9,668 / 6,592 | 1.617 | 1.381 | 1.644 |
| CGA, fresh | 7,311 / 0 | 3.567 | 3.102 | 3.572 |
| CGA, partial | 7,311 / 4,992 | 1.334 | 1.127 | 1.345 |

The sum of cell medians decreases from A1's 11.1598 to B's 9.8018 seconds
(12.17%), and is 12.56% lower than A2. Control-cell differences are 0.13–1.68%.
Predeclared gates require at least 10% reduction against **each** control,
no cell more than 5% slower than either control, control-cell differences within
5%, all 22 probes valid, matching inputs/cache counts, and original-budget
compatibility. The numeric gates pass against both controls. These are practical
decision thresholds, not statistical confidence estimates or evidence of the
same percentage improvement in complete replies.

The first B block (local capture `output/profiling/prefill-chunk-b-4096.json`) is explicitly
excluded: it ran 14:01:03–14:02:09 UTC while the
startup observer (local capture `output/profiling/prefill-chunk-b-startup.json`) continued
health polling through 14:01:58. Clean B began at 14:02:51. Its sampled minimum
available host memory was 19.28 GiB, with zero OOM, swap-out, or memory-pressure
counter increments; 442 global swap-in pages and 279 major faults remain recorded.
Startup pressure is separately retained and must not be described as absent.
The A2 startup observer (local capture `output/profiling/prefill-chunk-a2-startup.json`)
finished before its benchmark began. A2's resident trace records 18.91 GiB minimum
available memory, zero OOMs, 134 global swap-out pages and about 0.116 seconds of
memory-pressure counter increase; it is not a zero-paging measurement. Sampling
does not establish exact peaks or attribute global counters to one process.

The original-budget check (local capture `output/profiling/original-budget-compatibility-B4096.json`)
returned three schema-valid outputs at the original 4,096-token completion cap,
one each for parent, CGA, and UCA, without retries or truncation. It executed no
tools or full agent graph. The parent requests relevant retrieval; UCA correctly
accepts the bounded primitive-valued Map copy. **Overall quality is not accepted:**
`runs[1].validation.parsed` has a critical CGA grading contradiction. The public
question promises “the live internal list,” but the private rubric calls a copy
or iterator promise-preserving while disallowing reliance on a live view. Such a
redesign requires an acknowledged contract migration. This resembles earlier
quality failures and does not establish that chunk size caused the defect.

The original-budget 2,048 control (local capture `output/profiling/original-budget-compatibility-A2048.json`)
completed the parent search, then emitted a valid additional course search from
CGA instead of immediate `CGAOutput`. Both requests returned HTTP 200 and valid
tool arguments. The diagnostic stopped on that narrower terminal-output
expectation, executed no search, and never attempted its UCA request. Its
`execution: failed` is therefore not an API/parser failure. It provides no paired
final rubric and cannot establish semantic equivalence. No forced-output retry
was used to manufacture one. The measured backend candidate remains available
through the central code setting; it is not promoted as a quality-preserving
optimization or an accepted tutoring release.

Report SHA-256 values:

- A1: `2dcf2dbef6a36dc1f2c210eda9994ba1116f33a9dd0669e837add405949bc9cb`.
- Clean B: `4f93bd626094795f757772e6d311b3eaa5bdd3237c13803d2d40a88f33979d2f`.
- A2: `8145f2ba11135a990b576e71793af6fa2ab05b5400b9962da2a8015883378f05`.
- Excluded B: `c38af19cbb7eb0db536bcddee8a40549d429fccd9664d3167fb7b48e2b04106c`.
- Original-budget check: `d7e88e38fcb7d2295e3e01f8580b9c8eaf3c6d97cfb3706d0e5e8da76365f31f`.
- Original-budget control: `4ed633858b857175eb01f7324775c03c1d7ed821c6098e66064502253ff1f4a0`.

## Buffered tool responses and parser reliability

The shared client sets the public LangChain option
`disable_streaming="tool_calling"` when `BUFFER_TOOL_RESPONSES` is enabled.
Requests containing tool schemas use `stream: false` and SGLang's complete-response
parser. Calls without tools retain SSE. This applies even when a tool-enabled
parent ultimately returns ordinary text. The service already holds each whole
parent message until it can exclude private tool preambles and truncation;
tool status events now also wait for the completed model response.

The reason is a reproduced transport failure, separate from teaching quality.
The v2 tutoring report (local capture `output/profiling/tutoring-candidate-v2.json`) had two
failed child outputs with invalid tool arguments. A later conversation rerun
changed agent routes and passed, so the exact original failed CGA requests were
replayed without executing their returned tools. Each report contains the
serialized inputs, bound schemas, sampling options, actual HTTP payloads and
hashes, server metadata, chunks, and final parsed messages:

| Exact request replay, three repetitions each | Streaming median | Buffered median | Invalid streaming / buffered |
| --- | ---: | ---: | ---: |
| `missing-prerequisite/still-stuck` | 24.745 s | 22.369 s | 1 / 0 |
| `accessibility-stop/accessible` | 15.270 s | 15.552 s | 0 / 0 |

The streaming replay (local capture `output/profiling/tool-call-replay-v2.json`) produced one
invalid result in six calls; the
buffered replay (local capture `output/profiling/tool-call-replay-v2-buffered.json`) produced
six valid results with no errors or truncation. Each pair had identical input
hashes and actual HTTP payloads except `stream` and `stream_options`, one HTTP
attempt, and the same observed server settings. Output lengths varied, so these
small samples support selecting the parser path, not a speedup or a general
failure-rate estimate. Report SHA-256 values are
`b3a257bb5cf26165bc43a3d816ed454152d6dfd6c57639b8870848c63f5dc7ef`
and `77b383db7a2432ca46eed62c81c8089e4672a31b0c876c500104381f1059c6d1`,
respectively.

In the failing streaming replay, tool index 0 received a closing `}` twice,
separated by ordinary content `\n</parameter>\n\n`; its arguments ended in
`"coverage_gap": null}}`. LangChain correctly concatenated the deltas and
rejected the resulting JSON. The
[pinned SGLang parser](https://github.com/sgl-project/sglang/blob/v0.5.21/python/sglang/srt/function_call/qwen3_coder_detector.py)
handles `</function>` without checking whether it is still inside a tool-call
block. A stray closing tag can therefore append another brace to the last tool.
The raw pre-parser model text was not captured, so that precise tag sequence in
the live generation remains an inference. The offline reproduction below confirms
the mechanism. [Upstream PR 43587](https://github.com/sgl-project/sglang/pull/43587)
guards tags outside active blocks; it was open on 2026-10-18. No upstream patch,
dependency upgrade, model setting, or server setting is needed for this workaround.

This minimal parser-only recipe runs in the pinned SGLang environment without
loading a model or sending inference requests. For chunk sizes 1, 2, 7, 64 and
the whole input, the unchanged 0.5.21 detector emits the extra closing brace while
its complete-response parser returns the intended object:

```python
import json
from types import SimpleNamespace
from sglang.srt.function_call.qwen3_coder_detector import Qwen3CoderDetector

tools = [SimpleNamespace(type="function", function=SimpleNamespace(
    name="probe", parameters={"properties": {"coverage_gap": {"type": "null"}}}))]
wire = ("<tool_call><function=probe><parameter=coverage_gap>null</parameter>"
        "</function></tool_call>\n</parameter>\n\n</function></tool_call>")
for size in (1, 2, 7, 64, len(wire)):
    parser = Qwen3CoderDetector()
    arguments = "".join(
        call.parameters
        for start in range(0, len(wire), size)
        for call in parser.parse_streaming_increment(wire[start:start + size], tools).calls
    )
    complete = Qwen3CoderDetector().detect_and_parse(wire, tools).calls[0].parameters
    assert arguments == '{"coverage_gap": null}}'
    assert json.loads(complete) == {"coverage_gap": None}
    print(size, arguments, complete)
```

Buffered generation has no response body until completion. The client therefore
uses a 300-second read timeout, preserving 120-second connect/write/pool limits
and the service's 600-second total turn deadline. Disabling the flag restores
streaming and the 120-second read timeout. Profilers record the flag and accept
missing or null usage as unknown; missing usage must not discard finish reasons
or make a truncated call appear successful. Set `model.stream_usage = True` for
profiling; do not pass `stream_usage=True` as an invocation keyword, which would
reach the nonstreaming API as an unsupported field.

Local HTTP and real graph regressions cover both transport settings, preserved
tool arguments/usage/finish metadata, private rubric handling, late parent tools,
parallel evidence tools before final content, malformed child calls, truncation,
and retry/history behavior. These boundary checks do not establish semantic
teaching quality; the live tutoring review remains a separate acceptance gate.

## Host observations and troubleshooting

During the initial 27B setup on the lab Spark, native PyTorch identified NVIDIA
GB10, capability 12.1, and executed a CUDA matrix multiplication with the CUDA
13.0 environment.
This confirms basic GPU access, not a speedup. The first full server launch
exposed missing `Python.h` in the system Python installation: matrix multiplication
alone passed but Triton kernel compilation failed. The installer therefore uses
managed Python with headers and tests Triton initialization as well as PyTorch.
A fresh PyPI dependency installation and a repeat installer run both passed these
checks. Ollama also returned a 4,096-dimensional retrieval embedding.

Reducing the embedding context from 40,960 to 8,192 lowered Ollama's reported
allocation from 12,154,474,331 to 7,188,418,395 bytes, saving **4.625 GiB** on the lab
Spark. The [strict embedding adapter](../src/edbot/embedding_model.py) retains the
same 8B model and corpus fingerprint and rejects oversized inputs instead of
silently truncating them. Three queries and the largest stored chunk produced
bit-identical vectors; the queries returned the same top four chunks. The current
2,492-chunk index has no chunk larger than 1,307 UTF-8 bytes. These spot checks do
not establish equivalence for every input. See
the comparison report (local capture `output/profiling/embedding-context-comparison.json`).
The embedding checks overlapped Flash-Next weight loading, so their timings are
not a latency comparison. Subsequent Flash-Next reply measurements appear above.

The first Flash-Next launch allocated 795,904 KV tokens (18.22 GiB), although
only two 32K-context requests were allowed. Its scheduler then exited with
SIGKILL during FlashInfer autotuning, and SSH briefly stalled. Available memory
recovered after the process exited. This is consistent with memory pressure,
but the account cannot read kernel logs to confirm an OOM kill. The explicit
131,072-token cap reduced the next launch's KV pool to 3 GiB while retaining
headroom for two active contexts and cached prefixes. Both sides of an MTP
comparison must use the same cap; the failed startup is not a latency baseline.

The capped retry exposed a separate startup problem: more than twenty CUDA
compiler processes ran concurrently, many with 1–3 GiB RSS. Host memory and swap
filled, and `/proc/vmstat`'s cumulative `oom_kill` counter rose from 79 to 97 during
the monitored interval. The launcher was stopped; its workers and private table
were cleaned up, and available memory recovered to roughly 110 GiB. These
resource samples (local capture `output/profiling/flash-next-mtp-off-capped-resources.jsonl`)
confirm OOM activity during the retry, though they do not identify each victim.

The launcher now defaults to `COMPILER_JOBS = 1` via `MAX_JOBS`, while preserving
an explicit environment override. FlashInfer 0.6.18 passes this limit to Ninja,
reducing concurrent compiler memory use without changing inference kernels.
Its `FLASHINFER_NVCC_THREADS` default is already one. Compilation occurs inside
the autotuning phase; the observed concurrent compilers explain the memory spike.
This trades first-build time for lower peak memory; the KV cap does not bound
compiler or temporary kernel allocations. Autotuning remains enabled.
See the [versioned compiler implementation](https://github.com/flashinfer-ai/flashinfer/blob/v0.6.18/flashinfer/jit/cpp_ext.py).

With the official precompiled FlashInfer cache installed and the KV cap retained,
both complete runs kept the chat and embedding models resident without further
OOM activity. The host-wide `oom_kill` counter stayed at 97. Minimum sampled
available memory was 19.26 GiB in the
baseline run (local capture `output/profiling/flash-next-mtp-off-aot-resources.jsonl`) and
17.43 GiB with MTP enabled (local capture `output/profiling/flash-next-mtp-on-strict-resources.jsonl`).
MTP added roughly 0.26 GiB of draft KV storage and 85.65 seconds of draft weight
loading; it does not create a second PLE table. The optimized server took about
12 minutes to become ready, including 570.90 seconds loading target weights.
This is startup cost, excluded from the reply timings above. Keeping the server
resident avoids paying it for each conversation.

For a controlled fallback, SGLang's `--disable-flashinfer-autotune` skips startup
tuning and uses heuristic kernel tactics, which may reduce serving throughput.
Kernel compilation can still be required. This is an upstream server argument,
not an option accepted by the EdBot launcher. Preserve the normal persistent
kernel/tactic caches outside the temporary PLE directory: the default
`SGLANG_FLASHINFER_AUTOTUNE_CACHE=1` reuses successful tuning results, whereas
setting it to zero forces retuning. Leave the optional extended-prefill tuning
pass disabled (`SGLANG_FLASHINFER_AUTOTUNE_EXTEND=0`, the default) while diagnosing
startup. These controls are verified in the
[0.5.21 autotuning code](https://github.com/sgl-project/sglang/blob/v0.5.21/python/sglang/srt/model_executor/runner/flashinfer_autotune.py);
no speedup from them has been measured here.

Keep checkpoint mmap loading enabled. NVIDIA's PLE/MTP sidecar is about 53.7 GB;
`--weight-loader-disable-mmap` reads the entire file into memory before loading
its tensors. If source-page pressure remains high, benchmark the upstream options
`--model-loader-extra-config '{"num_threads":2}'` and
`--weight-loader-drop-cache-after-load` separately. The loader defaults to eight
threads, and the second option advises the OS to reclaim consumed checkpoint
pages; both can affect subsequent load time. More loader workers do not
parallelize the PLE row copies in the model's sequential loading loop. Every boot
rewrites that table, with no supported option to trust an existing initialized
file and skip copying. Retain the launcher's fresh, owned PLE directory and
measure load time and peak memory before changing loader defaults. See the
[loader selection](https://github.com/sgl-project/sglang/blob/v0.5.21/python/sglang/srt/model_loader/loader.py),
[bounded shard iterator](https://github.com/sgl-project/sglang/blob/v0.5.21/python/sglang/srt/model_loader/weight_utils.py),
and [PLE row loading](https://github.com/sgl-project/sglang/blob/v0.5.21/python/sglang/srt/models/qwen4_exp.py).

The **27B preset's** target checkpoint load reported FP8 KV scaling factors
defaulting to 1.0 because no calibrated factors were supplied. This is an additional reason to
validate assessment quality; successful startup alone does not validate the
quantized cache against a higher-precision reference. Flash-Next uses automatic
KV dtype selection instead of inheriting that 27B cache setting. These earlier
installation observations are not Flash-Next performance measurements. The
completed Flash-Next MTP comparison appears above; systematic assessment quality
evaluation remains pending.

Rootless Docker was investigated before selecting the native path. The account
had subordinate UID/GID ranges but lacked the privileged `newuidmap`/`newgidmap`
helpers (`uidmap` was not installed). A direct `unshare -Ur true` probe also failed
with `Operation not permitted`, with AppArmor restricting unprivileged user
namespaces. Downloading Docker into a home directory does not supply those
privileges. Native inference avoids that container prerequisite and requires no
change to the host's security policy.

- Use the server log, `free -h`, `nvidia-smi`, and `ollama ps` during a request.
  GB10 unified memory can appear as `Not Supported` in `nvidia-smi`; also inspect
  host available memory. Avoid keeping a duplicate Ollama chat model resident.
- If startup runs out of memory, reduce `MEM_FRACTION_STATIC` or
  `MAX_RUNNING_REQUESTS` in the shared configuration and restart deliberately.
- If tools arrive as plain text, check `--tool-call-parser qwen3_coder`. If
  structured output fails, check XGrammar, the actual package version, and model
  revisions. Do not treat a successful plain chat response as a tool-call test.
- An output cap can truncate an answer or tool call. Review the finish reason and
  adjust the cap centrally when needed, leaving room for input in the context.
- Restart the server after changing server settings and restart the app after
  changing its client settings. Existing services are not replaced by the installer.

## Optional container deployment

The Flash-Next preset is configured for native installation only. Passing
`--docker` fails explicitly because no matching pinned image is configured for it.
This prevents accidentally launching the older 27B image with a different model.

For `MODEL_PRESET = "27b"`, on a host with working Docker and NVIDIA CDI access,
`python3 scripts/start_sglang.py --docker` uses the pinned ARM64 CUDA 13 image. Preview with
`--docker --dry-run`. It retains weights/kernels in the `edbot-sglang-cache` Docker
volume and publishes only loopback port 30000. Inspect `docker logs edbot-sglang`.
An existing same-name container causes a failure rather than being replaced.
For legacy NVIDIA runtime setups, change `DOCKER_GPU_ARGS` in the code settings.
Docker permissions and rootless prerequisites must already be provided by the host.

## Sources

- [SGLang native installation](https://docs.sglang.io/docs/get-started/install)
- [Qwen3.8-Flash-Next GB10 cookbook](https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-Flash-Next)
- [Pinned NVIDIA Flash-Next checkpoint](https://huggingface.co/nvidia/Qwen3.8-Flash-Next-NVFP4/tree/fc694b54fb0174e0913e6adf86691ef85a4ead47)
- [Pinned NVIDIA chat template and thinking control](https://huggingface.co/nvidia/Qwen3.8-Flash-Next-NVFP4/blob/fc694b54fb0174e0913e6adf86691ef85a4ead47/chat_template.jinja)
- [SGLang 0.5.21 source](https://github.com/sgl-project/sglang/tree/v0.5.21)
- [File-backed N-gram table implementation](https://github.com/sgl-project/sglang/blob/v0.5.21/python/sglang/srt/models/qwen4_exp_ple_table.py)
- [Qwen3.8-27B GB10 cookbook](https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-27B)
- [27B server arguments](https://github.com/sgl-project/sglang/blob/v0.5.19/python/sglang/srt/server_args.py)
- [27B NVFP4 checkpoint](https://huggingface.co/RadixArk/Qwen3.8-27B-NVFP4)
- [27B DSpark checkpoint](https://huggingface.co/RadixArk/Qwen3.8-27B-DSpark)
- [Ollama Linux archives](https://docs.ollama.com/linux)
- [Docker rootless prerequisites](https://docs.docker.com/engine/security/rootless/)
- [Docker rootless troubleshooting](https://docs.docker.com/engine/security/rootless/troubleshoot/)
