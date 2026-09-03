"""Lớp ngôn ngữ CAPL: từ điển cú pháp, lexer, parser, analyzer.

Điểm vào chính cho phần UI (và cho engine ở Phase 2) là `compile_source()`.
"""

from __future__ import annotations

from pathlib import Path

from . import ast_nodes, builtins, keywords
from .analyzer import AnalysisResult, Analyzer, Symbol, analyze
from .diagnostics import Diagnostic, DiagnosticBag, Severity
from .includes import IncludedSymbols, resolve as resolve_includes
from .lexer import Lexer, Token, TokenKind, tokenize
from .parser import Parser, parse
from .snippets import SNIPPETS, Snippet

__all__ = [
    "ast_nodes", "builtins", "keywords",
    "AnalysisResult", "Analyzer", "Symbol", "analyze",
    "Diagnostic", "DiagnosticBag", "Severity",
    "IncludedSymbols", "resolve_includes",
    "Lexer", "Token", "TokenKind", "tokenize",
    "Parser", "parse",
    "SNIPPETS", "Snippet",
    "compile_source",
]


def compile_source(source: str, path: str = "",
                   search_paths: list[Path] | None = None) -> AnalysisResult:
    """Phân tích đầy đủ một file CAPL: lex → parse → nạp include → kiểm tra ngữ nghĩa.

    `path` là đường dẫn file đang phân tích; nó quyết định thư mục gốc để tìm
    các file `.cin` được `#include`. Truyền chuỗi rỗng nếu mã nguồn chưa có file
    trên đĩa — khi đó phần include sẽ bị bỏ qua.

    Hàm không bao giờ ném exception — mọi vấn đề đều nằm trong `result.diagnostics`.
    """
    parser = Parser(source, path)
    unit = parser.parse()

    base_dir: Path | None = None
    if path:
        candidate = Path(path)
        base_dir = candidate.parent if candidate.suffix else candidate
    included = resolve_includes(unit, base_dir, search_paths)
    return analyze(unit, parser.diagnostics, included)
