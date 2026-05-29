"""Sanity smoke for the analysis blueprint: makes sure the Flask app boots
and the analysis blueprint is registered. Heavy endpoint integration tests
should go in dedicated files under `tests/integration/`.
"""
import pytest

flask = pytest.importorskip('flask')


def _make_app():
    from api.analysis import analysis_bp
    app = flask.Flask(__name__)
    app.register_blueprint(analysis_bp, url_prefix='/api')
    return app


def test_blueprint_registers_without_errors():
    app = _make_app()
    rules = {r.rule for r in app.url_map.iter_rules()}
    # 至少这些核心 endpoint 应该都在
    expected_any = {'/api/heatmap', '/api/trajectory', '/api/cluster'}
    assert expected_any.issubset(rules), f"Missing endpoints: {expected_any - rules}"


def test_heatmap_rejects_missing_files():
    app = _make_app()
    client = app.test_client()
    resp = client.post('/api/heatmap', data={})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body and 'error' in body
