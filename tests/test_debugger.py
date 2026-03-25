from pathlib import Path
import tempfile
import shutil

import pexpect

from _config import TIMEOUT, SCRATCHPAD_PATH, wait_child


def test_debugger_skip():
    with tempfile.TemporaryDirectory(dir=SCRATCHPAD_PATH) as tmpdirname:
        # Copy sample file to tempdir
        fpath = shutil.copy(Path(__file__).parent / "samples/debugger.py", tmpdirname)
        fpath = Path(fpath).absolute()

        child = pexpect.spawn(f"ipb3d {fpath}", timeout=TIMEOUT)

        # Run the file, expect debugger output
        child.expect(r"In \[")
        child.sendline("%r")
        child.expect(r"foo = 123")
        child.expect(r"\(Pdb")

        # Update the file, expect debugger warning
        with open(fpath, "r") as fp:
            data = fp.read()
        with open(fpath, "w") as fp:
            fp.write(data.replace("123", "456"))
        child.expect(r"ignoring reload request")

        # Exit debugger
        child.sendline("exit")

        # Exit
        child.expect(r"In \[")
        child.sendline("exit")
        wait_child(child)


def test_debugger_exit():
    with tempfile.TemporaryDirectory(dir=SCRATCHPAD_PATH) as tmpdirname:
        # Copy sample file to tempdir
        fpath = shutil.copy(Path(__file__).parent / "samples/debugger.py", tmpdirname)
        fpath = Path(fpath).absolute()

        child = pexpect.spawn(f"ipb3d {fpath} --dbg-behavior exit", timeout=TIMEOUT)

        # Run the file, expect debugger output
        child.expect(r"In \[")
        child.sendline("%r")
        child.expect(r"foo = 123")
        child.expect(r"\(Pdb")

        # Update the file, expect breakpoint at updated line
        with open(fpath, "r") as fp:
            data = fp.read()
        with open(fpath, "w") as fp:
            fp.write(data.replace("123", "456"))
        child.expect(r"foo = 456")

        # Exit debugger
        child.sendline("exit")

        # Exit
        child.expect(r"In \[")
        child.sendline("exit")
        wait_child(child)
