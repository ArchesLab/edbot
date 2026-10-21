"""Exercise Edbot against a scripted local OpenAI-compatible HTTP server.

No model downloads, SEBook sync, or external inference calls are needed.
Run with: python -m unittest discover -s tests -v
"""
import asyncio
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from edbot import model_config as config


def tool_reply(name, arguments):
    """Split arguments as an inference server does while streaming a tool call."""
    arguments = json.dumps(arguments)
    midpoint = len(arguments) // 2
    return {
        "deltas": [
            {"role": "assistant", "content": ""},
            {"tool_calls": [{"index": 0, "id": "call_test", "type": "function",
                             "function": {"name": name, "arguments": arguments[:midpoint]}}]},
            {"tool_calls": [{"index": 0, "function": {"arguments": arguments[midpoint:]}}]},
        ],
        "finish_reason": "tool_calls",
    }


def text_reply(*parts):
    return {"deltas": [{"role": "assistant", "content": ""},
                       *({"content": part} for part in parts)], "finish_reason": "stop"}


def complete_message(reply):
    """Assemble the fixture's full response without repairing malformed arguments."""
    if "message" in reply:
        return reply["message"]
    content, calls = [], {}
    for delta in reply["deltas"]:
        content.append(delta.get("content") or "")
        for part in delta.get("tool_calls", []):
            call = calls.setdefault(part["index"], {
                "id": "", "type": "function", "function": {"name": "", "arguments": ""},
            })
            if "id" in part:
                call["id"] += part["id"]
            for key in ("name", "arguments"):
                call["function"][key] += part.get("function", {}).get(key) or ""
    message = {"role": "assistant", "content": "".join(content)}
    if calls:
        message["tool_calls"] = [calls[index] for index in sorted(calls)]
    return message


class ScriptedServer:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def __enter__(self):
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fixture.requests.append((self.path, payload))
                reply = fixture.replies.pop(0) if fixture.replies else {"error": "unexpected request"}
                if "error" in reply:
                    body = json.dumps({"error": {"message": reply["error"],
                                                "type": "invalid_request_error", "code": "test_error"}}).encode()
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                elif payload.get("stream"):
                    chunks = []
                    for delta in [*reply["deltas"], {}]:
                        chunks.append({
                            "id": f"chatcmpl-test-{len(fixture.requests)}",
                            "object": "chat.completion.chunk", "created": 1,
                            "model": config.MODEL_NAME,
                            "choices": [{"index": 0, "delta": delta, "logprobs": None,
                                         "finish_reason": reply["finish_reason"] if not delta else None}],
                        })
                    if "usage" in reply:
                        chunks[-1]["usage"] = reply["usage"]
                    body = ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
                            + "data: [DONE]\n\n").encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                else:
                    response = {
                        "id": f"chatcmpl-test-{len(fixture.requests)}",
                        "object": "chat.completion", "created": 1, "model": config.MODEL_NAME,
                        "choices": [{"index": 0, "message": complete_message(reply),
                                     "logprobs": None, "finish_reason": reply["finish_reason"]}],
                    }
                    if "usage" in reply:
                        response["usage"] = reply["usage"]
                    body = json.dumps(response).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        self.environment = patch.dict(os.environ, {
            "EDBOT_CHAT_BASE_URL": self.base_url,
            "EDBOT_CHAT_API_KEY": "local-test",
            "LANGSMITH_TRACING": "false",
            "LANGCHAIN_TRACING_V2": "false",
        })
        self.environment.start()
        return self

    def __exit__(self, *args):
        self.environment.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class SGLangIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Framework imports and fixture setup are synchronous; these tests check protocol,
        # not event-loop timing. Avoid reporting those imports as slow async callbacks.
        asyncio.get_running_loop().set_debug(False)

    def assert_chat_requests(self, server, count):
        self.assertEqual(len(server.requests), count)
        self.assertEqual(server.replies, [])
        for path, body in server.requests:
            self.assertEqual(path, "/v1/chat/completions")
            self.assertEqual(body["model"], config.MODEL_NAME)
            self.assertEqual(body["stream"], not (config.BUFFER_TOOL_RESPONSES
                                                  and bool(body.get("tools"))))
            self.assertEqual(body.get("max_tokens", body.get("max_completion_tokens")), 4096)
            self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
            self.assertEqual(body.get("temperature"), 0, "Production sampling must match the evaluated preset")
            self.assertNotIn("num_ctx", body)  # context is configured once on the SGLang server

    def build_agent(self):
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.store.memory import InMemoryStore
        from edbot import edbot_agent

        # Startup normally syncs SEBook and embeds it; this transport test never searches it.
        with patch.object(edbot_agent, "load_sebook_store"):
            return edbot_agent.create_edbot_agent(checkpointer=InMemorySaver(), store=InMemoryStore())

    async def events_for(self, agent):
        from edbot import service

        # Use the real graph while avoiding service's persistent production SQLite files.
        with patch.object(service, "_agent", agent):
            return [event async for event in service.chat_turn("sglang-contract-test", "Give me a practice question.")]

    async def test_factory_streams_through_configured_chat_completions_endpoint(self):
        """Catch wrong endpoint selection, missing server extras, and broken SSE text handling."""
        from edbot.chat_model import create_chat_model

        with ScriptedServer([text_reply("Hello", " student.")]) as server:
            model = create_chat_model()
            chunks = [chunk async for chunk in model.astream("Hello")]
            self.assertEqual("".join(chunk.text for chunk in chunks), "Hello student.")
            self.assert_chat_requests(server, 1)

    async def test_tool_transport_switch_preserves_request_result_and_usage(self):
        """Use real HTTP to verify the public option selects the full-response path."""
        from langchain_core.messages import AIMessageChunk
        from edbot.chat_model import create_chat_model
        from edbot.service import TURN_TIMEOUT_SECONDS

        arguments = {"result": "synthetic evidence"}
        tool = {"type": "function", "function": {
            "name": "SyntheticResult", "description": "Return a synthetic result.",
            "parameters": {"type": "object", "properties": {"result": {"type": "string"}},
                           "required": ["result"]},
        }}
        for buffered in (True, False):
            with self.subTest(buffered=buffered), \
                    patch.object(config, "BUFFER_TOOL_RESPONSES", buffered, create=True):
                reply = tool_reply("SyntheticResult", arguments)
                reply["usage"] = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
                with ScriptedServer([reply]) as server:
                    model = create_chat_model()
                    # Profilers request usage via this property; a call-level stream_usage
                    # kwarg would incorrectly reach the non-streaming OpenAI endpoint.
                    model.stream_usage = True
                    chunks = [chunk async for chunk in model.bind(
                        tools=[tool], tool_choice="required").astream("Synthetic request")]
                request = server.requests[0][1]
                self.assertEqual(request["stream"], not buffered)
                self.assertEqual(request["tools"], [tool])
                self.assertEqual(request["tool_choice"], "required")
                self.assertNotIn("stream_usage", request)
                if buffered:
                    self.assertNotIn("stream_options", request)
                    self.assertEqual(len(chunks), 1)
                    self.assertNotIsInstance(chunks[0], AIMessageChunk)
                complete = chunks[0]
                for chunk in chunks[1:]:
                    complete += chunk
                self.assertEqual(complete.tool_calls[0]["args"], arguments)
                self.assertEqual(complete.invalid_tool_calls, [])
                self.assertEqual(complete.response_metadata["finish_reason"], "tool_calls")
                self.assertEqual(complete.usage_metadata["input_tokens"], 100)
                self.assertEqual(complete.usage_metadata["output_tokens"], 20)
                self.assert_chat_requests(server, 1)
                self.assertEqual(model.request_timeout.read, 300 if buffered else 120)
                self.assertLess(model.request_timeout.read, TURN_TIMEOUT_SECONDS)
                self.assertEqual((model.request_timeout.connect, model.request_timeout.write,
                                  model.request_timeout.pool), (120, 120, 120))

    async def test_subagent_structured_output_remains_private_in_student_stream(self):
        """Catch child backend divergence, required-tool incompatibility, and rubric leakage."""
        private_rubric = "PRIVATE_RUBRIC_723: the correct answer is hidden"
        question = "Explain how a queue could represent pending requests."
        task = {
            "subagent_type": "content-generating-agent",
            "description": json.dumps({"mode": "generate_question", "concept": "queues",
                                       "target_tier": "Apply"}),
        }
        cga_output = {
            "mode": "generate_question", "concept": "queues", "target_tier": "Apply",
            "content": question, "format": "short_answer", "rubric": private_rubric,
            "concept_tags": ["queues"], "sources": ["SEBook queues"],
        }
        with ScriptedServer([tool_reply("task", task), tool_reply("CGAOutput", cga_output)]) as server:
            agent = self.build_agent()
            events = await self.events_for(agent)
            self.assertEqual([event.type for event in events if event.type in {"done", "error"}], ["done"])
            self.assertEqual("".join(event.text for event in events if event.type == "text"), question)
            self.assertNotIn(private_rubric, "".join(event.model_dump_json() for event in events))
            self.assert_chat_requests(server, 2)
            child = server.requests[1][1]
            self.assertEqual(child["tool_choice"], "required")
            self.assertIn("CGAOutput", [tool["function"]["name"] for tool in child["tools"]])
            # Skipping the rewrite must not lose the question or its private key
            # when the student returns to submit an answer.
            from edbot import service
            with patch.object(service, "_agent", agent):
                history = await service.get_history("sglang-contract-test")
                self.assertEqual(history[-1].content, question)
                self.assertNotIn(private_rubric, str(history))
                server.replies.append(text_reply("Which behavior would that preserve?"))
                followup = [event async for event in service.chat_turn(
                    "sglang-contract-test", "I would handle the oldest request first.")]
            self.assertEqual(followup[-1].type, "done")
            self.assert_chat_requests(server, 3)
            self.assertIn(private_rubric, json.dumps(server.requests[-1][1]["messages"]))

    async def test_long_response_is_delivered_and_server_error_is_sanitized(self):
        """Exercise complete reply delivery and provider-error handling."""
        first = "A queue preserves the order in which requests arrive. " * 5
        last = "The oldest request is handled first."
        with ScriptedServer([text_reply(first, last)]) as server:
            events = await self.events_for(self.build_agent())
            text = [event.text for event in events if event.type == "text"]
            self.assertEqual("".join(text), first + last)
            self.assertEqual(events[-1].type, "done")
            self.assert_chat_requests(server, 1)
            parent_tools = {tool["function"]["name"] for tool in server.requests[0][1]["tools"]}
            self.assertTrue({"ls", "read_file", "glob", "grep"} <= parent_tools)
            self.assertFalse({"write_file", "edit_file", "delete"} & parent_tools)

        with ScriptedServer([{"error": "PRIVATE_SERVER_DIAGNOSTIC"}]) as server:
            with self.assertLogs("edbot.service", level="ERROR"):
                events = await self.events_for(self.build_agent())
            self.assertEqual(events[-1].type, "error")
            self.assertNotIn("PRIVATE_SERVER_DIAGNOSTIC", events[-1].message)
            self.assertFalse(any(event.type == "done" for event in events))
            self.assert_chat_requests(server, 1)

    async def test_late_parent_tool_call_does_not_leak_its_preamble_or_change_public_history(self):
        from edbot import service

        task = {"subagent_type": "content-generating-agent", "description": json.dumps({
            "mode": "explain_at_tier", "concept": "queues", "target_tier": "Apply",
        })}
        late = tool_reply("task", task)
        late["deltas"][1:1] = [{"content": "PRIVATE_ROUTING_DIAGNOSTIC " * 10},
                                {"content": "More private routing notes before the task."}]
        final = "A queue removes the oldest pending item first."
        output = {"mode": "explain_at_tier", "concept": "queues", "target_tier": "Apply",
                  "content": final, "sources": ["Synthetic source"]}
        with ScriptedServer([late, tool_reply("CGAOutput", output)]) as server:
            agent = self.build_agent()
            events = await self.events_for(agent)
            self.assertEqual(events[-1].type, "done")
            self.assertEqual("".join(event.text for event in events if event.type == "text"), final)
            with patch.object(service, "_agent", agent):
                history = await service.get_history("sglang-contract-test")
            self.assertEqual([message.content for message in history if message.role == "edbot"], [final])
            self.assert_chat_requests(server, 2)

    async def test_truncated_parent_is_hidden_and_failed_before_successful_retry(self):
        from edbot import service

        unfinished = "UNFINISHED_PARENT_REPLY " * 20
        truncated = text_reply(unfinished[:230], unfinished[230:])
        truncated["finish_reason"] = "length"
        final = "Which part would you like to discuss first?"
        with ScriptedServer([truncated, text_reply(final)]) as server:
            agent = self.build_agent()
            with patch.object(service, "_agent", agent), patch.object(service.logger, "exception"):
                failed = [event async for event in service.chat_turn("truncated-parent", "Help me.")]
                self.assertEqual(failed[-1].type, "error")
                self.assertFalse(any(event.type in {"text", "done"} for event in failed))
                history = await service.get_history("truncated-parent")
                self.assertNotIn("UNFINISHED", str(history))
                retried = [event async for event in service.chat_turn("truncated-parent", "Please try again.")]
                history = await service.get_history("truncated-parent")
            self.assertEqual(retried[-1].type, "done")
            self.assertEqual("".join(event.text for event in retried if event.type == "text"), final)
            self.assertEqual([message.content for message in history if message.role == "edbot"], [final])
            self.assert_chat_requests(server, 2)

    async def test_complete_parent_message_with_invalid_tools_is_not_public(self):
        from langchain_core.messages import AIMessage
        from edbot import service

        class InvalidMessageAgent:
            async def astream(self, *args, **kwargs):
                yield AIMessage(content="PRIVATE_PREAMBLE " * 20, invalid_tool_calls=[{
                    "name": "task", "args": "not-json", "id": "bad-task", "error": "Invalid JSON",
                    "type": "invalid_tool_call",
                }]), {"langgraph_node": "model", "langgraph_checkpoint_ns": ""}

        with patch.object(service, "_agent", InvalidMessageAgent()), patch.object(service.logger, "exception"):
            events = [event async for event in service.chat_turn("invalid-complete-message", "Help me.")]
        self.assertEqual(events[-1].type, "error")
        self.assertFalse(any(event.type in {"text", "done"} for event in events))


if __name__ == "__main__":
    unittest.main()
