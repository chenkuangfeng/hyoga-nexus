"""Install all local workspace packages using the active Python environment."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
args = [sys.executable, "-m", "pip", "install"]
for package in sorted((root / "packages").iterdir()):
    if (package / "pyproject.toml").exists():
        args.extend(["-e", str(package)])
args.extend(["-e", f"{root}[dev]"])
subprocess.run(args, check=True)
