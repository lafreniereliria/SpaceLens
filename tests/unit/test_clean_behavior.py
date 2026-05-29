"""Regression tests for _clean_behavior_df().

Historical bug (thread `ioubxjdkqpv3kjdmzq30`): behavior.xlsx 中
BehaviorNum 含字符串导致 astype(int) 崩溃。
"""
import pandas as pd

from api.analysis import _clean_behavior_df


def test_clean_drops_rows_with_invalid_behavior_num(behavior_df_with_placeholders):
    df = _clean_behavior_df(behavior_df_with_placeholders)

    # 含 '/' 的两行（行 3、5）应被过滤掉
    assert len(df) == 3
    # BehaviorNum 应是纯 int 类型
    assert df['BehaviorNum'].dtype.kind in ('i', 'u')
    # behaviortype 列中不应再有 '/'
    assert '/' not in df['behaviortype'].astype(str).str.strip().values


def test_clean_keeps_rows_when_t_not_required():
    df_in = pd.DataFrame({
        'BehaviorNum':  [1, 2, '/'],
        'behaviortype': ['a', 'b', 'c'],
        # 故意不含 t 列
    })
    df = _clean_behavior_df(df_in, require_t=False)
    assert len(df) == 2
    assert df['BehaviorNum'].tolist() == [1, 2]


def test_clean_handles_all_valid_rows():
    df_in = pd.DataFrame({
        'BehaviorNum':  [1, 2, 3],
        'behaviortype': ['walk', 'sit', 'stand'],
        't':            [10, 20, 30],
    })
    df = _clean_behavior_df(df_in)
    assert len(df) == 3
    assert df['BehaviorNum'].tolist() == [1, 2, 3]
