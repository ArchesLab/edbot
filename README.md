# EdBot

## 1. Start Ollama

EdBot runs its models locally through [Ollama](https://ollama.com).

```bash
# Start the Ollama server (leave this running in its own terminal)
ollama serve

# First time only: download the chat and embedding models
ollama pull qwen3.8:27b
ollama pull qwen3-embedding:8b

# Check that both models are installed
ollama list
```

The model names are set in `src/edbot/edbot_agent.py` (`MODEL_NAME`) and
`src/edbot/tools/markdown_embedding.py` (`EMBEDDING_MODEL`).

## 2. Start the Chainlit UI

Install dependencies (first time only):

```bash
uv sync
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
