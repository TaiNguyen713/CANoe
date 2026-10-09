"""`.sim` → `.can` (§8 của SPEC_SIMLANG_V2.md).

MỘT CHIỀU, KHÔNG PHẢI ROUNDTRIP — khác hẳn `decompile` của spec v1 (đã bị
thay thế). Không cần bảo toàn thứ tự hay khớp bit-for-bit; đây là công cụ
trích xuất dữ liệu để người dùng tự viết tiếp thành handler có trạng thái.

Nguyên tắc xuyên suốt (lặp lại từ cả 2 tài liệu spec): gặp ký hiệu/tình
huống chưa hiểu (`Q--`, `l1`, `^`/`+xx`, request trùng, `Broadcast`, CAN ID
không cụ thể...) thì KHÔNG đoán — giữ nguyên thông tin đã có, sinh code vẫn
hợp lệ cú pháp (`// TODO: ...` phía trên khối `on request` bình thường),
không bao giờ bỏ qua âm thầm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import simfile
from .runtime.isotp import ff_length


@dataclass
class ImportResult:
    can_source: str
    todo_count: dict[str, int] = field(default_factory=dict)

    def _bump(self, key: str) -> None:
        self.todo_count[key] = self.todo_count.get(key, 0) + 1


def _reassemble_logical(lines: list[simfile.DataLine]) -> list[simfile.ByteToken] | None:
    """Ghép các dòng (1 Req hoặc chuỗi Res đa khung) thành payload logic —
    tương tự `runtime.isotp.Reassembler` nhưng làm việc trên `ByteToken`
    (giữ nguyên wildcard/unknown_marker) thay vì `bytes` cụ thể, vì dữ liệu
    import có thể chứa `xx`/`^`/`+xx` không thể ép về số nguyên."""
    if not lines or not lines[0].data_bytes:
        return None
    first_pci = lines[0].data_bytes[0]
    if first_pci.value is None:
        return None  # PCI không cụ thể — không biết đây là SF hay FF, bỏ qua an toàn
    frame_type = (first_pci.value >> 4) & 0x0F

    if frame_type == 0x0:  # Single Frame
        length = first_pci.value & 0x0F
        return lines[0].data_bytes[1:1 + length]

    if frame_type == 0x1:  # First Frame + (các) Consecutive Frame
        if len(lines[0].data_bytes) < 2 or lines[0].data_bytes[1].value is None:
            return None
        length = ff_length(first_pci.value, lines[0].data_bytes[1].value)
        payload = list(lines[0].data_bytes[2:8])
        for line in lines[1:]:
            if not line.data_bytes or line.data_bytes[0].value is None:
                return None
            payload.extend(line.data_bytes[1:8])
        return payload[:length] if len(payload) >= length else None

    return None  # PCI dạng khác (vd chính nó là FC) — không phải payload logic


def _byte_literal(tok: simfile.ByteToken, result: ImportResult) -> str:
    if tok.value is not None:
        return f"0x{tok.value:02X}"
    result._bump("unknown_token")
    marker = tok.raw
    return f"0x00 /* TODO: unknown token {marker!r} — value not translated, verify against real hardware/log */"


def _request_header(can_id: int, payload: list[simfile.ByteToken]) -> str | None:
    if not payload or payload[0].value is None:
        return None  # service không cụ thể — không dịch được
    service = payload[0].value
    header = f"on request 0x{can_id:X} service 0x{service:02X}"
    if len(payload) > 1 and payload[1].value is not None:
        header += f" pid 0x{payload[1].value:02X}"
    return header


def import_sim_to_can(path: str | Path) -> ImportResult:
    report = simfile.parse_sim_file(path)
    exchanges = simfile.group_exchanges(report)
    result = ImportResult(can_source="")
    lines_out: list[str] = []

    lines_out.append(f'// Sinh tự động bằng `simlang import` từ {Path(path).name}')
    lines_out.append('// KHÔNG PHẢI roundtrip — xem lại mọi khối trước khi dùng thật.')
    lines_out.append("")
    lines_out.append("on start {")
    lines_out.append(f'    loadStatic("{Path(path).name}");')
    lines_out.append("}")
    lines_out.append("")

    seen_signatures: dict[tuple[int, int, int | None], int] = {}

    for ex in exchanges:
        if ex.request is None:
            # Broadcast: không có on-event nào diễn đạt "phát tuần hoàn
            # không cần request" — đánh dấu, không đoán cú pháp mới (spec
            # v2 không có builtin lặp theo thời gian ngoài setTimer trong
            # handler đã tồn tại, nên gợi ý viết tay bằng on start+setTimer).
            result._bump("broadcast")
            can_id_txt = ex.responses[0].can_id_raw if ex.responses else "?"
            lines_out.append(
                f"// TODO: Broadcast {can_id_txt} — không có on-event nào ánh xạ bản tin phát "
                f"tuần hoàn không cần request; viết lại bằng on start + setTimer"
            )
            lines_out.append("")
            continue

        if ex.request.can_id is None:
            result._bump("unresolvable")
            lines_out.append(
                f"// TODO: không dịch được — CAN ID không cụ thể ({ex.request.can_id_raw!r})"
            )
            lines_out.append("")
            continue

        req_payload = _reassemble_logical([ex.request])
        header = _request_header(ex.request.can_id, req_payload) if req_payload is not None else None
        if header is None:
            result._bump("unresolvable")
            lines_out.append(
                f"// TODO: không dịch được — request không phải Single Frame hoặc service "
                f"không cụ thể (CAN ID 0x{ex.request.can_id:X})"
            )
            lines_out.append("")
            continue

        signature = (
            ex.request.can_id,
            req_payload[0].value,
            req_payload[1].value if len(req_payload) > 1 else None,
        )
        is_duplicate = signature in seen_signatures
        seen_signatures[signature] = seen_signatures.get(signature, 0) + 1

        todo_lines: list[str] = []
        if ex.request.q_dependent:
            result._bump("q_dependent")
            todo_lines.append("// TODO: Q-- — rewrite as a stateful handler")
        if is_duplicate:
            result._bump("duplicate")
            todo_lines.append("// TODO: duplicate request, needs disambiguation logic")

        rotating = [r for r in ex.responses if r.rotate]
        primary_responses = [ex.responses[0]] if ex.responses else []
        alt_comments: list[str] = []
        if rotating:
            result._bump("rotating")
            todo_lines.append("// TODO: l1 (rotating) — rewrite using a state variable")
            for alt in ex.responses[1:]:
                alt_payload = _reassemble_logical([alt])
                if alt_payload is not None:
                    alt_bytes = ", ".join(_byte_literal(b, result) for b in alt_payload)
                    alt_comments.append(f"//   alt: {alt_bytes}")

        for t in todo_lines:
            lines_out.append(t)
        lines_out.append(f"{header} {{")
        if ex.responses:
            resp_payload = _reassemble_logical(primary_responses)
            if resp_payload is None:
                lines_out.append("    // TODO: không dịch được — response không phải Single Frame")
            else:
                byte_list = ", ".join(_byte_literal(b, result) for b in resp_payload)
                lines_out.append(f"    output({byte_list});")
        else:
            lines_out.append("    // (không có response tương ứng trong file gốc)")
        for c in alt_comments:
            lines_out.append(c)
        lines_out.append("}")
        lines_out.append("")

    result.can_source = "\n".join(lines_out) + "\n"
    return result
