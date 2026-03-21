#!/usr/bin/env python3
"""
Launches an IPython REPL in a PTY, transparently forwarding the user's
terminal to it. When a watched file is saved, injects Ctrl-C followed by
a %run command into the IPython session — as if the user had typed it.

Usage:
    # TODO: set up script alias
    python main.py <file_to_watch.py>
"""

import time
import os
import pty
import sys
import tty
import select
import signal
import termios
import subprocess
import argparse
from multiprocessing import Process
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import fcntl

from ipython_b3d.viewer import run_ocp_vscode


# ---------------------------------------------------------------------------
# Self-pipe: file-watcher thread → select() loop
# ---------------------------------------------------------------------------
# We create a plain OS pipe. The watcher thread writes a single byte to the
# write-end when a reload is needed. The select() loop watches the read-end
# alongside master_fd and stdin, so the injection happens inside the same
# loop iteration as normal I/O — no locks, no races.
_pipe_r, _pipe_w = os.pipe()


def _request_reload(filepath: str) -> None:
    """Called from the watcher thread to signal a reload."""
    # Store the path so the main loop knows what to %run.
    print("[ipython-b3d] Save detected, requesting reload")
    _request_reload.pending_path = filepath
    try:
        os.write(_pipe_w, b"\x01")  # Any single byte works as a wake-up.
    except OSError:
        pass  # Pipe already closed (process is shutting down).


_request_reload.pending_path = ""


# ---------------------------------------------------------------------------
# File watcher (runs in a daemon thread)
# ---------------------------------------------------------------------------


def _start_watcher(filepath: str) -> None:
    """
    Start a watchdog observer that calls _request_reload() whenever
    `filepath` is closed-after-write (i.e. saved).
    """
    abs_path = os.path.abspath(filepath)
    watch_dir = os.path.dirname(abs_path)

    class _Handler(FileSystemEventHandler):
        def on_modified(self, event):
            if not event.is_directory and os.path.abspath(event.src_path) == abs_path:
                _request_reload(abs_path)

        # Some editors (vim, PyCharm) write to a temp file then rename it.
        def on_moved(self, event):
            if not event.is_directory and os.path.abspath(event.dest_path) == abs_path:
                _request_reload(abs_path)

    observer = Observer()
    observer.schedule(_Handler(), watch_dir, recursive=False)
    observer.daemon = True
    observer.start()


# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------


def _make_raw(fd: int) -> list:
    """Put a tty fd into raw mode; return the old attributes for restoration."""
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    return old


def _restore(fd: int, attrs: list) -> None:
    """Restore a tty fd to its previous attributes."""
    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
    except termios.error:
        pass


def _resize_pty(master_fd: int) -> None:
    """Forward the current terminal window size to the PTY master."""

    try:
        buf = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b"\x00" * 8)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, buf)
    except Exception:
        pass  # Non-fatal; IPython will just use a default size.


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run(watch_file: str) -> None:
    abs_watch = os.path.abspath(watch_file)

    # ---- Spawn IPython in a new PTY ----------------------------------------
    master_fd, slave_fd = pty.openpty()

    # Propagate the current window size into the new PTY immediately.
    _resize_pty(master_fd)

    def _child_setup():
        # 1. Start a new session — this process becomes session leader
        #    with no controlling terminal yet.
        os.setsid()
        # 2. Make the slave PTY the controlling terminal of this new session.
        #    This is the step that was missing: without TIOCSCTTY, the slave's
        #    ISIG line discipline never fires, so \x03 from Ctrl-C is never
        #    converted into SIGINT for IPython's process group.
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

    proc = subprocess.Popen(
        ["ipython"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
        preexec_fn=_child_setup,
    )

    # The parent no longer needs the slave end.
    os.close(slave_fd)

    # ---- Start file watcher -------------------------------------------------
    _start_watcher(abs_watch)
    print(
        f"[ipython-b3d] Watching {abs_watch!r}. Save it to trigger a %run reload.",
    )

    # ---- Set user's terminal to raw mode ------------------------------------
    stdin_fd = sys.stdin.fileno()
    old_attrs = _make_raw(stdin_fd)

    # ---- SIGWINCH: propagate window-resize events to the PTY ----------------
    def _sigwinch(_sig, _frame):
        _resize_pty(master_fd)

    signal.signal(signal.SIGWINCH, _sigwinch)

    # ---- SIGINT: ignore in the wrapper; let the \x03 byte do the work -------
    # When the user presses Ctrl-C, two things happen simultaneously:
    #   (a) The kernel delivers SIGINT to every process in the foreground
    #       process group — including this wrapper.
    #   (b) The kernel also writes \x03 into the PTY's input queue (because
    #       the slave side still has ISIG enabled from IPython's perspective).
    #
    # (b) is exactly what we want — IPython sees \x03 and interrupts its cell.
    # (a) is a problem — the default handler raises KeyboardInterrupt and
    # unwinds our select() loop before the byte even reaches IPython.
    #
    # Solution: ignore SIGINT here. The wrapper has no cells to interrupt;
    # IPython handles the signal itself via the PTY.  The user can still exit
    # cleanly with Ctrl-D (EOF), which IPython passes through as normal.
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    # ---- select() loop ------------------------------------------------------
    try:
        while True:
            # Check whether IPython has exited.
            if proc.poll() is not None:
                break

            try:
                rfds, _, _ = select.select([master_fd, stdin_fd, _pipe_r], [], [], 0.05)
            except (select.error, ValueError):
                # master_fd closed underneath us — IPython exited.
                break

            # 1. Data from IPython → user's stdout
            if master_fd in rfds:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    break  # PTY master closed — child has exited.
                if data:
                    os.write(sys.stdout.fileno(), data)

            # 2. Data from user's stdin → IPython
            if stdin_fd in rfds:
                try:
                    data = os.read(stdin_fd, 4096)
                except OSError:
                    break
                if data:
                    os.write(master_fd, data)

            # 3. Reload signal from the file watcher
            if _pipe_r in rfds:
                os.read(_pipe_r, 64)  # Drain the wake-up byte(s).
                path = _request_reload.pending_path

                # Small delay so the editor has fully flushed the file.

                time.sleep(0.05)

                # Inject: Ctrl-C to interrupt any running cell, then %run.
                os.write(master_fd, b"\x03")  # Ctrl-C

                time.sleep(0.05)  # Let IPython print ^C
                cmd = f"%run {path}\n".encode()
                os.write(master_fd, cmd)

    finally:
        # ---- Cleanup --------------------------------------------------------
        _restore(stdin_fd, old_attrs)
        signal.signal(signal.SIGWINCH, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            os.close(_pipe_r)
            os.close(_pipe_w)
        except OSError:
            pass

        # Give IPython a moment to exit cleanly; then force it.
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.terminate()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
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

    ocp_proc = Process(target=run_ocp_vscode)
    ocp_proc.daemon = True
    ocp_proc.start()

    run(args.file)


if __name__ == "__main__":
    main()
