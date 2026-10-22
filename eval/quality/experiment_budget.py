"""Sampled resource guard for bounded remote evaluation controllers."""
import threading
import time

import psutil

from eval.quality import runner


class BudgetGuard:
    """Sample this controller, all owned descendants, and every output root."""

    def __init__(self, roots, evidence, limits, deadline):
        self.roots, self.evidence, self.limits, self.deadline = roots, evidence, limits, deadline
        self.owner = psutil.Process()
        self.peaks = {'rss_bytes': 0, 'disk_bytes': 0, 'evidence_bytes': 0}
        self.violation = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._watch, daemon=True)

    def sample(self):
        children = self.owner.children(recursive=True)
        rss = self.owner.memory_info().rss
        for child in children:
            try:
                rss += child.memory_info().rss
            except psutil.NoSuchProcess:
                pass
        values = {'rss_bytes': rss, 'disk_bytes': sum(runner.disk_bytes(p) for p in self.roots),
                  'evidence_bytes': runner.disk_bytes(self.evidence)}
        self.peaks = {key: max(self.peaks[key], value) for key, value in values.items()}
        reason = next((key + '_budget' for key, value in values.items() if value >= self.limits[key]), None)
        if time.monotonic() >= self.deadline:
            reason = 'complete_deadline'
        if reason:
            self.violation = self.violation or reason
            # Only descendants of this specific controller are owned here.
            for child in reversed(children):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass

    def _watch(self):
        try:
            while not self.stop.is_set():
                self.sample()
                self.stop.wait(.1)
        except (psutil.Error, OSError) as exc:
            self.violation = 'budget_inspection_failed:' + type(exc).__name__

    def start(self):
        self.sample()
        self.thread.start()

    def check(self):
        self.sample()
        if self.violation:
            raise RuntimeError(self.violation)

    def close(self):
        self.stop.set()
        if self.thread.ident is not None:
            self.thread.join(timeout=2)
        if self.thread.is_alive():
            self.violation = self.violation or 'budget_monitor_cleanup'
        self.sample()
