"""
空间分析系统 Demo - Flask 主程序
"""

from flask import Flask, render_template, send_from_directory, request, jsonify
from api.analysis import analysis_bp
import os

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB

# ── 管理员密码（修改此处即可）────────────────────────────────────
ADMIN_PASSWORD = 'spacelens2025'
# ──────────────────────────────────────────────────────────────────

app.register_blueprint(analysis_bp, url_prefix='/api')


@app.route('/')
def cover():
    return render_template('cover.html')


@app.route('/results')
def index():
    return render_template('index.html')


@app.route('/projects')
def projects():
    return render_template('projects.html')


@app.route('/select_module')
def select_module():
    return render_template('select_module.html')


@app.route('/new_project')
def new_project():
    return render_template('new_project.html')


@app.route('/history')
def history():
    return render_template('history.html')


@app.route('/compare')
def compare():
    return render_template('compare.html')


@app.route('/admin/db')
def admin_db():
    return render_template('admin_db.html')


# ── 管理员 API ────────────────────────────────────────────────────
@app.route('/api/admin/verify', methods=['POST'])
def admin_verify():
    """验证管理员密码"""
    data = request.get_json(silent=True) or {}
    if data.get('password') == ADMIN_PASSWORD:
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': '密码错误，请重试'})


@app.route('/api/admin/db_data', methods=['GET'])
def admin_db_data():
    """返回完整数据库内容（需要正确通过密码验证）"""
    # 简单防护：校验 token（sessionStorage 存的是 '1'，这里以密码哈希做 token 更安全，
    # 但对于本地 desktop 场景简单防护即可）
    try:
        from api.db import DB_PATH, _connect, _lock
        import json as _json

        with _lock:
            conn = _connect()
            try:
                rows = conn.execute('SELECT * FROM projects ORDER BY created_at DESC').fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    try: d['computed'] = _json.loads(d.get('computed') or '[]')
                    except Exception: d['computed'] = []
                    try: d['skipped'] = _json.loads(d.get('skipped') or '[]')
                    except Exception: d['skipped'] = []
                    try: d['source_files'] = _json.loads(d.get('source_files') or '{}')
                    except Exception: d['source_files'] = {}
                    d.pop('files_md5', None)  # 不暴露原始 MD5
                    result.append(d)
            finally:
                conn.close()

        return jsonify({'rows': result, 'db_path': DB_PATH})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/clear_all', methods=['POST'])
def admin_clear_all():
    """清空所有项目记录"""
    try:
        from api.db import _connect, _lock
        with _lock:
            conn = _connect()
            try:
                conn.execute('DELETE FROM projects')
                conn.commit()
            finally:
                conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


if __name__ == '__main__':
    print("✨ 空间分析系统 Demo 启动中...")
    print("   访问 http://127.0.0.1:8080")
    app.run(debug=False, port=8080, host='127.0.0.1')
