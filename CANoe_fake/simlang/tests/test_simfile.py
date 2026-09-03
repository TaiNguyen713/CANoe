"""Test cho simfile.py (M1) — tiêu chí: đọc file .sim thật, không mất dữ liệu.

Số liệu kỳ vọng dưới đây được xác nhận trực tiếp trên 3 fixture thật (chạy
parser rồi đối chiếu tay + grep độc lập), không phải số đoán — xem ghi chú
từng test.
"""

from __future__ import annotations

from pathlib import Path

from simlang.simfile import (
    BlankLine,
    CommentLine,
    ConfigLine,
    DataLine,
    ProtocolConfigLine,
    SizeDatabaseLine,
    UnknownLine,
    parse_sim_file,
    parse_sim_text,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _physical_line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_dtc_info_no_data_lost():
    path = FIXTURES / "DTC_info.sim"
    report = parse_sim_file(path)
    assert len(report.entries) == _physical_line_count(path) == 329


def test_dtc_info_data_lines_and_malformed():
    report = parse_sim_file(FIXTURES / "DTC_info.sim")
    assert len(report.data) == 187
    # Một dòng thật (line 304) có 9 byte dữ liệu nhưng khai DLC=8 — bất
    # thường THẬT trong file nguồn, không phải lỗi parser.
    assert len(report.malformed) == 1
    bad = report.malformed[0]
    assert bad.line_no == 304
    assert "dư" in bad.malformed_reason


def test_dtc_info_unknown_tokens_plus_marker():
    """34 dòng khớp `+xx` qua grep, nhưng 53 token +xx tổng cộng trong text
    thô (một số dòng có 2 token); 2 trong số đó nằm trong dòng bị comment
    (`//INFO_DATABASE = Res<3 ... +08 ... +00 ...` ở dòng 246) nên KHÔNG
    được tokenize — 51 token còn lại đều nằm trong DataLine sống."""
    report = parse_sim_file(FIXTURES / "DTC_info.sim")
    assert len(report.unknown_tokens) == 51
    assert all(tok.startswith("+") for _, tok in report.unknown_tokens)
    # dòng 246 bị comment ("//..."), không được đưa vào unknown_tokens
    assert not any(line_no == 246 for line_no, _ in report.unknown_tokens)


def test_dtc_info_config_and_comments_preserved():
    report = parse_sim_file(FIXTURES / "DTC_info.sim")
    assert len(report.config) == 18
    assert any(isinstance(e, CommentLine) for e in report.entries)
    assert any(isinstance(e, UnknownLine) for e in report.entries)  # banner "###..."


def test_can_default_config_only_no_data_lines():
    """CAN_default.sim (25 dòng vật lý) chỉ có config, không có INFO_DATABASE."""
    path = FIXTURES / "CAN_default.sim"
    report = parse_sim_file(path)
    assert len(report.entries) == _physical_line_count(path) == 25
    assert len(report.data) == 0
    assert len(report.config) == 18
    assert any(isinstance(e, SizeDatabaseLine) for e in report.entries)


def test_can_default_dev_single_token_can_id_form():
    """CAN_default_dev.sim dùng dạng CAN ID gộp 1 token (vd '000007DF')."""
    path = FIXTURES / "CAN_default_dev.sim"
    report = parse_sim_file(path)
    assert len(report.entries) == _physical_line_count(path) == 31
    assert len(report.data) == 4
    assert len(report.malformed) == 0
    first = report.data[0]
    assert first.can_id_raw == "000007DF"
    assert first.can_id == 0x000007DF
    assert first.dlc == 8
    assert [b.raw for b in first.data_bytes] == ["02", "10", "81", "00", "00", "00", "00", "00"]


def test_four_byte_can_id_form_also_accepted():
    """DTC_info.sim dùng dạng CAN ID tách 4 token (vd '00 00 07 DF')."""
    report = parse_sim_file(FIXTURES / "DTC_info.sim")
    first = report.data[0]
    assert first.can_id_raw == "00 00 07 DF"
    assert first.can_id == 0x000007DF


def test_can_id_with_wildcard_byte_not_malformed():
    """Functional addressing: byte cuối CAN ID là 'xx' (don't-care), không
    phải lỗi — can_id không tính được (None) nhưng dòng KHÔNG malformed."""
    report = parse_sim_text(
        "INFO_DATABASE = Req>3\t\t\t00 00 07 xx  08  02 10 90 xx xx xx xx xx\tNONE\t0\t0"
    )
    line = report.data[0]
    assert line.can_id is None
    assert line.can_id_bytes[3].wildcard is True
    assert line.malformed is False


def test_can_id_with_plus_marker_not_malformed():
    """Byte 'engine tự tính' (+08) trong CAN ID cũng không phải lỗi — chỉ
    ghi vào unknown_tokens, không đoán giá trị."""
    report = parse_sim_text(
        "INFO_DATABASE = Res<3\t\t\t00 00 07 +08  08  02 50 +00 00 00 00 00 00\tNONE\t0\t0"
    )
    line = report.data[0]
    assert line.can_id is None
    assert line.can_id_bytes[3].unknown_marker == "+"
    assert line.malformed is False
    assert (1, "+08") in report.unknown_tokens
    assert (1, "+00") in report.unknown_tokens


def test_q_dependent_prefix_at_start():
    report = parse_sim_text(
        "INFO_DATABASE = Req>1\t\t\tQ-- 000007E0 08 02 27 03 00 00 00 00 00\tNONE\t0\t0"
    )
    line = report.data[0]
    assert line.q_dependent is True
    assert line.can_id_raw == "000007E0"
    assert line.malformed is False


def test_q_dependent_not_at_start_is_flagged_not_applied():
    """Engine gốc cắt cứng 3 ký tự đầu bất kể Q-- nằm ở đâu (bug đã xác
    nhận) — simfile.py KHÔNG được tái tạo hành vi đó: nếu Q-- không ở đầu,
    đánh dấu malformed, không set q_dependent=True."""
    report = parse_sim_text(
        "INFO_DATABASE = Req>1\t\t\t000007E0 Q-- 08 02 27 03 00 00 00 00\tNONE\t0\t0"
    )
    line = report.data[0]
    assert line.q_dependent is False
    assert line.malformed is True
    assert "Q--" in line.malformed_reason


def test_l1_rotate_prefix():
    report = parse_sim_text(
        "INFO_DATABASE = Res<1\tt0\tr1\tl1 000007E8 08 05 42 04 00 80 00 00 00\t4\t0\t0"
    )
    line = report.data[0]
    assert line.rotate is True
    assert line.can_id_raw == "000007E8"


def test_broadcast_tag_has_no_relation_or_number():
    report = parse_sim_text(
        "INFO_DATABASE = Broadcast\tt100\tr2\t00000300 08 05 22 F1 90 00 00 00\tNONE\t0\t0"
    )
    line = report.data[0]
    assert line.kind == "Broadcast"
    assert line.relation == ""
    assert line.direction_num == ""


def test_short_line_degrades_gracefully_instead_of_crashing():
    """File thật lỗi (chỉ 5 trường TAB thay vì 7) không được làm crash toàn
    bộ — engine gốc bị IndexOutOfRangeException nuốt exception và load thất
    bại CẢ FILE (HUONG_DAN_FILE_SIM.md §11a); simfile.py phải chỉ đánh dấu
    đúng MỘT dòng malformed."""
    text = "INFO_DATABASE = Req>1\t\t\t000007DF 08 02 09\tNONE"
    report = parse_sim_text(text)
    assert len(report.entries) == 1
    line = report.entries[0]
    assert isinstance(line, DataLine)
    assert line.malformed is True
    assert "7" in line.malformed_reason  # "số trường TAB != 7"


def test_short_data_field_pads_with_none_instead_of_raising():
    """DLC khai 8 byte nhưng field chỉ có 3 byte thật — pad bằng None, đánh
    dấu malformed, KHÔNG raise exception."""
    text = "INFO_DATABASE = Req>1\t\t\t000007DF 08 02 09 02\tNONE\t0\t0"
    report = parse_sim_text(text)
    line = report.data[0]
    assert line.malformed is True
    assert line.dlc == 8
    assert len(line.data_bytes) == 8
    assert line.data_bytes[0].value == 0x02
    assert line.data_bytes[-1].value is None
    assert line.data_bytes[-1].raw == ""


def test_note_line_kept_verbatim():
    report = parse_sim_text("//NOTE: Odometer 40240 km")
    assert len(report.entries) == 1
    note = report.entries[0]
    assert note.text == "Odometer 40240 km"


def test_plain_comment_and_blank_line_not_dropped():
    report = parse_sim_text("// just a comment\n\n/also a comment (single slash)")
    kinds = [type(e).__name__ for e in report.entries]
    assert kinds == ["CommentLine", "BlankLine", "CommentLine"]


def test_config_line_parses_key_value():
    report = parse_sim_text("<config sw> TFRAME = 5")
    cfg = report.config[0]
    assert cfg.key == "TFRAME"
    assert cfg.value_raw == "5"


def test_protocol_config_directive():
    report = parse_sim_text("ProtocolConfig\tEnableAutoCANFC")
    line = report.entries[0]
    assert isinstance(line, ProtocolConfigLine)
    assert line.directive == "EnableAutoCANFC"


def test_size_database_captured_but_never_interpreted():
    report = parse_sim_text("SIZE_DATABASE = 5")
    line = report.entries[0]
    assert isinstance(line, SizeDatabaseLine)
    assert line.value_raw == "5"
