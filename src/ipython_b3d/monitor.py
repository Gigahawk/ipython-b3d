import time
import os
import logging

from watchdog.events import FileSystemEventHandler, FileSystemEvent


logger = logging.getLogger("Monitor")


class IPythonB3dEventHandler(FileSystemEventHandler):
    def __init__(self, file_to_watch: str, msg_pipe: int, debounce_time: float = 0.5):
        self.file_to_watch: str = file_to_watch
        self.debounce_time: float = debounce_time
        self.last_run: float = 0.0
        self.msg_pipe: int = msg_pipe

        logger.info(f"Monitoring '{self.file_to_watch}'")

    def _request_reload(self):
        now = time.time()
        if now - self.last_run < self.debounce_time:
            logger.debug(
                f"Change detected in {self.file_to_watch!r}, but not requesting reload since reload was just requested"
            )
            return
        logger.info(f"Detected change in {self.file_to_watch!r}, requesting reload")

        self.last_run = now
        # Write a random byte to signal reload
        try:
            os.write(self.msg_pipe, b"\x01")
        except OSError:
            logger.error("Request failed, pipe is probably closed")
            pass

    def on_modified(self, event: FileSystemEvent):
        if event.is_directory:
            return
        if os.path.abspath(event.src_path) == os.path.abspath(self.file_to_watch):
            self._request_reload()
