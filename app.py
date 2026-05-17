"""
空间分析系统 Demo - Flask 主程序
"""

from flask import Flask, render_template, send_from_directory
from api.analysis import analysis_bp
import os

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB

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


@app.route('/new_project')
def new_project():
    return render_template('new_project.html')


if __name__ == '__main__':
    print("✨ 空间分析系统 Demo 启动中...")
    print("   访问 http://127.0.0.1:8080")
    app.run(debug=False, port=8080, host='127.0.0.1')
