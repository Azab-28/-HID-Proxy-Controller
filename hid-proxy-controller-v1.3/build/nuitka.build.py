"""Nuitka build script for standalone executable."""
import subprocess
import sys
import os
from pathlib import Path

def main():
    project_root = Path(__file__).parent.parent
    src_main = project_root / "src" / "hid_proxy" / "__main__.py"
    icon_path = project_root / "src" / "hid_proxy" / "ui" / "resources" / "icons" / "tray_idle.ico"
    
    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--follow-imports",
        "--enable-plugin=pyside6",
        "--enable-plugin=numpy",
        "--enable-plugin=cryptography",
        f"--output-dir={project_root}/dist",
        "--onefile",
        "--windows-disable-console",
        f"--windows-icon-from-ico={icon_path}" if icon_path.exists() else "",
        "--include-package-data=hid_proxy.ui.resources",
        "--windows-uac-admin=force",
        "--remove-output",
        "--assume-yes-for-downloads",
        str(src_main),
    ]
    cmd = [c for c in cmd if c]
    
    print("Building with Nuitka...")
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=project_root)
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())
