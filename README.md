# ipython-b3d

IPython wrapper for use with [build123d](https://github.com/gumyr/build123d) and
[CadQuery](https://github.com/CadQuery/cadquery) projects.

> Note: Linux is the only supported platform, Mac support is probably possible
> with some effort but I do not have a system to test on.

Greatly inspired by
[filewatcher123d](https://github.com/jdegenstein/filewatcher123d)

## Usage

```
ipb3d <file_to_watch>
```

This command will:

- Open an IPython interpreter
- Start an ocp-vscode instance in standalone mode
- Monitor the `<file_to_watch>` and automatically trigger reload when the file
  is saved

## Improvements over filewatcher123d

- Support for passing arguments through to ocp-vscode and IPython
- Proper handling of debugger prompts
- Support for switching the monitored file without exiting
