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
import collections
import re
import logging

from watchdog.observers import Observer

from ipython_b3d.viewer import run_ocp_vscode
from ipython_b3d.monitor import IPythonB3dEventHandler
from ipython_b3d.util import (
    resize_pty,
    set_tty_attr,
    make_raw,
    split_args,
    strip_unprintable,
)
from ipython_b3d.config import IPythonConfig
from ipython_b3d.logging import setup_logging


# Match "(Pdb) ", "(Pdb++) ", "ipdb>", "ipdb++>"
# Note: it seems like ipdb the ipdb prompt doesn't have a space after cleaning.
# It probably uses some strange escape sequence that gets filtered out
_DBG_PROMPT_RE = re.compile(rb"^\(Pdb\+{0,2}\) |^ipdb\+{0,2}>")

# Match "In [<number>]: "
_IPYTHON_PROMPT_RE = re.compile(rb"^In \[\d+\]: ")

logger = logging.getLogger("ipython-b3d")


class IPythonB3d:
    def __init__(
        self,
        watch_file: str,
        ipython_args: list[str] | None = None,
        dbg_buf_len: int = 1024,
    ):
        self.ipython_args: list[str] = []
        if ipython_args is not None:
            self.ipython_args = ipython_args
        self.watch_file: str = watch_file
        self.msg_pipe_r, self.msg_pipe_w = os.pipe()
        self.master_fd = None
        self.slave_fd = None
        self.stdin_fd = None
        self.proc = None
        self.dbg_buf: collections.deque[int] = collections.deque(maxlen=dbg_buf_len)

    def run(self):
        self.master_fd, self.slave_fd = pty.openpty()

        resize_pty(self.master_fd)

        def _child_setup(slave_fd=self.slave_fd):
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

        logger.info("Starting IPython console")
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
        logger.info(
            f"Started monitor for {self.watch_file!r}. Save it to trigger a %run reload."
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

    def allow_reload(self) -> bool:
        lines = re.split(rb"[\r\n]+", bytes(self.dbg_buf))
        for line in reversed(lines):
            line = line.lstrip()
            if not line:
                continue
            if _DBG_PROMPT_RE.search(line):
                logger.info("Inside debugger, ignoring reload request")
                return False
            if _IPYTHON_PROMPT_RE.search(line):
                logger.debug("Found IPython prompt, issuing reload")
                return True
        logger.warning(
            "Warning: Could not find prompt, issuing reload anyways.",
            file=sys.stderr,
        )
        return True

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
                logger.error("IPython has exited", file=sys.stderr)
                break

            try:
                rfds, _, _ = select.select(
                    [self.master_fd, self.stdin_fd, self.msg_pipe_r], [], [], 0.05
                )
            except (select.error, ValueError):
                logger.error("master_fd closed, IPython has exited")
                break

            # 1. Data from IPython → user's stdout
            if self.master_fd in rfds:
                try:
                    data = os.read(self.master_fd, 4096)
                except OSError:
                    break  # PTY master closed — child has exited.
                if data:
                    self.dbg_buf.extend(strip_unprintable(data))
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

                if self.allow_reload():
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
    _ = parser.add_argument(
        "--dbg-buflen",
        type=int,
        default=1024,
        help=(
            "Length of buffer used to detect if a debugger is active.\n"
            "Reloads will not be triggered when a debugger is detected."
        ),
    )
    _log_levels = ["debug", "info", "warning", "error", "critical"]
    _ = parser.add_argument(
        "--log-level",
        type=str,
        default="info",
        choices=_log_levels,
        help="Verbosity of ipython-b3d/general log messages",
    )
    _ = parser.add_argument(
        "--b3d-log-level",
        type=str,
        default="warning",
        choices=_log_levels,
        help="Verbosity of build123d log messages",
    )
    args, rest = parser.parse_known_args()
    rest_args = split_args(rest)
    fname: str = str(args.file)

    setup_logging(args.log_level)

    if not os.path.isfile(fname):
        logger.error(f"File not found: {fname!r}")
        sys.exit(1)

    ipython_config = IPythonConfig(args, rest_args["--ipy"])

    run_ocp_vscode(rest_args["--ocv"])

    wrapper = IPythonB3d(
        fname,
        ipython_args=ipython_config.args,
        dbg_buf_len=args.dbg_buflen,
    )
    wrapper.run()


if __name__ == "__main__":
    main()
