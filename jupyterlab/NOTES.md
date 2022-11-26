# Notes

## Attach IDE debugger to notebook

Attaching to a Jupyter notebook session with Ubuntu
with [PyCharm (JetBrains)](https://www.jetbrains.com/help/pycharm/attaching-to-local-process.html).

```bash
# Allow connections temporarily
echo 0 | sudo tee /proc/sys/kernel/yama/ptrace_scope
```

Get the ID from the terminal window where Jupyter is running. Should look something like:

```
[I 2022-03-03 18:51:11.287 ServerApp] Kernel restarted: fb58e963-a51e-424e-a151-1c6d30c65bb7
```

Process to attach to with PyCharm is `fb58e963-a51e-424e-a151-1c6d30c65bb7`.

## Local package as an editable dependency
```bash
git clone git@github.com:rsundqvist/rics.git my-local/rics
pip install -e my-local/rics
```
