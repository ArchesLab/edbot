"""The student's turn counter must keep counting across chats, so a new chat never looks older than saved work."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from edbot import student_model, turn_count
from edbot.interface_def import EdbotContext, Message


class PlainModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class TurnCountTests(unittest.IsolatedAsyncioTestCase):
    async def test_counter_starts_after_turns_saved_before_it_existed(self):
        store = InMemoryStore()
        await student_model.save_entry(store, "alice", "recursion", "Apply", "medium", "Traced f(3).", 12)
        self.assertEqual(await turn_count.next_turn(store, "alice"), 13)
        self.assertEqual(await turn_count.next_turn(store, "alice"), 14)
        self.assertEqual(await turn_count.next_turn(store, "bob"), 1, "Each student has their own counter")

    async def test_concurrent_chats_never_take_the_same_turn(self):
        store = InMemoryStore()
        turns = await asyncio.gather(*(turn_count.next_turn(store, "alice") for _ in range(5)))
        self.assertEqual(sorted(turns), [1, 2, 3, 4, 5])

    def test_without_a_counter_the_conversation_is_counted(self):
        conversation = [Message(role="student", content="a"), Message(role="edbot", content="b"),
                        {"role": "student", "content": "c"}]
        self.assertEqual(turn_count.current_turn(EdbotContext(student_id="alice"), conversation), 2)
        self.assertEqual(turn_count.current_turn(SimpleNamespace(), conversation), 2)
        self.assertEqual(turn_count.current_turn(EdbotContext(student_id="alice", student_turn=40), conversation), 40)

    async def test_a_new_chat_continues_the_students_count(self):
        from edbot import edbot_agent, service
        store = InMemoryStore()
        model = PlainModel(responses=[AIMessage(content=f"Reply {i}.") for i in range(3)])
        with patch.object(edbot_agent, "create_chat_model", return_value=model), \
                patch.object(edbot_agent, "load_sebook_store"):
            graph = edbot_agent.create_edbot_agent(checkpointer=InMemorySaver(serde=service.SERDE), store=store)
        with patch.object(service, "_agent", graph):
            for thread in ("alice:first", "alice:first", "alice:second"):
                events = [event async for event in service.chat_turn("alice", "Hello.", thread_id=thread)]
                self.assertEqual(events[-1].type, "done")
            self.assertEqual(len(await service.get_history("alice", "alice:second")), 2, "The new chat starts empty")
        saved = await store.aget(turn_count.namespace("alice"), turn_count.TURN_KEY)
        self.assertEqual(saved.value["count"], 3, "The second chat's first message is the student's third turn")


if __name__ == "__main__":
    unittest.main()
