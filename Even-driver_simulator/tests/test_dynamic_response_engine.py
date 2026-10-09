import time

import pytest

from engine.dynamic_response_engine import (
    DynamicResponseEngine,
    DynamicResponseRule,
    linear_byte_response,
)


class FakeDatabase:
    def __init__(self):
        self.updates = []

    def OBDDb_UpdateRes(self, response, checksum, frame_index, response_index):
        self.updates.append((response, checksum, frame_index, response_index))


def test_rule_validation():
    with pytest.raises(ValueError):
        DynamicResponseRule(-1, 0, 20, lambda *_: "AA", "NONE")
    with pytest.raises(ValueError):
        DynamicResponseRule(0, 0, 0, lambda *_: "AA", "NONE")


def test_engine_updates_database():
    database = FakeDatabase()
    engine = DynamicResponseEngine(database)
    engine.add_rule(
        DynamicResponseRule(
            frame_index=3,
            response_index=0,
            interval_ms=10,
            provider=lambda _elapsed, count: f"000007E8 01 {count:02X}",
            checksum="NONE",
            name="counter",
        )
    )
    engine.start()
    time.sleep(0.055)
    engine.stop()

    assert len(database.updates) >= 4
    assert database.updates[0] == ("000007E8 01 00", "NONE", 3, 0)
    assert all(update[2:] == (3, 0) for update in database.updates)


def test_external_event_can_set_response_immediately():
    database = FakeDatabase()
    engine = DynamicResponseEngine(database)
    engine.set_response(
        frame_index=2,
        response_index=0,
        response="000007E8 08 03 41 0D 64 00 00 00",
        checksum="NONE",
    )
    assert database.updates == [
        ("000007E8 08 03 41 0D 64 00 00 00", "NONE", 2, 0)
    ]


def test_linear_byte_response():
    provider = linear_byte_response(
        "000007E8 08 03 41 0D {VALUE} 00 00 00", "{VALUE}", 0, 200, 2.0
    )
    assert " 00 " in provider(0.0, 0)
    assert " 64 " in provider(1.0, 1)
    assert " C8 " in provider(2.0, 2)
