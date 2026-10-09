"""Test cho importer .sim → .can (M5, §8 của SPEC_SIMLANG_V2.md).

KHÔNG PHẢI roundtrip — kiểm tra (1) mọi khối TODO đúng theo bảng §8, (2)
output LUÔN là .can hợp lệ (feed lại qua parser), (3) không crash trên dòng
lỗi thật."""

from __future__ import annotations

from pathlib import Path

from simlang.importer import import_sim_to_can
from simlang.parser import parse

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _assert_reparses(can_source: str) -> None:
    parse(can_source)  # ném SimlangSyntaxError nếu không hợp lệ


def test_synthetic_fixture_hits_every_todo_rule_exactly_once():
    result = import_sim_to_can(FIXTURES / "synthetic_todo_cases.sim")
    assert result.todo_count == {
        "q_dependent": 1,
        "rotating": 1,
        "duplicate": 1,
        "unknown_token": 1,
    }
    _assert_reparses(result.can_source)


def test_synthetic_fixture_normal_pair_has_no_todo():
    result = import_sim_to_can(FIXTURES / "synthetic_todo_cases.sim")
    can_file = parse(result.can_source)
    first = can_file.on_requests[0]
    assert (first.can_id, first.service, first.pid) == (0x7E0, 0x10, 0x03)


def test_synthetic_fixture_q_dependent_block_has_todo_comment():
    result = import_sim_to_can(FIXTURES / "synthetic_todo_cases.sim")
    assert "TODO: Q-- — rewrite as a stateful handler" in result.can_source


def test_synthetic_fixture_rotating_block_lists_all_alternatives_as_comments():
    result = import_sim_to_can(FIXTURES / "synthetic_todo_cases.sim")
    assert "TODO: l1 (rotating)" in result.can_source
    assert "alt: 0x41, 0x0C, 0x1B, 0x40" in result.can_source
    assert "alt: 0x41, 0x0C, 0x1C, 0x88" in result.can_source


def test_synthetic_fixture_duplicate_request_emits_both_blocks():
    result = import_sim_to_can(FIXTURES / "synthetic_todo_cases.sim")
    can_file = parse(result.can_source)
    signatures = [(r.can_id, r.service, r.pid) for r in can_file.on_requests]
    assert signatures.count((0x7DF, 0x01, 0x0C)) == 2
    assert "TODO: duplicate request, needs disambiguation logic" in result.can_source


def test_synthetic_fixture_unknown_marker_becomes_placeholder_with_todo():
    result = import_sim_to_can(FIXTURES / "synthetic_todo_cases.sim")
    assert "0x00 /* TODO: unknown token '^A7'" in result.can_source
    _assert_reparses(result.can_source)  # placeholder vẫn phải hợp lệ cú pháp


def test_synthetic_fixture_malformed_line_does_not_crash_import():
    """Dòng lỗi (5 trường TAB) không được làm crash toàn bộ import — khác
    hẳn engine gốc, nơi 1 dòng lỗi làm CẢ FILE không load được (§11a)."""
    result = import_sim_to_can(FIXTURES / "synthetic_todo_cases.sim")
    _assert_reparses(result.can_source)


def test_config_header_becomes_load_static_call():
    result = import_sim_to_can(FIXTURES / "synthetic_todo_cases.sim")
    can_file = parse(result.can_source)
    assert can_file.on_start is not None
    call = can_file.on_start.body.statements[0].expr
    assert call.name == "loadStatic"
    assert call.args[0].value == "synthetic_todo_cases.sim"


def test_real_fixture_dtc_info_reparses_and_flags_functional_wildcards():
    """DTC_info.sim có nhiều request functional-broadcast (CAN ID chứa `xx`)
    — importer PHẢI đánh dấu 'không dịch được', không được đoán giá trị."""
    result = import_sim_to_can(FIXTURES / "DTC_info.sim")
    _assert_reparses(result.can_source)
    assert result.todo_count.get("unresolvable", 0) > 0
    assert "CAN ID không cụ thể" in result.can_source or "không phải Single Frame" in result.can_source


def test_real_fixture_can_default_dev_two_simple_pairs_no_todo():
    result = import_sim_to_can(FIXTURES / "CAN_default_dev.sim")
    can_file = parse(result.can_source)
    assert len(can_file.on_requests) == 2
    assert result.todo_count == {}


def test_real_fixture_can_default_config_only_no_requests():
    result = import_sim_to_can(FIXTURES / "CAN_default.sim")
    can_file = parse(result.can_source)
    assert can_file.on_requests == []
    assert can_file.on_start is not None


def test_every_generated_exchange_block_across_all_fixtures_reparses():
    for name in ["DTC_info.sim", "CAN_default.sim", "CAN_default_dev.sim", "synthetic_todo_cases.sim"]:
        result = import_sim_to_can(FIXTURES / name)
        _assert_reparses(result.can_source)
