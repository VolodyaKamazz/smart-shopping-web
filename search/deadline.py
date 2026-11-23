import time

SEARCH_DEADLINE = 9.0
DELIVERY_BUDGET = 3.0


class Deadline:
    def __init__(self, seconds, started=None):
        self.limit = (time.monotonic() if started is None else started) + seconds

    def remaining(self):
        return max(0.0, self.limit - time.monotonic())

    @property
    def expired(self):
        return time.monotonic() >= self.limit

    def share(self, seconds):
        return Deadline(min(seconds, self.remaining()))
