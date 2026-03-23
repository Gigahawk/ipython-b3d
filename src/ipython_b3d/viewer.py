from multiprocessing import Process


def _run_ocp_vscode(args: list[str]):
    print("[Viewer] Starting viewer")
    # import in function to avoid slow startup
    from ocp_vscode.__main__ import main

    # TODO: support args
    main(args, standalone_mode=False)


def run_ocp_vscode(args: list[str] | None = None):
    if args is None:
        args = []
    ocp_proc = Process(target=_run_ocp_vscode, args=(args,))
    ocp_proc.daemon = True
    ocp_proc.start()


if __name__ == "__main__":
    run_ocp_vscode()
