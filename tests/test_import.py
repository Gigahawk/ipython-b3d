from pathlib import Path
import tempfile
import shutil

import pexpect

from _config import TIMEOUT, SCRATCHPAD_PATH, wait_child


def test_import():
    with tempfile.TemporaryDirectory(dir=SCRATCHPAD_PATH) as tmpdirname:
        # Copy sample files to tempdir
        simple = shutil.copy(Path(__file__).parent / "samples/simple.py", tmpdirname)
        ipt = shutil.copy(
            Path(__file__).parent / "samples/import_simple.py", tmpdirname
        )
        simple = Path(simple).absolute()
        ipt = Path(ipt).absolute()

        child = pexpect.spawn(f"ipb3d {ipt}", timeout=TIMEOUT)

        # Run the file, expect initial bar value
        child.expect(r"In \[")
        child.sendline("%r")

        child.expect(r"In \[")
        child.sendline("bar")
        child.expect(r"123")

        # Update simple, nothing should be rerun, since it is not being monitored
        with open(simple, "w") as fp:
            fp.write("foo = 456")
        child.expect(r"In \[")
        child.sendline("bar")
        child.expect(r"123")

        # Trigger a manual run, value should be updated
        child.expect(r"In \[")
        child.sendline("%r")

        child.expect(r"In \[")
        child.sendline("bar")
        child.expect(r"456")

        # Exit
        child.expect(r"In \[")
        child.sendline("exit")
        wait_child(child)


def test_import_debugger():
    with tempfile.TemporaryDirectory(dir=SCRATCHPAD_PATH) as tmpdirname:
        # Copy sample files to tempdir
        debugger = shutil.copy(
            Path(__file__).parent / "samples/debugger.py", tmpdirname
        )
        ipt = shutil.copy(
            Path(__file__).parent / "samples/import_debugger.py", tmpdirname
        )
        debugger = Path(debugger).absolute()
        ipt = Path(ipt).absolute()

        child = pexpect.spawn(f"ipb3d {ipt}", timeout=TIMEOUT)

        # Run the file, expect debugger hit
        child.expect(r"In \[")
        child.sendline("%r")
        child.expect(r"foo = 123")

        # Continue out of debugger
        child.expect(r"\(Pdb")
        child.sendline("c")

        # Check import completed successfully
        child.expect(r"In \[")
        child.sendline("bar")
        child.expect(r"123")

        # Update debugger, nothing should be rerun, since it is not being monitored
        with open(debugger, "r") as fp:
            data = fp.read()
        with open(debugger, "w") as fp:
            fp.write(data.replace("123", "456"))
        child.expect(r"In \[")
        child.sendline("bar")
        child.expect(r"123")

        # Trigger a manual run, value should be updated
        child.expect(r"In \[")
        child.sendline(r"%rr")
        # child.sendline("%r")
        # Regular reload doesn't work???
        # pdb randomly reports stopping at line 6, which is a comment???
        #
        # If you do this test manually and step through the debugger, it is clear that the
        # actual execution is still correct, only the printed line number/lines are incorrect.
        #
        # This seems to have something to do with importlib?
        # If you exit instead of continuing through the first debugger invocation, this
        # subsequent check will work, although IPython will emit this error:
        #     [autoreload] ERROR: Failed to reload module 'debugger' from file '/home/jasper/repos/ipython-b3d/tests/samples/debugger.py'
        #     ... (importlib/autoreload trace)
        #     ModuleNotFoundError: spec not found for the module 'debugger
        # This also just seems to randomly happen once in a while even when you do continue.
        #
        # If you always exit and never allow the module to load completely, the reported line will always be correct.
        # As soon as the module loads once (and is then modified) the weird incorrect line behavior will start.
        # Modifications and effects
        # - Modifying global foo (after function definition): no effect
        # - Modifying local_foo (inside function definition, after pdb call): causes pdb to report a break at line 6 instead of line 11
        # - Adding lines before debugger call: pdb still breaks at line 11, now showing whatever happens to be there
        #
        # ipdb also behaves the same.
        child.expect(r"foo = 456")

        # Continue out of debugger
        child.expect(r"\(Pdb")
        child.sendline("c")

        # Check import completed successfully
        child.expect(r"In \[")
        child.sendline("bar")
        child.expect(r"456")

        # Exit
        child.expect(r"In \[")
        child.sendline("exit")
        wait_child(child)
