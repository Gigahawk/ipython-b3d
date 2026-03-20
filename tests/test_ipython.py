import time

import wpexpect


def test_ipython():
    # env = copy.copy(os.environ)
    ## Disable color codes
    # env["TERM"] = "dumb"
    child = wpexpect.spawn(
        # disable control chars
        "ipython --simple-prompt",
        # env=env,
        encoding="utf-8",
    )
    child.expect("In ", timeout=10)
    child.sendline("1 + 1")
    child.expect(": 2", timeout=10)
    child.sendline("from time import sleep; sleep(10)")
    time.sleep(0.1)
    child.sendcontrol("c")
    child.expect("KeyboardInterrupt", timeout=10)
    child.sendline("exit")
    child.wait()
