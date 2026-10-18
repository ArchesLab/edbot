"""Check the embedding HTTP contract without Ollama or a model download."""
import asyncio
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from ollama import ResponseError

from edbot.embedding_model import create_embedding_model


class EmbeddingServer:
    def __enter__(self):
        fixture = self
        self.requests = []
        self.reject = False

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fixture.requests.append((self.path, payload))
                if fixture.reject:
                    response = {"error": "input length exceeds maximum context length"}
                    self.send_response(400)
                else:
                    response = {"model": payload["model"],
                                "embeddings": [[0.25, 0.75] for _ in payload["input"]]}
                    self.send_response(200)
                body = json.dumps(response).encode()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()
        self.environment = patch.dict(os.environ, {
            "OLLAMA_HOST": f"http://127.0.0.1:{self.server.server_port}",
        })
        self.environment.start()
        return self

    def __exit__(self, *args):
        self.environment.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class EmbeddingModelTests(unittest.TestCase):
    def assert_request(self, request, inputs):
        path, body = request
        self.assertEqual(path, "/api/embed")
        self.assertEqual(body["model"], "qwen3-embedding:8b")
        self.assertEqual(body["input"], inputs)
        self.assertEqual(body["options"]["num_ctx"], 8192)
        self.assertIs(body["truncate"], False)

    def test_sync_documents_and_query_send_bounded_context_without_truncation(self):
        with EmbeddingServer() as server:
            model = create_embedding_model()
            model.dimensions = 2
            model.keep_alive = -1
            model.num_thread = 2
            self.assertEqual(model.embed_documents(["first", "second"]), [[0.25, 0.75], [0.25, 0.75]])
            self.assertEqual(model.embed_query("query"), [0.25, 0.75])
            self.assertEqual(len(server.requests), 2)
            self.assert_request(server.requests[0], ["first", "second"])
            self.assert_request(server.requests[1], ["query"])
            for _, body in server.requests:
                self.assertEqual(body["dimensions"], 2)
                self.assertEqual(body["keep_alive"], -1)
                self.assertEqual(body["options"]["num_thread"], 2)

    def test_async_documents_and_query_use_the_same_strict_context(self):
        async def embed(model):
            self.assertEqual(await model.aembed_documents(["document"]), [[0.25, 0.75]])
            self.assertEqual(await model.aembed_query("query"), [0.25, 0.75])

        with EmbeddingServer() as server:
            asyncio.run(embed(create_embedding_model()))
            self.assertEqual(len(server.requests), 2)
            self.assert_request(server.requests[0], ["document"])
            self.assert_request(server.requests[1], ["query"])

    def test_oversize_server_errors_surface_in_sync_and_async_queries(self):
        with EmbeddingServer() as server:
            server.reject = True
            model = create_embedding_model()
            for call in (lambda: model.embed_query("oversized input"),
                         lambda: asyncio.run(model.aembed_query("oversized input"))):
                with self.subTest(call=call), self.assertRaisesRegex(ResponseError, "exceeds maximum context"):
                    call()
            self.assertEqual(len(server.requests), 2)
            for request in server.requests:
                self.assert_request(request, ["oversized input"])


if __name__ == "__main__":
    unittest.main()
