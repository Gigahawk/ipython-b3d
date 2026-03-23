from argparse import Namespace
import inspect

import ipython_b3d.logging as _logging
from ipython_b3d.util import get_sidechannel_fifo_path


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
    def pre_run_setup_section(self) -> str:
        return """
from IPython import get_ipython

def __pre_run_handler(*args, **kwargs):
    import linecache
    linecache.clearcache()

get_ipython().events.register("pre_run_cell", __pre_run_handler)
        """

    @property
    def sidechannel_setup_section(self) -> str:
        return f"""
import json

def __send_sidechannel(cmd: str, args: list[str] = [], kwargs: dict[str, str] = {{}}):
    __ipb3d_fifo_path = {get_sidechannel_fifo_path()!r}
    payload = {{
        "cmd": cmd,
        "args": args,
        "kwargs": kwargs,
    }}
    __ipb3dconfig_logger.debug(f"Sending command to wrapper: {{payload}}")
    if __ipb3d_fifo_path:
        with open(__ipb3d_fifo_path, "w") as f:
            f.write(json.dumps(payload))
    else:
        __ipb3dconfig_logger.error("Send failed for command: {{payload}}")
        """

    @property
    def switch_file_setup_section(self) -> str:
        return """
from IPython.core.magic import register_line_magic
from InquirerPy import inquirer
from InquirerPy.validator import Validator
import os

__ipb3dswitchfile_logger = logging.getLogger("Switch File")

def __is_py_script(path):
    if not os.path.isfile(path):
        return False
    if not str(path).endswith(".py") or str(path).endswith(".ipy"):
        return False
    return True

@register_line_magic
def sf(line):
    err_msg = "A python file must be selected"
    if line:
        path = line
    else:
        validator = Validator.from_callable(__is_py_script, error_message=err_msg)
        path = inquirer.filepath(
            message="Enter a python file to monitor:",
            validate=validator,
            only_files=False,
            only_directories=False,
            mandatory=True,
        ).execute()
    path = os.path.abspath(path)
    if not __is_py_script(path):
        __ipb3dswitchfile_logger.error(err_msg)
        return

    __send_sidechannel("switch_file", [path])

    global __ipb3dmanualrun_target
    __ipb3dmanualrun_target = path

__ipb3dconfig_logger.info("Use %sf to switch the monitored file")

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
__ipb3dmanualrun_target = {self.watch_file!r}

@register_line_magic
def r(line):
    __ipb3dmanualrun_logger.warning(f"Executing {{__ipb3dmanualrun_target!r}}")
    get_ipython().run_line_magic("run", '"{{__ipb3dmanualrun_target}}"')

__ipb3dconfig_logger.info("Use %r to manually reload {self.watch_file!r} ")
        """

    @property
    def c(self) -> str:
        return f"""
{self.log_setup_section}

{self.sidechannel_setup_section}

{self.pre_run_setup_section}

{self.autoreload_section}

{self.manual_reload_section}

{self.switch_file_setup_section}

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
