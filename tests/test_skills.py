import json
import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from speaker.skills import Skills, Timers, describe_duration


def tool(name, **args):
    return SimpleNamespace(type="tool_use", id=f"toolu_{name}", name=name, input=args)


class DescribeDurationTest(unittest.TestCase):
    def test_reads_naturally(self):
        self.assertEqual(describe_duration(10), "10 seconds")
        self.assertEqual(describe_duration(60), "1 minute")
        self.assertEqual(describe_duration(540), "9 minutes")
        self.assertEqual(describe_duration(3725), "1 hour, 2 minutes and 5 seconds")


class TimersTest(unittest.TestCase):
    def test_a_timer_rings_with_its_name(self):
        done = threading.Event()
        said = []
        timers = Timers(on_done=lambda text: (said.append(text), done.set()))
        timers.set(1, "pasta")
        self.assertTrue(done.wait(3))
        self.assertEqual(said, ["Your pasta timer is done."])
        self.assertEqual(timers.running(), [])

    def test_unlabelled_timers_are_named_by_length(self):
        timers = Timers(on_done=lambda text: None)
        self.assertEqual(timers.set(600).name(), "10 minute timer")
        timers.cancel()

    def test_a_cancelled_timer_never_rings(self):
        said = []
        timers = Timers(on_done=said.append)
        timer = timers.set(1)
        self.assertEqual([t.id for t in timers.cancel(timer.id)], [timer.id])
        threading.Event().wait(1.3)
        self.assertEqual(said, [])


class SkillsTest(unittest.TestCase):
    def setUp(self):
        self.said = []
        self.timers = Timers(on_done=self.said.append)
        fixed = datetime(2026, 10, 4, 9, 5, tzinfo=timezone(timedelta(hours=-7), "PDT"))
        self.skills = Skills(self.timers, now=lambda: fixed)

    def tearDown(self):
        self.timers.cancel()

    def run_tool(self, name, **args):
        result = self.skills.run(tool(name, **args))
        self.assertEqual(result["tool_use_id"], f"toolu_{name}")
        return result

    def test_time_note_is_spoken_style(self):
        self.assertEqual(self.skills.time_note(), "[Local time: 9:05 AM on Sunday, October 4, 2026, PDT]")

    def test_there_is_no_clock_tool(self):
        # The time comes with each question instead, saving a round trip to the API.
        self.assertNotIn("get_current_time", {t["name"] for t in self.skills.tools})

    def test_set_list_and_cancel(self):
        set_result = json.loads(self.run_tool("set_timer", duration_seconds=540, label="pasta")["content"])
        self.assertEqual(set_result["name"], "pasta timer")
        listed = json.loads(self.run_tool("list_timers")["content"])["timers"]
        self.assertEqual([t["name"] for t in listed], ["pasta timer"])
        cancelled = json.loads(self.run_tool("cancel_timer", timer_id=set_result["timer_id"])["content"])
        self.assertEqual(cancelled, {"cancelled": ["pasta timer"]})

    def test_cancel_without_id_cancels_everything(self):
        self.run_tool("set_timer", duration_seconds=60)
        self.run_tool("set_timer", duration_seconds=120)
        cancelled = json.loads(self.run_tool("cancel_timer")["content"])["cancelled"]
        self.assertEqual(len(cancelled), 2)

    def test_bad_input_comes_back_as_an_error_result(self):
        for args in ({}, {"duration_seconds": 0}, {"duration_seconds": "ten"}, {"duration_seconds": 10**6}):
            result = self.run_tool("set_timer", **args)
            self.assertTrue(result.get("is_error"), args)
        self.assertTrue(self.run_tool("cancel_timer", timer_id=99).get("is_error"))
        self.assertTrue(self.skills.run(tool("no_such_tool")).get("is_error"))


if __name__ == "__main__":
    unittest.main()
