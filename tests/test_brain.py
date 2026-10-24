"""Brain tests against a fake Anthropic client, so they need no API key or network."""

import contextlib
import unittest
from types import SimpleNamespace

import anthropic

try:
    import httpx2 as httpx  # anthropic 1.x
except ImportError:
    import httpx  # anthropic 0.x

from speaker import phrases
from speaker.brain import Brain
from speaker.config import Settings
from speaker.skills import Skills, Timers


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_block(name, **args):
    return SimpleNamespace(type="tool_use", id=f"toolu_{name}", name=name, input=args)


class FakeStream:
    def __init__(self, chunks, message):
        self.text_stream = iter(chunks)
        self._message = message

    def get_final_message(self):
        return self._message


class FakeClient:
    """Replays scripted responses: each is (text chunks, content blocks, stop_reason) or an exception."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    @contextlib.contextmanager
    def stream(self, **request):
        # Copy the list: the brain appends to it after this call returns.
        self.requests.append({**request, "messages": list(request["messages"])})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        chunks, content, stop_reason = response
        message = SimpleNamespace(content=content, stop_reason=stop_reason, stop_details=None, usage=None)
        yield FakeStream(chunks, message)


def answer(*chunks):
    return list(chunks), [text_block("".join(chunks))], "end_turn"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def api_error(cls, status, message="boom"):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(message, response=httpx.Response(status, request=request), body=None)


class BrainTest(unittest.TestCase):
    def setUp(self):
        self.timers = Timers(on_done=lambda text: None)
        self.clock = Clock()

    def tearDown(self):
        self.timers.cancel()

    def brain(self, *responses, **settings):
        self.client = FakeClient(*responses)
        return Brain(Settings(**settings), Skills(self.timers), client=self.client, clock=self.clock)

    def test_streams_sentences_as_they_complete(self):
        brain = self.brain(answer("It is about 384,000 km", " away. That's far", "!"))
        self.assertEqual(list(brain.reply("How far is the moon?")), ["It is about 384,000 km away.", "That's far!"])

    def test_request_uses_haiku_low_effort_and_the_tools(self):
        brain = self.brain(answer("Hi."))
        list(brain.reply("Hello"))
        request = self.client.requests[0]
        self.assertEqual(request["model"], "claude-haiku-5-5")
        self.assertEqual(request["output_config"], {"effort": "low"})
        self.assertEqual(request["thinking"], {"type": "adaptive"})
        self.assertNotIn("temperature", request)
        self.assertEqual(
            {t["name"] for t in request["tools"]},
            {"get_current_time", "set_timer", "list_timers", "cancel_timer"},
        )

    def test_thinking_can_be_turned_off(self):
        brain = self.brain(answer("Hi."), thinking="off")
        list(brain.reply("Hello"))
        self.assertEqual(self.client.requests[0]["thinking"], {"type": "disabled"})

    def test_runs_a_timer_tool_and_speaks_both_rounds(self):
        thinking = SimpleNamespace(type="thinking", thinking="", signature="sig")
        call = tool_block("set_timer", duration_seconds=10)
        brain = self.brain(
            (["Setting it now."], [thinking, text_block("Setting it now."), call], "tool_use"),
            answer("Your 10 second timer is running."),
        )
        spoken = list(brain.reply("Set a timer for ten seconds"))
        self.assertEqual(spoken, ["Setting it now.", "Your 10 second timer is running."])
        self.assertEqual(len(self.timers.running()), 1)
        second = self.client.requests[1]["messages"]
        # The assistant turn goes back unchanged (thinking included), then the tool result.
        self.assertIs(second[-2]["content"][0], thinking)
        self.assertEqual(second[-1]["content"][0]["tool_use_id"], "toolu_set_timer")

    def test_remembers_recent_turns_as_plain_text(self):
        brain = self.brain(answer("Mount Everest."), answer("Weeks."))
        list(brain.reply("What's the tallest mountain?"))
        list(brain.reply("How long to climb it?"))
        self.assertEqual(
            self.client.requests[1]["messages"],
            [
                {"role": "user", "content": "What's the tallest mountain?"},
                {"role": "assistant", "content": "Mount Everest."},
                {"role": "user", "content": "How long to climb it?"},
            ],
        )

    def test_forgets_after_five_quiet_minutes(self):
        brain = self.brain(answer("Mount Everest."), answer("Climb what?"))
        list(brain.reply("What's the tallest mountain?"))
        self.clock.now += 301
        list(brain.reply("How long to climb it?"))
        self.assertEqual(len(self.client.requests[1]["messages"]), 1)

    def test_keeps_only_the_last_few_exchanges(self):
        brain = self.brain(*[answer(f"Answer {i}.") for i in range(6)], history_turns=2)
        for i in range(6):
            list(brain.reply(f"Question {i}"))
        self.assertEqual(len(self.client.requests[-1]["messages"]), 5)  # 2 exchanges + the new question

    def test_failures_become_spoken_errors(self):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        cases = [
            (anthropic.APIConnectionError(request=request), phrases.NO_INTERNET),
            (anthropic.APITimeoutError(request=request), phrases.NO_INTERNET),
            (api_error(anthropic.AuthenticationError, 401), phrases.KEY_PROBLEM),
            (api_error(anthropic.RateLimitError, 429), phrases.BUSY),
            (api_error(anthropic.InternalServerError, 500), phrases.BUSY),
            (api_error(anthropic.BadRequestError, 400), phrases.SOMETHING_WRONG),
            (
                api_error(anthropic.BadRequestError, 400, "Your credit balance is too low to access the Anthropic API."),
                phrases.NO_CREDIT,
            ),
        ]
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                brain = self.brain(error)
                self.assertEqual(list(brain.reply("Hello")), [expected])

    def test_a_failed_turn_is_not_remembered(self):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        brain = self.brain(anthropic.APIConnectionError(request=request), answer("Hello."))
        list(brain.reply("First"))
        list(brain.reply("Second"))
        self.assertEqual(len(self.client.requests[1]["messages"]), 1)

    def test_refusal_is_spoken_politely(self):
        brain = self.brain(([], [], "refusal"))
        self.assertEqual(list(brain.reply("Something bad")), [phrases.CANT_HELP])


if __name__ == "__main__":
    unittest.main()
