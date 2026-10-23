"""Small in-process limits for the explicitly single-process demo service."""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException


class RateLimits:
    def __init__(self, per_minute=600, triage_per_minute=6):
        self.per_minute, self.triage_per_minute = per_minute, triage_per_minute
        self.windows = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, client, path):
        group = "triage" if path.endswith("/triage") else "api"
        limit = self.triage_per_minute if group == "triage" else self.per_minute
        now = time.monotonic()
        with self.lock:
            if len(self.windows) > 2048:
                for key in list(self.windows):
                    if not self.windows[key] or self.windows[key][-1] < now - 60:
                        del self.windows[key]
            window = self.windows[(client, group)]
            while window and window[0] <= now - 60:
                window.popleft()
            if len(window) >= limit:
                raise HTTPException(
                    429, "Request limit reached; retry later", headers={"Retry-After": "60"}
                )
            window.append(now)
