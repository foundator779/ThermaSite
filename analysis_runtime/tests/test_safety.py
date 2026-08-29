import pytest

from analysis_runtime.safety import UnsafeCodeError, validate_code


@pytest.mark.parametrize(
    "source",
    [
        "import subprocess",
        "import socket",
        "import requests",
        "from urllib import request",
        "eval('1 + 1')",
        "exec('x=1')",
        "open('../secret')",
    ],
)
def test_static_safety_rejects_dangerous_constructs(source):
    with pytest.raises(UnsafeCodeError):
        validate_code(source)


def test_static_safety_accepts_scientific_code():
    validate_code("import pandas as pd\nframe = pd.DataFrame({'x': [1, 2]})")
