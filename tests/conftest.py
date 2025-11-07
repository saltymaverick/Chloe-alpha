import sys
from pathlib import Path

# Add project root (/root/Chloe-alpha) so `import engine_alpha` works in tests
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
