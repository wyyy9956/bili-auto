# -*- coding: utf-8 -*-
"""便捷入口，等价于 ``python -m src.cli``。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
