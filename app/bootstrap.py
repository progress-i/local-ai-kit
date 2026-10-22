"""Ubuntu launcher bootstrap; only stdlib is used by the distribution Python."""
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from lib.common import APP, KIT, bootstrap, env_python, owned_root

try:
    arguments = sys.argv[1:]
    root_arg = Path.home() / "LocalAISeries"
    if "--root" in arguments:
        i = arguments.index("--root")
        root_arg = arguments[i + 1]
        del arguments[i:i + 2]
    action = arguments[0] if arguments else "hardware"
    # These paths can be inspected/removed even after a broken or partial install.
    if action in ("hardware", "remove", "inventory"):
        os.execv(sys.executable, [sys.executable, "-B", str(APP / "manage.py"), "--root", str(root_arg), *arguments])
    root = owned_root(root_arg, create=(action == "install"))
    py = bootstrap(root) if action == "install" else env_python(root)
    if not py.exists():
        raise RuntimeError("Окружение не установлено полностью. Повторите install.")
    os.execv(str(py), [str(py), "-B", str(APP / "manage.py"), "--root", str(root), *arguments])
except (Exception, KeyboardInterrupt) as e:
    print(f"ОШИБКА: {e}", file=sys.stderr)
    sys.exit(1)
