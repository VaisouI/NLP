#!/usr/bin/env python3
"""Подготовительная проверка Notebook при запрете IPC; не имитирует целевую VM."""
from pathlib import Path
import getpass

import matplotlib
import nbformat
from IPython.core.interactiveshell import InteractiveShell
from IPython.utils.capture import capture_output


def main():
    root = Path(__file__).resolve().parents[1]
    path = root / 'notebooks/02_baseline_robustness.ipynb'
    notebook = nbformat.read(path, as_version=4)
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
            raise RuntimeError(f'Code cell {count}: {error}') from error
        outputs = []
        if captured.stdout:
            outputs.append(nbformat.v4.new_output('stream', name='stdout', text=captured.stdout))
        if captured.stderr:
            outputs.append(nbformat.v4.new_output('stream', name='stderr', text=captured.stderr))
        for item in captured.outputs:
            outputs.append(nbformat.v4.new_output('display_data', data=item.data, metadata=item.metadata))
        cell.outputs, cell.execution_count = outputs, count
    notebook.metadata['validation'] = {
        'jupyter_kernel_start_verified': False, 'method': 'preparation: sequential in-process IPython',
        'execution_user': getpass.getuser(), 'code_cells_executed': count,
        'limitation': 'Target Ubuntu must execute nbconvert --execute; preparation is not evidence of its configuration',
    }
    nbformat.validate(notebook)
    nbformat.write(notebook, path)
    print(f'PASS: {count} real code cells executed in preparation; standalone Jupyter startup is not verified')


if __name__ == '__main__':
    main()
