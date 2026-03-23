from argparse import Namespace
import inspect

import ipython_b3d.logging as _logging


class IPythonConfig:
    def __init__(self, args: Namespace, ipy_args: list[str] | None = None):
        self.ipy_args: list[str] = []
        if ipy_args is not None:
            self.ipy_args = ipy_args

        self.watch_file: str = args.file
        self.autoreload: int = args.autoreload
        self.log_level: str = args.log_level
        self.b3d_log_level: str = args.b3d_log_level
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
    def log_setup_section(self) -> str:
        return f"""
{inspect.getsource(_logging)}

setup_logging({self.log_level!r})

__ipb3d_b3d_logger = logging.getLogger("build123d")
__ipb3d_b3d_logger.setLevel(getattr(logging, {self.b3d_log_level.upper()!r}, logging.WARNING))

__ipb3dconfig_logger = logging.getLogger("IPythonConfig")
        """

    @property
    def autoreload_section(self) -> str:
        if self.autoreload > 0:
            return f"""
__ipb3dconfig_logger.info("Enabling autoreload mode {self.autoreload}")
%load_ext autoreload
%autoreload {self.autoreload}
            """
        return ""

    @property
    def manual_reload_section(self) -> str:
        return f"""
from IPython.core.magic import register_line_magic
from IPython import get_ipython

__ipb3dmanualrun_logger = logging.getLogger("Manual Run")

@register_line_magic
def r(line):
    __ipb3dmanualrun_logger.warning("Executing {self.watch_file!r}")
    get_ipython().run_line_magic("run", '"{self.watch_file}"')

__ipb3dconfig_logger.info("Use %r to manually reload {self.watch_file!r} ")
        """

    @property
    def c(self) -> str:
        return f"""
{self.log_setup_section}

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
