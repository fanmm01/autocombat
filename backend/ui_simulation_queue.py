"""Share the server's CPU budget between background simulation entry points."""
import logging
import os
import threading


class SimulationQueue:
    def __init__(self):
        count = getattr(os, 'process_cpu_count', os.cpu_count)() or 1
        default = max(1, min(8, count - 2))
        try:
            limit = int(os.environ.get('AUTOCOMBAT_WEB_WORKERS', default))
        except ValueError:
            limit = default
        self.workers = min(count, limit, 32) if limit > 0 else default
        self.lock = threading.Lock()
        self.pending = {}
        self.thread = None

    def submit(self, key, run, *args):
        with self.lock:
            self.pending[key] = (run, args)
            if self.thread is None:
                thread = threading.Thread(target=self.drain, daemon=True, name='simulation-queue')
                try:
                    thread.start()
                except RuntimeError:
                    self.pending.pop(key)
                    raise
                self.thread = thread

    def cancel(self, key):
        with self.lock:
            return self.pending.pop(key, None) is not None

    def drain(self):
        while True:
            with self.lock:
                if not self.pending:
                    self.thread = None
                    return
                run, args = self.pending.pop(next(iter(self.pending)))
            try:
                run(*args)
            except Exception:
                logging.getLogger(__name__).exception('Background simulation failed')
