# GCC16 installer source

`ensure_gcc16.py` is an unmodified, SHA-256-pinned copy of the Kernels tool
identified in `source.json`. Keeping that small build tool in the SDK avoids
private Git credentials during image creation. It downloads and verifies the
pinned GCC source archive; it contains no compiler binaries or licensed tools.

Update the source file and its provenance together. The wrapper refuses a hash
or version mismatch. The SDK does not maintain a separate implementation of the
installer: fixes belong in Kernels first, then this pinned copy is refreshed.

The upstream tool is provided under Apache-2.0. GCC itself retains its upstream
licenses and runtime-library exceptions; vendoring this installer does not
relicense the compiler.
