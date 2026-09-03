"""Giải quyết chỉ thị `#include` trong khối `includes { }` của CAPL.

Trình biên dịch CAPL thật nạp nội dung file `.cin` trước khi phân tích node, nên
hàm khai báo trong `.cin` phải được xem là đã tồn tại. Module này làm đúng việc
đó: đọc đệ quy các file được include, thu thập tên hàm / biến toàn cục / kiểu,
rồi đưa cho analyzer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import ast_nodes as ast

#: `#include "Lib.cin"` hoặc `#include <Lib.cin>`
_INCLUDE_RE = re.compile(r'#\s*include\s*[<"]([^>"]+)[>"]')

MAX_DEPTH = 8


@dataclass
class IncludedSymbols:
    """Ký hiệu gom được từ toàn bộ cây include."""
    functions: dict[str, ast.FunctionDecl] = field(default_factory=dict)
    globals: dict[str, ast.VarDecl] = field(default_factory=dict)
    types: set[str] = field(default_factory=set)
    resolved: list[Path] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def merge(self, other: "IncludedSymbols") -> None:
        self.functions.update(other.functions)
        self.globals.update(other.globals)
        self.types |= other.types
        self.resolved.extend(other.resolved)
        self.missing.extend(other.missing)


def directive_target(directive: str) -> str | None:
    """Lấy tên file từ một dòng `#include`."""
    match = _INCLUDE_RE.search(directive)
    return match.group(1).strip() if match else None


def resolve(unit: ast.CaplFile, base_dir: Path | None,
            search_paths: list[Path] | None = None) -> IncludedSymbols:
    """Đọc đệ quy các file được include và trả về ký hiệu của chúng."""
    result = IncludedSymbols()
    if base_dir is None:
        return result
    roots = [base_dir] + list(search_paths or [])
    _collect(unit, roots, result, seen=set(), depth=0)
    return result


def _collect(unit: ast.CaplFile, roots: list[Path], out: IncludedSymbols,
             seen: set[Path], depth: int) -> None:
    if unit.includes is None or depth >= MAX_DEPTH:
        return

    # tránh vòng lặp import: `parse` được gọi trễ để không tạo import vòng
    from .parser import Parser

    for directive in unit.includes.directives:
        target = directive_target(directive)
        if not target:
            continue
        path = _locate(target, roots)
        if path is None:
            out.missing.append(target)
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            source = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            out.missing.append(target)
            continue

        parser = Parser(source, str(resolved))
        included = parser.parse()
        out.resolved.append(resolved)

        for fn in included.functions:
            out.functions.setdefault(fn.name, fn)
        for decl in included.global_variables():
            out.globals.setdefault(decl.name, decl)
        out.types |= {s.name for s in included.structs}
        out.types |= {e.name for e in included.enums}
        for enum in included.enums:
            for member in enum.members:
                out.globals.setdefault(
                    member.name,
                    ast.VarDecl(member.line, member.column,
                                type_name="enum", name=member.name, is_const=True),
                )

        # file .cin có thể include tiếp file khác
        nested_roots = [resolved.parent] + roots
        _collect(included, nested_roots, out, seen, depth + 1)


def _locate(target: str, roots: list[Path]) -> Path | None:
    candidate = Path(target)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    for root in roots:
        path = root / target
        if path.exists():
            return path
        # CANoe cho phép bỏ phần mở rộng
        for suffix in (".cin", ".can"):
            alt = root / (target + suffix)
            if alt.exists():
                return alt
    return None
