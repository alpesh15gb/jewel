# Release gate

A production candidate may be merged to `main` only when the Windows build workflow passes on the pull request head, including source reproducibility, Python compilation, imports, GUI smoke tests, pytest, all three PyInstaller executables, packaged self-tests and Inno Setup installer creation.

The resulting `main` installer is a software production candidate. Bijoria go-live additionally requires the physical acceptance and accountant sign-off documents in this directory.
