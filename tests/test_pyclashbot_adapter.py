import unittest

from hastycr.adapters.pyclashbot import PyClashBotActionSink
from hastycr.models import Action


class FakeController:
    def __init__(self):
        self.clicks = []

    def click(self, x, y, clicks, interval):
        self.clicks.append((x, y, clicks, interval))


class PyClashBotAdapterTests(unittest.TestCase):
    def test_normalized_action_becomes_two_clicks(self):
        controller = FakeController()
        sink = PyClashBotActionSink(
            controller,
            frame_width=400,
            frame_height=600,
            card_centres=((50, 550), (150, 550), (250, 550), (350, 550)),
        )
        sink.execute(Action(card_slot=2, x=0.5, y=0.25))
        self.assertEqual((250, 550, 1, 0.0), controller.clicks[0])
        self.assertEqual((200, 150, 1, 0.0), controller.clicks[1])


if __name__ == "__main__":
    unittest.main()
