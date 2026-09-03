"""Parser cho file `.sim` (định dạng đích của engine SimulatorInterface.dll).

Tham chiếu định dạng: HUONG_DAN_FILE_SIM.md ở gốc repo. Nguyên tắc cốt lõi:
KHÔNG BAO GIỜ làm mất dữ liệu — mỗi dòng vật lý trong file luôn ánh xạ ra
đúng một `SimLine` trong `ParseReport.entries`, kể cả khi dòng đó không nhận
dạng được (rơi vào `UnknownLine`) hoặc dữ liệu bị lỗi định dạng (rơi vào
`DataLine(malformed=True)` thay vì bị bỏ qua hay làm crash cả file, khác với
hành vi gốc của engine — xem §11a của HUONG_DAN_FILE_SIM.md).

Ký hiệu `^xx` (byte engine tự tính) và `+xx` (quan sát được trong file thật,
dùng cho functional addressing — chưa tài liệu nào giải thích) được xử lý
GIỐNG HỆT NHAU: giữ nguyên nguyên văn, ghi vào `ParseReport.unknown_tokens`,
không bao giờ diễn giải giá trị.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Các loại dòng
# ---------------------------------------------------------------------------


@dataclass
class ByteToken:
    raw: str
    value: int | None = None
    wildcard: bool = False
    unknown_marker: str | None = None  # "^" hoặc "+"


@dataclass
class DataLine:
    kind: str  # "Req" | "Res" | "Broadcast"
    relation: str  # "<" | ">" | ""
    direction_num: str  # vd "1","3","14" — KHÔNG DIỄN GIẢI, giữ nguyên
    delay_raw: str  # field [1], vd "t500" hoặc ""
    repeat_raw: str  # field [2]
    q_dependent: bool
    rotate: bool
    can_id: int | None  # None nếu bất kỳ byte nào trong 4 byte là wildcard/unknown_marker
    can_id_raw: str
    can_id_bytes: list[ByteToken]
    dlc: int | None
    dlc_raw: str
    data_bytes: list[ByteToken]
    checksum: str
    poly: str
    unused: str
    line_no: int
    raw: str
    malformed: bool = False
    malformed_reason: str = ""


@dataclass
class ConfigLine:
    key: str
    value_raw: str
    line_no: int
    raw: str


@dataclass
class NoteLine:
    text: str
    line_no: int
    raw: str


@dataclass
class CommentLine:
    text: str
    line_no: int
    raw: str


@dataclass
class ProtocolConfigLine:
    directive: str
    line_no: int
    raw: str


@dataclass
class SizeDatabaseLine:
    value_raw: str
    line_no: int
    raw: str


@dataclass
class BlankLine:
    line_no: int
    raw: str


@dataclass
class UnknownLine:
    line_no: int
    raw: str


SimLine = (
    ConfigLine
    | NoteLine
    | CommentLine
    | ProtocolConfigLine
    | SizeDatabaseLine
    | DataLine
    | BlankLine
    | UnknownLine
)


@dataclass
class ParseReport:
    source: str
    entries: list[SimLine] = field(default_factory=list)
    unknown_tokens: list[tuple[int, str]] = field(default_factory=list)

    @property
    def data(self) -> list[DataLine]:
        return [e for e in self.entries if isinstance(e, DataLine)]

    @property
    def malformed(self) -> list[DataLine]:
        return [d for d in self.data if d.malformed]

    @property
    def notes(self) -> list[NoteLine]:
        return [e for e in self.entries if isinstance(e, NoteLine)]

    @property
    def config(self) -> list[ConfigLine]:
        return [e for e in self.entries if isinstance(e, ConfigLine)]


@dataclass
class Exchange:
    """Một request tĩnh và (các) response đi kèm — dùng chung bởi
    `runtime/builtins.py::StaticTable` (tra bảng tĩnh lúc chạy) và
    `importer.py` (M5, sinh khối `on request`). `request` là None cho
    `Broadcast` (không có request kích hoạt)."""

    request: DataLine | None
    responses: list[DataLine] = field(default_factory=list)


def group_exchanges(report: ParseReport) -> list[Exchange]:
    """Gom các dòng `Req`/`Broadcast` + các dòng `Res` theo SAU nó (tới khi
    gặp `Req`/`Broadcast` tiếp theo) thành từng `Exchange`, theo đúng thứ tự
    xuất hiện trong file. `Res` mồ côi (không có `Req` trước) bị bỏ qua an
    toàn, không raise."""
    exchanges: list[Exchange] = []
    current: Exchange | None = None
    for line in report.data:
        if line.kind in ("Req", "Broadcast"):
            current = Exchange(request=line if line.kind == "Req" else None)
            if line.kind == "Broadcast":
                current.responses.append(line)
            exchanges.append(current)
        elif line.kind == "Res" and current is not None:
            current.responses.append(line)
    return exchanges


# ---------------------------------------------------------------------------
# Tokenizing field [3] ("[Q--] [l1] <CANID> <DLC> <byte>...")
# ---------------------------------------------------------------------------

_HEX8 = re.compile(r"^[0-9A-Fa-f]{8}$")
_HEX_BYTE = re.compile(r"^[0-9A-Fa-f]{1,2}$")
_TAG_RE = re.compile(r"^INFO_DATABASE\s*=\s*(Req|Res|Broadcast)\s*([<>]?)\s*(\d*)\s*$", re.IGNORECASE)


def _classify_byte_token(tok: str) -> ByteToken:
    """Phân loại một token byte đơn: hex cụ thể / wildcard xx / marker ^ /
    marker + (^ và + được xử lý GIỐNG HỆT NHAU — xem docstring module)."""
    if tok.upper() == "XX":
        return ByteToken(raw=tok, wildcard=True)
    if tok.startswith("^"):
        return ByteToken(raw=tok, unknown_marker="^")
    if tok.startswith("+"):
        return ByteToken(raw=tok, unknown_marker="+")
    if _HEX_BYTE.match(tok):
        return ByteToken(raw=tok, value=int(tok, 16))
    return ByteToken(raw=tok)  # không nhận dạng được — caller tự quyết định có coi là lỗi hay không


def _looks_like_byte_token(tok: str) -> bool:
    return bool(_HEX_BYTE.match(tok)) or tok.upper() == "XX" or tok.startswith("^") or tok.startswith("+")


def _tokenize_data_field(
    raw_field: str,
) -> tuple[bool, bool, int | None, str, list[ByteToken], int | None, str, list[ByteToken], list[str]]:
    """Trả về (q_dependent, rotate, can_id, can_id_raw, can_id_bytes, dlc, dlc_raw, data_bytes, reasons).

    Lưu ý quan trọng rút ra từ dữ liệu thật (DTC_info.sim): nhóm 4-byte CAN ID
    không phải lúc nào cũng là 4 byte hex cụ thể — có thể chứa `xx` (wildcard
    địa chỉ ECU trong functional addressing, vd `00 00 07 xx`) hoặc `+xx`
    (byte engine "tự tính = request + 8", vd `00 00 07 +08`). Nhận diện nhóm
    4-byte bằng `_looks_like_byte_token` (chấp nhận cả ba dạng) thay vì chỉ
    hex thuần — nếu không, những dòng này bị đánh nhầm là malformed.
    """
    reasons: list[str] = []
    working = raw_field.lstrip()

    q_dependent = False
    upper = working.upper()
    if upper.startswith("Q--") or upper.startswith("Q00"):
        q_dependent = True
        working = working[3:].lstrip()
    elif "Q--" in upper or "Q00" in upper:
        # xuất hiện nhưng không ở đầu — KHÔNG áp dụng (xem HUONG_DAN §5/§11d:
        # engine gốc cắt cứng 3 ký tự bất kể vị trí, đây là bug đã xác nhận,
        # không tái tạo lại hành vi đó).
        reasons.append("Q--/Q00 xuất hiện nhưng không ở đầu trường — không áp dụng (xem engine bug §11d)")

    rotate = False
    tokens = working.split()
    if tokens and tokens[0].lower() == "l1":
        rotate = True
        tokens = tokens[1:]

    idx = 0
    can_id: int | None = None
    can_id_raw = ""
    can_id_bytes: list[ByteToken] = []
    if idx < len(tokens) and _HEX8.match(tokens[idx]):
        raw8 = tokens[idx]
        can_id_bytes = [ByteToken(raw=raw8[i:i + 2], value=int(raw8[i:i + 2], 16)) for i in range(0, 8, 2)]
        can_id_raw = raw8
        can_id = int(raw8, 16)
        idx += 1
    elif idx + 3 < len(tokens) and all(_looks_like_byte_token(t) for t in tokens[idx:idx + 4]):
        group = tokens[idx:idx + 4]
        can_id_bytes = [_classify_byte_token(t) for t in group]
        can_id_raw = " ".join(group)
        if all(b.value is not None for b in can_id_bytes):
            can_id = int("".join(f"{b.value:02X}" for b in can_id_bytes), 16)
        idx += 4
    else:
        reasons.append("không nhận dạng được token CAN ID")
        if idx < len(tokens):
            can_id_raw = tokens[idx]
            idx += 1

    # Lưu ý: CAN ID có byte wildcard (`xx`, functional addressing) hoặc
    # unknown-marker (`^`/`+xx`, byte engine tự tính) là dữ liệu THẬT, không
    # phải lỗi — `can_id` chỉ đơn giản là None trong trường hợp đó (không
    # tính được số nguyên đầy đủ), KHÔNG được thêm vào `reasons`/malformed.

    dlc: int | None = None
    dlc_raw = ""
    if idx < len(tokens):
        dlc_raw = tokens[idx]
        try:
            dlc = int(dlc_raw, 10)
        except ValueError:
            reasons.append(f"DLC không phải số: {dlc_raw!r}")
        idx += 1
    else:
        reasons.append("thiếu trường DLC")

    data_bytes: list[ByteToken] = []
    remaining = tokens[idx:]
    take = dlc if dlc is not None else len(remaining)
    for i in range(take):
        if i < len(remaining):
            tok = remaining[i]
            bt = _classify_byte_token(tok)
            data_bytes.append(bt)
            if bt.value is None and not bt.wildcard and bt.unknown_marker is None:
                reasons.append(f"byte dữ liệu không nhận dạng được: {tok!r}")
        else:
            data_bytes.append(ByteToken(raw=""))
            reasons.append("thiếu byte dữ liệu so với DLC khai báo")

    if dlc is not None and len(remaining) > dlc:
        reasons.append(f"dư {len(remaining) - dlc} token trong trường dữ liệu so với DLC khai báo")

    return q_dependent, rotate, can_id, can_id_raw, can_id_bytes, dlc, dlc_raw, data_bytes, reasons


def _parse_data_line(fields: list[str], line_no: int, raw: str) -> DataLine:
    reasons: list[str] = []
    if len(fields) != 7:
        reasons.append(f"số trường TAB != 7 (thấy {len(fields)})")
    padded = (fields + [""] * 7)[:7]

    m = _TAG_RE.match(padded[0].strip())
    if m:
        kind, relation, direction_num = m.group(1), m.group(2), m.group(3)
    else:
        kind, relation, direction_num = padded[0].strip(), "", ""
        reasons.append(f"không khớp mẫu tag dòng dữ liệu: {padded[0]!r}")

    q_dependent, rotate, can_id, can_id_raw, can_id_bytes, dlc, dlc_raw, data_bytes, tok_reasons = (
        _tokenize_data_field(padded[3])
    )
    reasons.extend(tok_reasons)

    return DataLine(
        kind=kind,
        relation=relation,
        direction_num=direction_num,
        delay_raw=padded[1],
        repeat_raw=padded[2],
        q_dependent=q_dependent,
        rotate=rotate,
        can_id=can_id,
        can_id_raw=can_id_raw,
        can_id_bytes=can_id_bytes,
        dlc=dlc,
        dlc_raw=dlc_raw,
        data_bytes=data_bytes,
        checksum=padded[4],
        poly=padded[5],
        unused=padded[6],
        line_no=line_no,
        raw=raw,
        malformed=bool(reasons),
        malformed_reason="; ".join(reasons),
    )


# ---------------------------------------------------------------------------
# Phân loại từng dòng vật lý
# ---------------------------------------------------------------------------


def parse_sim_text(text: str, source: str = "<string>") -> ParseReport:
    report = ParseReport(source=source)
    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()

        if stripped == "":
            report.entries.append(BlankLine(line_no=line_no, raw=raw))
            continue

        if stripped.upper().startswith("//NOTE:"):
            report.entries.append(
                NoteLine(text=stripped[len("//NOTE:"):].strip(), line_no=line_no, raw=raw)
            )
            continue

        if stripped.startswith("/"):
            report.entries.append(CommentLine(text=stripped, line_no=line_no, raw=raw))
            continue

        if stripped.lower().startswith("<config sw>"):
            rest = stripped[len("<config sw>"):].strip()
            if "=" in rest:
                key, _, value = rest.partition("=")
                key, value = key.strip(), value.strip()
            else:
                key, value = rest, ""
            report.entries.append(ConfigLine(key=key, value_raw=value, line_no=line_no, raw=raw))
            continue

        if stripped.upper().startswith("SIZE_DATABASE"):
            _, _, value = stripped.partition("=")
            report.entries.append(
                SizeDatabaseLine(value_raw=value.strip(), line_no=line_no, raw=raw)
            )
            continue

        if stripped.upper().startswith("PROTOCOLCONFIG"):
            parts = stripped.split()
            directive = parts[-1] if len(parts) > 1 else ""
            report.entries.append(
                ProtocolConfigLine(directive=directive, line_no=line_no, raw=raw)
            )
            continue

        if stripped.upper().startswith("INFO_DATABASE"):
            fields = raw.split("\t")
            data_line = _parse_data_line(fields, line_no, raw)
            report.entries.append(data_line)
            for tok in (*data_line.can_id_bytes, *data_line.data_bytes):
                if tok.unknown_marker is not None:
                    report.unknown_tokens.append((line_no, tok.raw))
            continue

        report.entries.append(UnknownLine(line_no=line_no, raw=raw))

    return report


def parse_sim_file(path: str | Path, encoding: str = "utf-8") -> ParseReport:
    p = Path(path)
    try:
        text = p.read_text(encoding=encoding)
    except UnicodeDecodeError:
        text = p.read_text(encoding="latin-1")
    return parse_sim_text(text, source=str(p))
