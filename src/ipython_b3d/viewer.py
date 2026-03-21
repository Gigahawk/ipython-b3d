def run_ocp_vscode():
    print("[Viewer] Starting viewer")
    # import in function to avoid slow startup
    from ocp_vscode.__main__ import main

    # TODO: support args
    main([], standalone_mode=False)


if __name__ == "__main__":
    run_ocp_vscode()
