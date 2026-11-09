"""Static checks for scripts/install_mac.sh.

macOS ships bash 3.2, which treats the bytes of a multibyte character that
directly follows `$NAME` as part of the variable name: `"結束碼 $RC）"` is
read as the variable `RC\\xef\\xbc\\x89`, which under `set -u` aborts with
"RC?: unbound variable". Every variable reference must therefore be braced.
"""

import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "install_mac.sh"


def test_no_unbraced_variable_before_non_ascii():
    text = SCRIPT.read_text(encoding="utf-8")
    bad = [(i, line) for i, line in enumerate(text.splitlines(), 1)
           if re.search(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]", line)]
    assert bad == [], bad


def test_all_uppercase_variables_braced():
    text = SCRIPT.read_text(encoding="utf-8")
    assert not re.findall(r"\$[A-Z_][A-Z0-9_]*", text)


def test_rc_initialized_and_syntax_ok():
    text = SCRIPT.read_text(encoding="utf-8")
    assert re.search(r"^RC=0$", text, re.M)
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0
