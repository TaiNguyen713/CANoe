"""`msTimer` — mỗi handle gắn với một callback (đăng ký một lần lúc
`register()` sinh ra bởi codegen), `set()` có thể gọi lại nhiều lần (mỗi lần
huỷ lịch cũ rồi đặt lại) — đây là cách `on timer rpmTimer { ...;
setTimer(rpmTimer, 100); }` tự tái lập lịch an toàn từ bên trong callback
của chính nó (xem ví dụ §5.1)."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable


class TimerHandle:
    def __init__(self, name: str) -> None:
        self.name = name
        self._task: asyncio.Task | None = None

    def __repr__(self) -> str:
        return f"TimerHandle({self.name!r})"


class TimerManager:
    def __init__(self) -> None:
        self._callbacks: dict[str, Callable[..., Awaitable[None]]] = {}

    def on_expire(self, name: str, fn: Callable[..., Awaitable[None]]) -> None:
        self._callbacks[name] = fn

    def set(self, handle: TimerHandle, ms: int, ctx) -> None:
        self.cancel(handle)
        handle._task = asyncio.create_task(self._fire_after(handle, ms, ctx))

    def cancel(self, handle: TimerHandle) -> None:
        if handle._task is not None and not handle._task.done():
            handle._task.cancel()
        handle._task = None

    async def _fire_after(self, handle: TimerHandle, ms: int, ctx) -> None:
        await asyncio.sleep(ms / 1000)
        cb = self._callbacks.get(handle.name)
        if cb is not None:
            await cb(ctx)
