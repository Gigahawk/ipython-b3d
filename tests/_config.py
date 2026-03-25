from pathlib import Path

TIMEOUT = 10

# watchdog.observer doesn't seem to work inside macOS default tempdir.
# Use a scratchpad path inside the repo instead.
SCRATCHPAD_PATH = Path(__file__).parent / ".scratch"
SCRATCHPAD_PATH.mkdir(parents=True, exist_ok=True)


def wait_child(child):
    # Avoid Hang on macOS
    # https://stackoverflow.com/questions/58751357/python-script-pexpect-hangs-on-child-wait
    while True:
        try:
            child.read_nonblocking()
        except Exception:
            break

    if child.isalive():
        child.wait()
