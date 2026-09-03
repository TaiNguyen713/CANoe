"""Thành phần UI liên quan tới CAPL: editor, tô màu, gợi ý mã, browser."""

from .browser import CaplBrowser
from .completer import CaplCompleter
from .editor import CaplEditor
from .highlighter import CaplHighlighter

__all__ = ["CaplBrowser", "CaplCompleter", "CaplEditor", "CaplHighlighter"]
