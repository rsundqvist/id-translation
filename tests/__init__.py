import os
from pathlib import Path

os.environ["TEST_ROOT"] = str(Path(__file__).parent).replace("\\", "\\\\")
