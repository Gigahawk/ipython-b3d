import logging

# ANSI color codes
COLORS = {
    logging.DEBUG: "\033[90m",  # grey
    logging.INFO: "\033[0m",  # reset / normal
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",  # red
    logging.CRITICAL: "\033[1;31m",  # bold red
}
RESET = "\033[0m"


class ColorFormatter(logging.Formatter):
    def format(self, record):
        color = COLORS.get(record.levelno, RESET)
        fmt = f"{color}[%(name)s] %(levelname)s: %(message)s{RESET}"
        formatter = logging.Formatter(fmt)
        return formatter.format(record)


HANDLER = logging.StreamHandler()
HANDLER.setFormatter(ColorFormatter())


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        handlers=[HANDLER],
    )
