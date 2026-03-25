import pdb


def run_foo(arg=None):
    try:
        # Force normal pdb instead of pdb++ to avoid colors in debugger
        pdb.pdb.set_trace()
    except AttributeError:
        pdb.set_trace()

    local_foo = 123
    return local_foo


foo = 123

if __name__ == "__main__":
    run_foo(arg="debugger")
