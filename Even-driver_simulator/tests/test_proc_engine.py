from types import SimpleNamespace

import pytest

from engine.proc_engine import ProcController, ProcProgram, ProcSyntaxError, frames_match


class FakeDatabase:
    def __init__(self):
        self.updates = []

    def OBDDb_UpdateRes(self, response, checksum, frame_index, response_index):
        self.updates.append((response, checksum, frame_index, response_index))


def write_proc(tmp_path, content):
    path = tmp_path / "scenario.proc"
    path.write_text(content, encoding="utf-8")
    return path


def test_frame_match_allows_display_prefix_and_wildcards():
    assert frames_match("000007DF 08 02 01 XX", "[RX] 000007DF 08 02 01 0C")
    assert not frames_match("000007DF 08 02 01 0D", "[RX] 000007DF 08 02 01 0C")


def test_two_step_same_command_changes_next_response(tmp_path):
    path = write_proc(
        tmp_path,
        """
        SIM "base.sim"
        START A1
        BLOCK A1
          TX 000007DF 08 02 01 0C
          RX 000007E8 08 03 41 0C 01 00
          NEXT A2
        END
        BLOCK A2
          TX 000007DF 08 02 01 0C
          RX 000007E8 08 03 41 0C 00 01
          NEXT A2
        END
        """,
    )
    program = ProcProgram.load(path)
    database = FakeDatabase()
    controller = ProcController(program, database, checksum="NONE")
    entries = [
        SimpleNamespace(req="000007DF 08 02 01 0C", res_s=["original"])
    ]
    controller.bind(entries)
    assert database.updates[-1][0].endswith("01 00")

    transition = controller.handle_tx("12:00 [RX] 000007DF 08 02 01 0C")
    assert transition.previous == "A1"
    assert transition.current == "A2"
    assert database.updates[-1][0].endswith("00 01")


def test_ambiguous_request_requires_frame_index(tmp_path):
    path = write_proc(
        tmp_path,
        """
        START A
        BLOCK A
          TX 000007DF 08 XX
          RX 000007E8 08 00
        END
        """,
    )
    controller = ProcController(ProcProgram.load(path), FakeDatabase(), "NONE")
    entries = [
        SimpleNamespace(req="000007DF 08 01", res_s=["a"]),
        SimpleNamespace(req="000007DF 08 02", res_s=["b"]),
    ]
    with pytest.raises(ValueError, match="FRAME_INDEX"):
        controller.bind(entries)


def test_unknown_next_is_rejected(tmp_path):
    path = write_proc(
        tmp_path,
        """
        START A
        BLOCK A
          TX AA
          RX BB
          NEXT MISSING
        END
        """,
    )
    with pytest.raises(ProcSyntaxError, match="unknown block"):
        ProcProgram.load(path)
