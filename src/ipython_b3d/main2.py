import time
import argparse
import pty
import sys
import os
import tty
import subprocess
import termios
from multiprocessing import Process
import signal
import select
import fcntl

from watchdog.observers import Observer

from ipython_b3d.viewer import run_ocp_vscode
from ipython_b3d.monitor import IPythonB3dEventHandler
from ipython_b3d.util import resize_pty, set_tty_attr


class IPythonB3d:
    def __init__(self, watch_file: str):
        self.abs_path: str = os.path.abspath(watch_file)
        self.msg_pipe_r, self.msg_pipe_w = os.pipe()
        self.master_fd = None
        self.slave_fd = None
        self.stdin_fd = None
        self.proc = None

    def run(self):
        self.start_viewer()

        self.master_fd, self.slave_fd = pty.openpty()

        resize_pty(self.master_fd)

        def _child_setup(slave_fd=self.slave_fd):
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

        print(
            "[ipython-b3d] Starting IPython console",
            file=sys.stderr,
        )
        self.proc = subprocess.Popen(
            ["ipython"],
            stdin=self.slave_fd,
            stdout=self.slave_fd,
            stderr=self.slave_fd,
            close_fds=True,
            preexec_fn=_child_setup,
        )

        os.close(self.slave_fd)

        self.start_file_watcher()
        print(
            f"[ipython-b3d] Started monitor for {self.abs_path!r}. Save it to trigger a %run reload.\n",
            file=sys.stderr,
        )

        self.stdin_fd = sys.stdin.fileno()
        old_attrs = termios.tcgetattr(self.stdin_fd)
        tty.setraw(self.stdin_fd)

        self.set_signal_handlers()

        try:
            self.input_loop()
        finally:
            set_tty_attr(self.stdin_fd, old_attrs)
            self.unset_signal_handlers()

            try:
                os.close(self.master_fd)
            except OSError:
                pass

            try:
                os.close(self.msg_pipe_r)
                os.close(self.msg_pipe_w)
            except OSError:
                pass

            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.terminate()

    @property
    def watch_dir(self) -> str:
        return os.path.dirname(self.abs_path)

    def start_viewer(self):
        ocp_proc = Process(target=run_ocp_vscode)
        ocp_proc.daemon = True
        ocp_proc.start()

    def start_file_watcher(self):
        observer = Observer()
        observer.schedule(
            IPythonB3dEventHandler(
                self.abs_path,
                self.msg_pipe_w,
            ),
            self.watch_dir,
            recursive=False,
        )
        observer.daemon = True
        observer.start()

    def set_signal_handlers(self):
        def _sigwinch(_sig, _frame):
            resize_pty(self.master_fd)

        # Forward window size changes to pty
        signal.signal(signal.SIGWINCH, _sigwinch)

        # Ignore SIGINT (Ctrl-C) in wrapper, signal is still forwarded to the pty
        signal.signal(signal.SIGINT, signal.SIG_IGN)

    def unset_signal_handlers(self):
        signal.signal(signal.SIGWINCH, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)

    def input_loop(self):
        while True:
            if self.proc is not None and self.proc.poll() is not None:
                print(
                    "[ipython-b3d] IPython has exited",
                    file=sys.stderr,
                )
                break

            try:
                rfds, _, _ = select.select(
                    [self.master_fd, self.stdin_fd, self.msg_pipe_r], [], [], 0.05
                )
            except (select.error, ValueError):
                print(
                    "[ipython-b3d] master_fd closed, IPython has exited",
                    file=sys.stderr,
                )
                break

            # 1. Data from IPython → user's stdout
            if self.master_fd in rfds:
                try:
                    data = os.read(self.master_fd, 4096)
                except OSError:
                    break  # PTY master closed — child has exited.
                if data:
                    os.write(sys.stdout.fileno(), data)

            # 2. Data from user's stdin → IPython
            if self.stdin_fd in rfds:
                try:
                    data = os.read(self.stdin_fd, 4096)
                except OSError:
                    break
                if data:
                    os.write(self.master_fd, data)

            # 3. Reload signal from the file watcher
            if self.msg_pipe_r in rfds:
                os.read(self.msg_pipe_r, 64)  # Drain the wake-up byte(s).

                # Small delay so the editor has fully flushed the file.
                time.sleep(0.05)

                # Inject: Ctrl-C to interrupt any running cell, then %run.
                os.write(self.master_fd, b"\x03")  # Ctrl-C

                time.sleep(0.05)  # Let IPython print ^C
                cmd = f"%run {self.abs_path}\n".encode()
                os.write(self.master_fd, cmd)


def main():
    parser = argparse.ArgumentParser(
        description="IPython REPL with automatic %run on file save."
    )
    parser.add_argument(
        "file",
        help="Python file to watch and %run when saved.",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"[ipython-b3d] ERROR: File not found: {args.file!r}", file=sys.stderr)
        sys.exit(1)

    wrapper = IPythonB3d(args.file)
    wrapper.run()


if __name__ == "__main__":
    main()
