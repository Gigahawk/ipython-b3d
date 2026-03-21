import termios
import fcntl
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


def make_raw(fd: int) -> list:
    """
    Put the terminal into raw-input mode while preserving output processing.

    tty.setraw() disables ALL termios processing including OPOST/ONLCR on the
    output side, which means bare \\n from IPython (or anything else writing to
    stdout) no longer gets translated to \\r\\n — causing the classic
    staircase effect where lines drop down but don't return to column 0.

    We only need raw mode on the *input* side (no echo, no line buffering, no
    signal character processing — we handle all of that ourselves via the PTY).
    Output should keep OPOST so the kernel still does \\n → \\r\\n translation.
    """
    new = termios.tcgetattr(fd)

    # Input flags: disable start/stop flow control and CR/NL translation.
    new[0] &= ~(termios.IXON | termios.IXOFF | termios.ICRNL)

    # Output flags: deliberately leave OPOST and ONLCR *enabled*.
    # new[1] is oflag — do not touch it.

    # Control flags: 8-bit chars, disable parity.
    new[2] &= ~(termios.PARENB)
    new[2] |= termios.CS8

    # Local flags: no echo, no canonical mode, no signal generation.
    # This is the core of "raw input" — but we leave OPOST alone.
    new[3] &= ~(
        termios.ECHO | termios.ECHONL | termios.ICANON | termios.ISIG | termios.IEXTEN
    )

    # Read returns immediately with whatever is available.
    new[6][termios.VMIN] = 1
    new[6][termios.VTIME] = 0

    termios.tcsetattr(fd, termios.TCSADRAIN, new)
