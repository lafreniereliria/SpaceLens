"""Pytest shared fixtures."""
import io
import pathlib
import sys

import pandas as pd
import pytest

# Make sure repo root is on sys.path so `from api.analysis import ...` works
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeFS:
    """Minimal stand-in for werkzeug's FileStorage."""
    def __init__(self, data: bytes, filename: str):
        self._buf = io.BytesIO(data)
        self.filename = filename

    def read(self, *a, **kw):
        return self._buf.read(*a, **kw)

    def seek(self, *a, **kw):
        return self._buf.seek(*a, **kw)


@pytest.fixture
def make_csv_fs():
    def _make(df: pd.DataFrame, filename: str = 'sample.csv'):
        return _FakeFS(df.to_csv(index=False).encode('utf-8'), filename)
    return _make


@pytest.fixture
def behavior_df_with_placeholders():
    """A behavior dataframe that contains '/' placeholders in numeric columns.

    Regression: see thread `viihn96cq0fkzl786zpc` and `ioubxjdkqpv3kjdmzq30` —
    pandas reads '/' as a string, so naive astype(int) blows up.
    """
    return pd.DataFrame({
        'UserID':       [1, 2, 3, 4, 5],
        'X':            [10, 20, 30, 40, 50],
        'Y':            [10, 20, 30, 40, 50],
        'Region':       [1, 1, 2, 2, 3],
        'BehaviorNum':  [1, 2, '/', 3, '/'],
        'behaviortype': ['walk', 'sit', '/', 'walk', '/'],
        't':            [10, 20, '/', 40, 50],
    })


@pytest.fixture
def env_df_with_placeholders():
    """Environment dataframe with '/' in ParameterNum / Value (regression for
    thread `ub0i30yq3zrcjekkrlgb`)."""
    return pd.DataFrame({
        'X':            [10, 20, 30, 40],
        'Y':            [10, 20, 30, 40],
        'ParameterNum': [1, 2, '/', 3],
        'Value':        [25.0, '/', 60.0, 70.0],
    })
