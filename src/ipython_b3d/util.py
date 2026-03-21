import termios
import tty
import fcntl
import termios
import sys


def set_tty_attr(fd: int, attrs: list) -> None:
    """Restore a tty fd to its previous attributes."""
    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
    except termios.error:
        pass


def resize_pty(master_fd: int) -> None:
    """Forward the current terminal window size to the PTY master."""

    try:
        buf = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b"\x00" * 8)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, buf)
    except Exception:
        pass  # Non-fatal; IPython will just use a default size.
