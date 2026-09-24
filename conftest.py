import os
import sys
import pathlib

# Ensure TCL_LIBRARY and TK_LIBRARY are set for Windows Python 3.14 environments
base_p = pathlib.Path(sys.base_prefix)
tcl_dir = base_p / "tcl" / "tcl8.6"
tk_dir = base_p / "tcl" / "tk8.6"
if tcl_dir.exists() and "TCL_LIBRARY" not in os.environ:
    os.environ["TCL_LIBRARY"] = str(tcl_dir)
if tk_dir.exists() and "TK_LIBRARY" not in os.environ:
    os.environ["TK_LIBRARY"] = str(tk_dir)
