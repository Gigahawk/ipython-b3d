from argparse import Namespace


class IPythonConfig:
    def __init__(self, args: Namespace, ipy_args: list[str] | None = None):
        self.ipy_args: list[str] = []
        if ipy_args is not None:
            self.ipy_args = ipy_args

        self.watch_file: str = args.file
        self.autoreload: int = args.autoreload
        self._c = ""

        self.filter_args()

        pass

    def filter_args(self):
        for arg in self.ipy_args.copy():
            # Filter out -c, add to our existing preamble
            if arg.startswith("-c"):
                self.ipy_args.remove(arg)
                self._c += "\n" + arg.split("=", 1)[1] + "\n"

            # Filter out -i, we always require it
            if arg.startswith("-i"):
                self.ipy_args.remove(arg)

    @property
    def autoreload_section(self) -> str:
        if self.autoreload > 0:
            return f"""
print("[IPythonConfig] Enabling autoreload mode {self.autoreload}")
%load_ext autoreload
%autoreload {self.autoreload}
            """
        return ""

    @property
    def manual_reload_section(self) -> str:
        return f"""
from IPython.core.magic import register_line_magic
from IPython import get_ipython

@register_line_magic
def r(line):
    print("[Manual Run] Executing {self.watch_file!r}")
    get_ipython().run_line_magic("run", '"{self.watch_file}"')

print("[IPythonConfig] Use %r to manually reload {self.watch_file!r} ")
        """

    @property
    def c(self) -> str:
        return f"""
{self.autoreload_section}

{self.manual_reload_section}

{self._c}
        """

    @property
    def args(self) -> list[str]:
        return [
            "-c",
            self.c,
            # Force interactive mode always, IPython will exit if we pass -c
            "-i",
        ]
