import time
import os
import sys

from watchdog.events import FileSystemEventHandler, FileSystemEvent


class IPythonB3dEventHandler(FileSystemEventHandler):
    def __init__(self, file_to_watch: str, msg_pipe: int, debounce_time: float = 0.5):
        self.file_to_watch: str = os.path.abspath(file_to_watch)
        self.debounce_time: float = debounce_time
        self.last_run: float = 0.0
        self.msg_pipe: int = msg_pipe

        print(f"[Monitor] Monitoring '{self.file_to_watch}'")

    def _request_reload(self):
        print(f"[Monitor] Detected change in '{self.file_to_watch}'")
        now = time.time()
        if now - self.last_run < self.debounce_time:
            print("[Monitor] Not requesting reload since reload was just requested")
            return

        self.last_run = now
        print("[Monitor] Requesting reload")
        # Write a random byte to signal reload
        try:
            os.write(self.msg_pipe, b"\x01")
        except OSError:
            print(
                "[Monitor] Request failed, pipe is probably closed",
                file=sys.stderr,
            )
            pass

    def on_modified(self, event: FileSystemEvent):
        if event.is_directory:
            return
        if os.path.abspath(event.src_path) == self.file_to_watch:
            self._request_reload()
