import time
import argparse
import pty
import sys
import os
import subprocess
import termios
import signal
import select
import fcntl

from watchdog.observers import Observer

from ipython_b3d.viewer import run_ocp_vscode
from ipython_b3d.monitor import IPythonB3dEventHandler
from ipython_b3d.util import resize_pty, set_tty_attr, make_raw, split_args
from ipython_b3d.config import IPythonConfig


class IPythonB3d:
    def __init__(self, watch_file: str, ipython_args: list[str] | None = None):
        self.ipython_args: list[str] = []
        if ipython_args is not None:
            self.ipython_args = ipython_args
        self.watch_file: str = watch_file
        self.msg_pipe_r, self.msg_pipe_w = os.pipe()
        self.master_fd = None
        self.slave_fd = None
        self.stdin_fd = None
        self.proc = None

    def run(self):
        self.master_fd, self.slave_fd = pty.openpty()

        resize_pty(self.master_fd)

        def _child_setup(slave_fd=self.slave_fd):
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

        print("[ipython-b3d] Starting IPython console")
        self.proc = subprocess.Popen(
            ["ipython"] + self.ipython_args,
            stdin=self.slave_fd,
            stdout=self.slave_fd,
            stderr=self.slave_fd,
            close_fds=True,
            preexec_fn=_child_setup,
        )

        os.close(self.slave_fd)

        self.start_file_watcher()
        print(
            f"[ipython-b3d] Started monitor for {self.watch_file!r}. Save it to trigger a %run reload.\n"
        )

        self.stdin_fd = sys.stdin.fileno()
        old_attrs = termios.tcgetattr(self.stdin_fd)
        make_raw(self.stdin_fd)

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
        return os.path.dirname(self.watch_file)

    def start_file_watcher(self):
        observer = Observer()
        observer.schedule(
            IPythonB3dEventHandler(
                self.watch_file,
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
                print("[ipython-b3d] IPython has exited", file=sys.stderr)
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
                cmd = f"%run {self.watch_file}\n".encode()
                os.write(self.master_fd, cmd)


class _ArgFormatter(
    argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter
):
    pass


def main():
    parser = argparse.ArgumentParser(formatter_class=_ArgFormatter)
    parser.description = f"""
    IPython wrapper that automatically spawns an ocp-vscode instance and autoreloads files on save.

    Argument forwarding:
        --ipy<arg>(=val) -> forwarded to IPython
        --ocv<arg>(=val) -> forwarded to ocp-vscode

        Note: for arguments with values you MUST use a '=', ' ' is not allowed.

    Example:
        {parser.prog} \\
            --ipy-c="print('hello')" --ipy--matplotlib=qt --ipyprofile --ipycreate \\
            --ocv-ticks=10

    """
    _ = parser.add_argument(
        "file",
        type=lambda p: os.path.abspath(p),
        help="Python file to watch and %%run when saved.",
    )
    _ = parser.add_argument(
        "--autoreload",
        type=int,
        default=2,
        choices=[0, 1, 2, 3],
        help="IPython autoreload mode, set to 0 to disable",
    )
    args, rest = parser.parse_known_args()
    rest_args = split_args(rest)
    fname: str = str(args.file)

    if not os.path.isfile(fname):
        print(f"[ipython-b3d] ERROR: File not found: {fname!r}", file=sys.stderr)
        sys.exit(1)

    ipython_config = IPythonConfig(args, rest_args["--ipy"])

    run_ocp_vscode(rest_args["--ocv"])

    wrapper = IPythonB3d(fname, ipython_config.args)
    wrapper.run()


if __name__ == "__main__":
    main()
