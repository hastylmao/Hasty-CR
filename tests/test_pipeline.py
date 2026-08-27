import unittest

from hastycr.models import Action, GameState
from hastycr.pipeline import ChimeraPipeline


class Source:
    def capture(self):
        return "frame"


class Perception:
    def observe(self, frame):
        return GameState(frame=frame, screen="battle", elixir=5)


class Policy:
    def decide(self, state):
        return Action(card_slot=1, x=0.25, y=0.75)


class Sink:
    def __init__(self):
        self.actions = []

    def execute(self, action):
        self.actions.append(action)


class PipelineTests(unittest.TestCase):
    def test_dry_run_does_not_execute(self):
        sink = Sink()
        result = ChimeraPipeline(Source(), Perception(), Policy(), sink).step()
        self.assertFalse(result.executed)
        self.assertEqual([], sink.actions)
        self.assertEqual("battle", result.state.screen)

    def test_explicit_gate_executes(self):
        sink = Sink()
        result = ChimeraPipeline(
            Source(), Perception(), Policy(), sink, allow_live_actions=True
        ).step()
        self.assertTrue(result.executed)
        self.assertEqual(1, len(sink.actions))

    def test_action_validation(self):
        with self.assertRaises(ValueError):
            Action(card_slot=4, x=0.5, y=0.5).validate()


if __name__ == "__main__":
    unittest.main()

