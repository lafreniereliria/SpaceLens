"""
本地 SQLite 项目数据库
负责历史项目的持久化存储
"""

import os
import sqlite3
import json
import time
import threading
from pathlib import Path


# ── 数据库文件路径 ─────────────────────────────────────────
def _get_db_path() -> str:
    base = os.environ.get('SPACELENS_DATA_DIR', '')
    if not base:
        base = os.path.join(Path.home(), '.spacelens')
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, 'projects.db')


DB_PATH = _get_db_path()
_lock = threading.Lock()

# ── 建表 SQL ───────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    building_type TEXT    NOT NULL DEFAULT '',
    input_folder  TEXT    NOT NULL DEFAULT '',
    session_id    TEXT    NOT NULL,
    computed      TEXT    NOT NULL DEFAULT '[]',
    skipped       TEXT    NOT NULL DEFAULT '[]',
    floorplan_b64 TEXT    DEFAULT NULL,
    files_md5     TEXT    DEFAULT NULL,  -- JSON dict {slot: md5}，去重用
    created_at    REAL    NOT NULL
);
"""

# ── 迁移：旧库可能缺字段 ─────────────────────────────────
_MIGRATIONS = [
    ('files_md5',     'ALTER TABLE projects ADD COLUMN files_md5     TEXT DEFAULT NULL;'),
    ('result_folder', 'ALTER TABLE projects ADD COLUMN result_folder TEXT DEFAULT NULL;'),
]


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """创建表（若不存在），并做列迁移"""
    with _lock:
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
            cols = [r[1] for r in conn.execute('PRAGMA table_info(projects)').fetchall()]
            for col_name, sql in _MIGRATIONS:
                if col_name not in cols:
                    conn.execute(sql)
            conn.commit()
        finally:
            conn.close()


# ── 去重 key 计算 ───────────────────────────────────────────
def _dedup_key(files_md5: dict | None, building_type: str) -> str | None:
    """
    用各文件 MD5（排序后）+ 建筑类型 拼成去重字符串。
    files_md5 格式：{'img': 'abc...', 'loc': 'def...', ...}
    任何一个为 None / 空则返回 None（不去重）
    """
    if not files_md5:
        return None
    sorted_md5 = '|'.join(f'{k}:{v}' for k, v in sorted(files_md5.items()) if v)
    if not sorted_md5:
        return None
    return f'{building_type}::{sorted_md5}'


# ── CRUD ──────────────────────────────────────────────────

def save_project(name: str, building_type: str, input_folder: str,
                 session_id: str, computed: list, skipped: list,
                 floorplan_b64: str | None = None,
                 files_md5: dict | None = None,
                 result_folder: str | None = None) -> int:
    """
    保存项目记录，返回记录 id。

    去重策略：
    1. 若 files_md5 + building_type 完全相同的记录已存在 → 更新该记录（session_id 等更新）
    2. 若 session_id 已存在 → 更新该记录
    3. 否则插入新记录
    """
    with _lock:
        conn = _connect()
        try:
            computed_j = json.dumps(computed, ensure_ascii=False)
            skipped_j  = json.dumps(skipped,  ensure_ascii=False)
            files_md5_j = json.dumps(files_md5, ensure_ascii=False) if files_md5 else None

            dedup_key = _dedup_key(files_md5, building_type)

            # 优先按 files_md5+building_type 去重
            existing = None
            if dedup_key:
                # 查找所有有 files_md5 的同类型记录，逐一比对 key
                rows = conn.execute(
                    'SELECT id, files_md5, building_type FROM projects WHERE building_type = ?',
                    (building_type,)
                ).fetchall()
                for row in rows:
                    if row['files_md5']:
                        try:
                            stored_md5 = json.loads(row['files_md5'])
                        except Exception:
                            stored_md5 = {}
                        if _dedup_key(stored_md5, row['building_type']) == dedup_key:
                            existing = row
                            break

            # 再按 session_id 查（兜底）
            if existing is None:
                existing = conn.execute(
                    'SELECT id FROM projects WHERE session_id = ?', (session_id,)
                ).fetchone()

            if existing:
                conn.execute(
                    '''UPDATE projects SET
                        name=?, building_type=?, input_folder=?, session_id=?,
                        computed=?, skipped=?, floorplan_b64=?, files_md5=?,
                        result_folder=?
                       WHERE id=?''',
                    (name, building_type, input_folder, session_id,
                     computed_j, skipped_j, floorplan_b64,
                     files_md5_j, result_folder, existing['id'])
                )
                conn.commit()
                return existing['id']
            else:
                cur = conn.execute(
                    '''INSERT INTO projects
                       (name, building_type, input_folder, session_id,
                        computed, skipped, floorplan_b64, files_md5, result_folder, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (name, building_type, input_folder, session_id,
                     computed_j, skipped_j, floorplan_b64,
                     files_md5_j, result_folder, time.time())
                )
                conn.commit()
                return cur.lastrowid
        finally:
            conn.close()


def list_projects() -> list[dict]:
    """返回所有项目，按创建时间倒序"""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                'SELECT * FROM projects ORDER BY created_at DESC'
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d['computed'] = json.loads(d['computed'] or '[]')
                d['skipped']  = json.loads(d['skipped']  or '[]')
                # files_md5 不暴露给前端（体积大且无用）
                d.pop('files_md5', None)
                result.append(d)
            return result
        finally:
            conn.close()


def get_project(project_id: int) -> dict | None:
    """根据 id 获取单个项目"""
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                'SELECT * FROM projects WHERE id = ?', (project_id,)
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            d['computed'] = json.loads(d['computed'] or '[]')
            d['skipped']  = json.loads(d['skipped']  or '[]')
            if d.get('files_md5'):
                try:
                    d['files_md5'] = json.loads(d['files_md5'])
                except Exception:
                    d['files_md5'] = {}
            return d
        finally:
            conn.close()


def delete_project(project_id: int) -> bool:
    """删除一条项目记录"""
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute('DELETE FROM projects WHERE id = ?', (project_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def update_project_name(project_id: int, name: str) -> bool:
    """重命名项目"""
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                'UPDATE projects SET name=? WHERE id=?', (name, project_id)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


# 初始化
init_db()
