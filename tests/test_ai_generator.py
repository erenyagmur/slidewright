"""AI pipeline tests with a fake HTTP transport (no network, no API key)."""
import json

import anthropic
import httpx2 as httpx

from ai_generator import ai_generate, parse_brief_local

GOOD = [  # 3-move level, 3 trucks
    {"id": "R", "x": 0, "y": 2, "length": 2, "orientation": "H"},
    {"id": "A", "x": 2, "y": 0, "length": 3, "orientation": "V"},
    {"id": "F", "x": 3, "y": 0, "length": 3, "orientation": "H"},
    {"id": "C", "x": 4, "y": 1, "length": 2, "orientation": "V"},
    {"id": "B", "x": 3, "y": 3, "length": 3, "orientation": "V"},
    {"id": "D", "x": 0, "y": 5, "length": 2, "orientation": "H"},
    {"id": "E", "x": 4, "y": 5, "length": 2, "orientation": "H"},
]
OVERLAP = [GOOD[0], {"id": "A", "x": 1, "y": 1, "length": 2, "orientation": "V"}]
UNSOLVABLE = [GOOD[0], {"id": "X", "x": 4, "y": 2, "length": 2, "orientation": "H"}]
SPEC = {"level_number": 4, "difficulty_min": 3.0, "difficulty_max": 5.0, "target_moves": 3,
        "moves_tolerance": 1, "trucks_min": 0, "trucks_max": 3, "exit_truck": False,
        "mechanic": "trucks as walls"}


class FakeClaude:
    def __init__(self):
        self.requests = []
        self.variant_calls = 0

    def reply(self, obj):
        return {"id": "msg_x", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                "content": [{"type": "text", "text": json.dumps(obj)}], "stop_reason": "end_turn",
                "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        last = body["messages"][-1]["content"]
        text = last if isinstance(last, str) else json.dumps(last)
        if "Turn this level brief" in text:
            obj = SPEC
        elif "designer's note" in text:
            obj = {"notes": [{"name": "Fixed", "why_it_works": "w", "what_it_teaches": "t"}]}
        else:
            self.variant_calls += 1
            if self.variant_calls == 1:
                obj = {"variants": [{"name": "Overlap", "idea": "i", "vehicles": OVERLAP},
                                    {"name": "Stuck", "idea": "i", "vehicles": UNSOLVABLE}]}
            else:
                obj = {"variants": [{"name": "Fixed", "idea": "i", "vehicles": GOOD}]}
        return httpx.Response(200, json=self.reply(obj))


def test_ai_loop_rejects_then_accepts_with_feedback():
    fake = FakeClaude()
    client = anthropic.Anthropic(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(fake)))
    levels, report = ai_generate("level 4, trucks as walls, about 3 moves", count=1, variants=2,
                                 client=client, log=lambda *_: None)
    assert len(levels) == 1 and levels[0].source == "ai"
    assert levels[0].metrics["min_moves"] == 3
    assert levels[0].note["what_it_teaches"] == "t"
    # round 1 rejected both with solver reasons, round 2 accepted
    r1 = report["rounds"][0]
    assert not r1[0]["ok"] and "overlaps" in r1[0]["reasons"][0]
    assert not r1[1]["ok"] and "unsolvable" in r1[1]["reasons"][0]
    assert report["rounds"][1][0]["ok"]
    # the feedback turn carried the solver report back to the model
    fb = fake.requests[2]["messages"][-1]["content"]
    assert "REJECTED" in fb and "unsolvable" in fb
    # request shape: model, structured output, adaptive thinking, server-side fallback
    req = fake.requests[1]
    assert req["model"] == "claude-opus-5-5"
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert req["thinking"] == {"type": "adaptive"}
    assert req["fallbacks"] == "default"


def test_fallback_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    levels, report = ai_generate("level 3, easy, about 4 moves", count=1, log=lambda *_: None, seed=1)
    assert report["mode"] == "procedural"
    assert levels and levels[0].note["why_it_works"]


def test_local_brief_parser():
    s = parse_brief_local("level 12, medium-hard, introduce trucks blocking the exit row, about 15 moves")
    assert s.level_number == 12 and s.target_moves == 15
    assert (s.difficulty_min, s.difficulty_max) == (5.5, 7.0)
    assert s.exit_truck and s.trucks_min >= 1
