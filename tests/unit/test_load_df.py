"""Regression tests for load_df() — numeric coercion against '/' placeholders.

Historical bugs (see threads `viihn96cq0fkzl786zpc`, `ub0i30yq3zrcjekkrlgb`):
- behavior.xlsx 的 `BehaviorNum` / `t` 列含 '/' → 直接 astype(int) 崩溃
- environment.xlsx 的 `ParameterNum` / `Value` 列含 '/' → 同上

修复方案是在 load_df 中对已知数值列统一 pd.to_numeric(errors='coerce')。
这些测试用例锁定该行为，禁止任何后续 PR 退化。
"""
import numpy as np
import pandas as pd

from api.analysis import load_df


def test_load_df_coerces_slash_in_behavior_columns(make_csv_fs, behavior_df_with_placeholders):
    fs = make_csv_fs(behavior_df_with_placeholders, 'behavior.csv')
    df = load_df(fs)

    # BehaviorNum 和 t 中的 '/' 必须被转成 NaN，而不是字符串
    assert df['BehaviorNum'].dtype.kind in ('f', 'i'), (
        f"BehaviorNum dtype must be numeric, got {df['BehaviorNum'].dtype}"
    )
    assert df['t'].dtype.kind in ('f', 'i'), (
        f"t dtype must be numeric, got {df['t'].dtype}"
    )
    assert df['BehaviorNum'].isna().sum() == 2
    assert df['t'].isna().sum() == 1


def test_load_df_coerces_slash_in_environment_columns(make_csv_fs, env_df_with_placeholders):
    fs = make_csv_fs(env_df_with_placeholders, 'environment.csv')
    df = load_df(fs)

    assert df['ParameterNum'].dtype.kind in ('f', 'i')
    assert df['Value'].dtype.kind in ('f', 'i')
    assert df['ParameterNum'].isna().sum() == 1
    assert df['Value'].isna().sum() == 1


def test_load_df_preserves_clean_numeric_columns(make_csv_fs):
    df_in = pd.DataFrame({'X': [1, 2, 3], 'Y': [4, 5, 6], 'UserID': ['u1', 'u2', 'u3']})
    fs = make_csv_fs(df_in, 'loc.csv')
    df = load_df(fs)

    assert list(df['X']) == [1, 2, 3]
    assert list(df['Y']) == [4, 5, 6]
    # UserID 不在数值列白名单里，保持原样
    assert list(df['UserID']) == ['u1', 'u2', 'u3']
