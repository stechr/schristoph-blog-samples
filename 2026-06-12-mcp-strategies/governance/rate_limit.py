"""rate_limit.py — Per-tool rate limiting with standard headers + load shedding.

The governance pillar recommends rate limiting primarily at the MCP-server
level, per-tool limits to protect downstream resources, and returning the limit
state in HTTP headers so agents can self-manage retries:

    X-RateLimit-Limit: 100
    X-RateLimit-Remaining: 45
    X-RateLimit-Reset: 1640995200

It also recommends load shedding for general overload not attributable to one
caller. This module implements both with no real AWS resources — an in-memory
fixed-window limiter you can run and watch.

Run:
    python rate_limit.py
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class WindowState:
    count: int = 0
    window_start: float = field(default_factory=time.time)


@dataclass
class PerToolRateLimiter:
    """Fixed-window per-tool limiter.

    `limits` maps a tool name to its max calls per `window_seconds`. The paper's
    rule: if a tool fans out to several downstream APIs, set its limit to the
    LOWEST allowed by those APIs. `global_limit` is the load-shedding ceiling
    across all tools combined.
    """
    limits: dict[str, int]
    window_seconds: float = 1.0
    global_limit: int | None = None
    _state: dict[str, WindowState] = field(default_factory=dict)
    _global: WindowState = field(default_factory=WindowState)

    def _roll(self, st: WindowState, now: float) -> None:
        if now - st.window_start >= self.window_seconds:
            st.count = 0
            st.window_start = now

    def check(self, tool: str, now: float | None = None) -> tuple[bool, dict[str, int], str]:
        """Return (allowed, headers, reason)."""
        now = time.time() if now is None else now

        # Load shedding first: global overload is not one caller's fault.
        if self.global_limit is not None:
            self._roll(self._global, now)
            if self._global.count >= self.global_limit:
                reset = int(self._global.window_start + self.window_seconds)
                return False, self._headers(self.global_limit, 0, reset), \
                    "load-shed (global limit)"

        limit = self.limits.get(tool)
        if limit is None:
            return True, {}, "no per-tool limit"

        st = self._state.setdefault(tool, WindowState(window_start=now))
        self._roll(st, now)
        reset = int(st.window_start + self.window_seconds)

        if st.count >= limit:
            return False, self._headers(limit, 0, reset), "per-tool limit"

        st.count += 1
        if self.global_limit is not None:
            self._global.count += 1
        remaining = limit - st.count
        return True, self._headers(limit, remaining, reset), "ok"

    @staticmethod
    def _headers(limit: int, remaining: int, reset: int) -> dict[str, int]:
        return {"X-RateLimit-Limit": limit,
                "X-RateLimit-Remaining": remaining,
                "X-RateLimit-Reset": reset}


def _demo() -> None:
    # github_issue_create is limited to 3/sec (pretend the downstream API caps
    # there). github_issue_get is more generous at 5/sec.
    limiter = PerToolRateLimiter(
        limits={"github_issue_create": 3, "github_issue_get": 5},
        window_seconds=1.0,
        global_limit=6,  # load-shed ceiling across all tools
    )

    print("Calling github_issue_create 5 times in one window "
          "(per-tool limit = 3):\n")
    base = time.time()
    for i in range(1, 6):
        allowed, headers, reason = limiter.check("github_issue_create", now=base)
        status = "200 OK" if allowed else "429 Too Many Requests"
        hdr = "  ".join(f"{k}={v}" for k, v in headers.items())
        print(f"  call {i}: {status:<22} [{reason}]  {hdr}")

    print("\nThe 4th and 5th calls are rejected with 429 and "
          "X-RateLimit-Remaining=0. An agent reads X-RateLimit-Reset and waits "
          "instead of hammering the tool.")

    print("\nLoad shedding (global limit = 6): mixing tools until the global "
          "ceiling trips:\n")
    limiter2 = PerToolRateLimiter(
        limits={"a_x_get": 10, "b_y_get": 10}, window_seconds=1.0, global_limit=6)
    base2 = time.time()
    for i in range(1, 9):
        tool = "a_x_get" if i % 2 else "b_y_get"
        allowed, headers, reason = limiter2.check(tool, now=base2)
        status = "200 OK" if allowed else "429"
        print(f"  call {i:>2} -> {tool:<9} {status:<6} [{reason}]")
    print("\nNeither tool hit its own 10/sec limit, but the combined load "
          "tripped the global ceiling at 6 — that is load shedding.")


if __name__ == "__main__":
    _demo()
