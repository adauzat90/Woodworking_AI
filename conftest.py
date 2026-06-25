"""Make the package importable from the source tree without an install.

Inserting this tree's own ``src`` ahead of anything else means pytest always
tests the code *in this checkout* — including isolated git worktrees used during
the cleanup epic — rather than a globally installed copy.
"""

import os
import sys

_SRC = os.path.join(os.path.dirname(__file__), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
