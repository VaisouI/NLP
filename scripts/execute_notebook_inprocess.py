#!/usr/bin/env python3
"""Локальная проверка ячеек при запрете сокетов Jupyter в контейнере.

Это выполнение реального кода через IPython, а не проверка запуска Jupyter-сервера.
На учебной VM notebook дополнительно выполняется обычным nbconvert --execute.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
import nbformat
from IPython.core.interactiveshell import InteractiveShell
from IPython.utils.capture import capture_output


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    notebook_path = root / 'notebooks/01_dataset_analysis.ipynb'
    notebook = nbformat.read(notebook_path, as_version=4)
    shell = InteractiveShell.instance()
    matplotlib.use('module://matplotlib_inline.backend_inline', force=True)
    from matplotlib_inline.backend_inline import configure_inline_support
    configure_inline_support(shell, 'module://matplotlib_inline.backend_inline')
    count = 0
    for cell in notebook.cells:
        if cell.cell_type != 'code':
            continue
        count += 1
        with capture_output(stdout=True, stderr=True, display=True) as captured:
            result = shell.run_cell(cell.source, store_history=True)
        error = result.error_before_exec or result.error_in_exec
        if error:
            raise RuntimeError(f'Cell {count} failed: {error}') from error
        outputs = []
        if captured.stdout:
            outputs.append(nbformat.v4.new_output('stream', name='stdout', text=captured.stdout))
        if captured.stderr:
            outputs.append(nbformat.v4.new_output('stream', name='stderr', text=captured.stderr))
        for rich in captured.outputs:
            outputs.append(nbformat.v4.new_output('display_data', data=rich.data, metadata=rich.metadata))
        cell.outputs = outputs
        cell.execution_count = count
    notebook.metadata['validation'] = {
        'method': 'sequential in-process IPython execution',
        'code_cells_executed': count,
        'jupyter_kernel_start_verified': False,
        'limitation': 'The hosted container denies TCP and IPC socket binding; rerun nbconvert --execute on the Ubuntu VM.',
    }
    nbformat.validate(notebook)
    nbformat.write(notebook, notebook_path)
    print(f'PASS: all {count} code cells executed sequentially using in-process IPython.')
    print('LIMITATION: a standalone Jupyter kernel/server could not be started in this container; verify on the target VM.')


if __name__ == '__main__':
    main()
