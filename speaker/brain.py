"""The brain: sends the transcript to Claude and streams back speakable sentences (F4, F9)."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Iterator

import anthropic

from speaker import phrases
from speaker.config import Settings
from speaker.skills import Skills
from speaker.text import SentenceSplitter

log = logging.getLogger(__name__)

# Kept free of anything that changes per request (like the time), so it can be cached.
SYSTEM_PROMPT = """\
You are the voice of a smart speaker in someone's home. Everything you write is read aloud \
by a text-to-speech voice, so:
- Answer in one to three short spoken sentences, and lead with the answer.
- Answer only what was asked. Asked the time, say the time; mention the date or time zone \
only if asked.
- Write plain sentences only: no lists, headings, markdown, emoji or links.
- Say numbers the way a person would ("about three hundred eighty thousand kilometers").
- Offer to say more only when the short answer leaves out something the person would \
clearly want; most answers need no offer.

The question comes from speech-to-text and may contain misheard words. Go with the most \
likely meaning; if it makes no sense at all, say you didn't catch it.

Use the tools for the time, the date and timers, and never guess the time. You can't play \
music, control devices, check the weather or search the web; if asked, say so in one sentence.\
"""

MAX_TOOL_ROUNDS = 5


class Brain:
    """Holds a short conversation with Claude and yields the reply one sentence at a time."""

    def __init__(
        self,
        settings: Settings,
        skills: Skills,
        client: Any = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.settings = settings
        self.skills = skills
        self.client = client or anthropic.Anthropic(
            timeout=anthropic.Timeout(settings.api_timeout_s, connect=5.0),
            max_retries=1,
        )
        self._clock = clock
        # Each past turn is its messages: the question, any tool calls and results, the answer.
        self._turns: list[list[dict]] = []
        self._last_turn_at: float | None = None

    def reply(self, question: str) -> Iterator[str]:
        """Yields the spoken reply sentence by sentence. API failures become a spoken error."""
        self._forget_if_stale()
        question_message = {"role": "user", "content": question}
        messages = [m for turn in self._turns for m in turn] + [question_message]
        turn = [question_message]  # what this turn adds to the history, without thinking blocks
        spoken: list[str] = []
        try:
            for _ in range(MAX_TOOL_ROUNDS):
                response = yield from self._stream_round(messages, spoken)
                if response.stop_reason == "refusal":
                    log.warning("refusal: %s", getattr(response, "stop_details", None))
                    yield phrases.CANT_HELP
                    return
                tool_uses = [b for b in response.content if b.type == "tool_use"]
                if response.stop_reason != "tool_use" or not tool_uses:
                    break
                # Thinking and tool_use blocks go back unchanged, then one message with every result.
                results = {"role": "user", "content": [self.skills.run(b) for b in tool_uses]}
                messages += [{"role": "assistant", "content": response.content}, results]
                turn += [{"role": "assistant", "content": _history_blocks(response.content)}, results]
            else:
                log.warning("gave up after %d tool rounds", MAX_TOOL_ROUNDS)
        except anthropic.APIConnectionError as e:  # also covers timeouts
            log.warning("no connection to the API: %s", e)
            yield phrases.NO_INTERNET
            return
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            log.error("API key rejected: %s", e)
            yield phrases.KEY_PROBLEM
            return
        except TypeError as e:
            # The SDK raises a plain TypeError, before any request, when no API key is set.
            if "authentication" not in str(e).lower():
                raise
            log.error("no API key: set ANTHROPIC_API_KEY in /etc/pi-speaker/env")
            yield phrases.KEY_PROBLEM
            return
        except anthropic.RateLimitError as e:
            log.warning("rate limited: %s", e)
            yield phrases.BUSY
            return
        except anthropic.APIStatusError as e:
            log.error("API error %s: %s", e.status_code, e)
            if e.status_code >= 500:
                yield phrases.BUSY
            elif "credit balance" in str(e.message).lower():  # no dedicated error type for this
                yield phrases.NO_CREDIT
            else:
                yield phrases.SOMETHING_WRONG
            return

        if not spoken:
            spoken.append("Okay.")
            yield "Okay."
        # Only the final answer's text: a tool_use left over from MAX_TOOL_ROUNDS has no result.
        answer = "".join(b.text for b in response.content if b.type == "text").strip() or "Okay."
        turn.append({"role": "assistant", "content": [{"type": "text", "text": answer}]})
        self._remember(turn)

    def _stream_round(self, messages: list[dict], spoken: list[str]) -> Iterator[str]:
        """Streams one request, yielding sentences as they complete; returns the final message."""
        splitter = SentenceSplitter()
        with self.client.messages.stream(**self._request(messages)) as stream:
            for text in stream.text_stream:
                for sentence in splitter.feed(text):
                    spoken.append(sentence)
                    yield sentence
            response = stream.get_final_message()
        for sentence in splitter.flush():
            spoken.append(sentence)
            yield sentence
        log.debug("usage: %s", response.usage)
        return response

    def _request(self, messages: list[dict]) -> dict:
        s = self.settings
        thinking = {"type": "disabled"} if s.thinking == "off" else {"type": "adaptive"}
        return {
            "model": s.model,
            "max_tokens": s.max_tokens,
            "system": SYSTEM_PROMPT,
            "tools": self.skills.tools,
            "thinking": thinking,
            "output_config": {"effort": s.effort},
            "cache_control": {"type": "ephemeral"},
            "messages": messages,
        }

    def _remember(self, turn: list[dict]) -> None:
        # Whole turns are dropped from the front, so a tool call never loses its result.
        self._turns = (self._turns + [turn])[-self.settings.history_turns :]
        self._last_turn_at = self._clock()

    def _forget_if_stale(self) -> None:
        if self._last_turn_at is None:
            return
        if self._clock() - self._last_turn_at > self.settings.history_timeout_s:
            log.info("conversation forgotten after %.0f s of quiet", self.settings.history_timeout_s)
            self.forget()

    def forget(self) -> None:
        self._turns = []
        self._last_turn_at = None


def _history_blocks(content: list[Any]) -> list[dict]:
    """A finished turn's text and tool_use blocks, for replaying in later turns.

    Thinking blocks are left out: past turns don't need them, and without them, trimming old
    turns can never invalidate one (a changed prefix makes a replayed thinking block a 400).
    """
    blocks = []
    for b in content:
        if b.type == "text" and b.text.strip():
            blocks.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
    return blocks
