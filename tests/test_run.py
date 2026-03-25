from pathlib import Path
import tempfile
import shutil

import pexpect

from _config import TIMEOUT, SCRATCHPAD_PATH, wait_child


def test_run():
    with tempfile.TemporaryDirectory(dir=SCRATCHPAD_PATH) as tmpdirname:
        # Copy sample file to tempdir
        fpath = shutil.copy(Path(__file__).parent / "samples/simple.py", tmpdirname)
        fpath = Path(fpath).absolute()

        child = pexpect.spawn(f"ipb3d {fpath}", timeout=TIMEOUT)

        # File does not run on first load, expect a NameError
        child.expect(r"In \[")
        child.sendline("foo")
        child.expect("NameError")

        # Run the file
        child.expect(r"In \[")
        child.sendline("%r")

        # Variable should exist now
        child.expect(r"In \[")
        child.sendline("foo")
        child.expect("123")

        # Expect the file to run on a new write
        with open(fpath, "wb") as fp:
            fp.write(b"foo = 456")
        child.expect(r"\%run")

        # Variable value should have changed
        child.expect(r"In \[")
        child.sendline("foo")
        child.expect("456")

        # Exit
        child.expect(r"In \[")
        child.sendline("exit")
        wait_child(child)
