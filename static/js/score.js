/* SpaceLens — 评分页面前端逻辑 */
(function () {
  'use strict';

  // ── 工具 ──
  function $(id) { return document.getElementById(id); }
  function getSid() {
    var m = location.search.match(/[?&]sid=([^&]+)/);
    return m ? decodeURIComponent(m[1]) : null;
  }

  function gradePill(score) {
    if (score == null) return '<span class="score-pill" style="background:#ccc">N/A</span>';
    if (score >= 85) return '<span class="score-pill excellent">' + score.toFixed(1) + ' 优秀</span>';
    if (score >= 70) return '<span class="score-pill good">' + score.toFixed(1) + ' 良好</span>';
    if (score >= 60) return '<span class="score-pill fair">' + score.toFixed(1) + ' 一般</span>';
    return '<span class="score-pill poor">' + score.toFixed(1) + ' 存在问题</span>';
  }

  function smallPill(score) {
    if (score == null) return '<span class="score-pill" style="background:#eee;color:#888">--</span>';
    if (score >= 85) return '<span class="score-pill excellent">' + score.toFixed(1) + '</span>';
    if (score >= 70) return '<span class="score-pill good">' + score.toFixed(1) + '</span>';
    if (score >= 60) return '<span class="score-pill fair">' + score.toFixed(1) + '</span>';
    return '<span class="score-pill poor">' + score.toFixed(1) + '</span>';
  }

  // ── 状态 ──
  var SID = getSid();
  var DEFAULT_WEIGHTS = {
    subjective: 0.40,
    physical: 0.20,
    circulation: 0.20,
    behavior: 0.20,
  };
  var DIM_LABELS = {
    subjective: '主观心理感知',
    physical: '物理环境感知',
    circulation: '动线感知',
    behavior: '行为感知',
  };
  var DIM_ORDER = ['subjective', 'physical', 'circulation', 'behavior'];
  var currentWeights = Object.assign({}, DEFAULT_WEIGHTS);
  var _lastFolderName = '';

  // ── 主题切换 ──
  (function bindTheme() {
    var btn = $('theme-toggle');
    if (!btn) return;
    btn.addEventListener('click', function () {
      var cur = document.documentElement.getAttribute('data-theme') || 'light';
      var next = cur === 'light' ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('theme', next);
      recompute();
    });
  })();

  // ── 权重表单 ──
  function renderWeightsForm() {
    var form = $('weights-form');
    if (!form) return;
    form.innerHTML = '';
    DIM_ORDER.forEach(function (key) {
      var wrap = document.createElement('div');
      wrap.className = 'weight-input';
      wrap.innerHTML =
        '<label for="w-' + key + '">' + DIM_LABELS[key] + ' (W)</label>' +
        '<input id="w-' + key + '" type="number" min="0" max="1" step="0.05" value="' +
        currentWeights[key].toFixed(2) + '">';
      form.appendChild(wrap);
    });
    updateWeightSumHint();
    DIM_ORDER.forEach(function (key) {
      $('w-' + key).addEventListener('input', updateWeightSumHint);
    });
  }

  function readWeights() {
    var w = {};
    DIM_ORDER.forEach(function (key) {
      var v = parseFloat($('w-' + key).value);
      w[key] = isNaN(v) ? 0 : v;
    });
    return w;
  }

  function updateWeightSumHint() {
    var w = readWeights();
    var sum = DIM_ORDER.reduce(function (s, k) { return s + w[k]; }, 0);
    var hint = $('weight-sum-hint');
    if (Math.abs(sum - 1.0) < 0.001) {
      hint.style.color = '#00c9a7';
      hint.textContent = '当前权重总和：' + sum.toFixed(2) + ' ✓（归一化）';
    } else {
      hint.style.color = '#f5a623';
      hint.textContent = '当前权重总和：' + sum.toFixed(2) +
        '（提交时会按比例归一化使用）';
    }
  }

  function resetWeights() {
    currentWeights = Object.assign({}, DEFAULT_WEIGHTS);
    renderWeightsForm();
    recompute();
  }
  window.resetWeights = resetWeights;

  // ── 拉取与渲染 ──
  function recompute() {
    currentWeights = readWeights();
    $('loading-state').style.display = 'block';
    $('score-content').style.display = 'none';
    $('error-state').style.display = 'none';
    var theme = document.documentElement.getAttribute('data-theme') || 'light';
    fetch('/api/score/' + SID, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ahp_weights: currentWeights, theme: theme }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        $('loading-state').style.display = 'none';
        if (data.error) {
          $('error-state').style.display = 'block';
          $('error-message').innerHTML =
            '<div>' + (data.error || '未知错误') + '</div>' +
            (data.traceback ? '<pre style="margin-top:10px;font-size:11px;color:#888;white-space:pre-wrap;max-height:240px;overflow:auto">' +
              data.traceback + '</pre>' : '');
          return;
        }
        renderScore(data);
      })
      .catch(function (err) {
        $('loading-state').style.display = 'none';
        $('error-state').style.display = 'block';
        $('error-message').textContent = '请求失败：' + err.message;
      });
  }
  window.recompute = recompute;

  function setImg(id, b64) {
    var el = $(id);
    if (!el) return;
    if (b64) {
      el.src = 'data:image/png;base64,' + b64;
      el.style.display = '';
    } else {
      el.style.display = 'none';
    }
  }

  function renderScore(data) {
    var s = data.score;
    // Topbar 项目名
    if (data.project_name) {
      $('topbar-project-title').style.display = '';
      $('topbar-project-text').textContent = data.project_name +
        (data.folder_name ? '  ·  ' + data.folder_name : '');
    }
    $('status-text').textContent = '评分完成 · 总分 ' + (s.total_score != null ? s.total_score.toFixed(1) : '--');

    // 保存按钮：评分计算成功就显示
    var saveBtn = $('save-score-btn');
    if (saveBtn) saveBtn.style.display = 'inline-flex';

    // 缓存最近的项目名（保存模态默认值）
    _lastFolderName = data.folder_name || '';

    // 图
    var imgs = data.images || {};
    setImg('img-total', imgs.image_total);
    setImg('img-radar', imgs.image_radar);
    setImg('img-dim-bar', imgs.image_dim_bar);
    setImg('img-metric-bar', imgs.image_metric_bar);
    setImg('img-region-bar', imgs.image_region_bar);
    setImg('img-region-heatmap', imgs.image_region_heatmap);

    // 维度方块
    var dimGrid = $('dim-grid');
    dimGrid.innerHTML = '';
    DIM_ORDER.forEach(function (k) {
      var d = s.dimensions[k] || {};
      var tile = document.createElement('div');
      tile.className = 'dim-tile ' + k;
      var sc = d.score;
      tile.innerHTML =
        '<div class="name">' + (d.label || DIM_LABELS[k]) + '</div>' +
        '<div class="num">' + (sc != null ? sc.toFixed(1) : '--') +
        '<span class="unit"> / 100</span></div>' +
        '<div class="meta">权重 ' + (d.weight != null ? d.weight.toFixed(2) : '--') +
        ' · ' + (sc != null ? (sc >= 85 ? '优秀' : sc >= 70 ? '良好' : sc >= 60 ? '一般' : '存在问题') : '无数据') + '</div>';
      dimGrid.appendChild(tile);
    });

    // 各维度指标贡献明细
    var bdEl = $('dim-breakdown');
    bdEl.innerHTML = '';
    DIM_ORDER.forEach(function (k) {
      var d = s.dimensions[k] || {};
      var bd = (d.breakdown && d.breakdown.metrics) || [];
      if (!bd.length && k !== 'subjective') return;
      var box = document.createElement('div');
      box.style.marginBottom = '20px';
      var header = '<div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:8px">' +
        DIM_LABELS[k] + '（维度得分 ' +
        (d.score != null ? d.score.toFixed(1) : '--') +
        '，权重 ' + (d.weight != null ? d.weight.toFixed(2) : '--') +
        '）</div>';
      var tbl = '<table class="metric-table"><thead><tr>' +
        '<th>指标</th><th>标准化得分</th><th>权重 ω</th><th>惩罚 P</th><th>加权贡献</th>' +
        '</tr></thead><tbody>';
      bd.forEach(function (r) {
        var label = (s.metric_labels && s.metric_labels[r.metric]) || r.metric;
        tbl += '<tr>' +
          '<td>' + label + '</td>' +
          '<td class="score-cell">' + smallPill(r.score) + '</td>' +
          '<td>' + (r.weight != null ? r.weight.toFixed(4) : '--') + '</td>' +
          '<td>' + (r.penalty != null ? r.penalty.toFixed(2) : '--') + '</td>' +
          '<td><strong>' + (r.weighted != null ? r.weighted.toFixed(2) : '--') + '</strong></td>' +
          '</tr>';
      });
      tbl += '</tbody></table>';
      // 主观维度补充模型说明
      if (k === 'subjective' && d.breakdown && d.breakdown.subjective_model) {
        var m = d.breakdown.subjective_model;
        tbl += '<div style="margin-top:8px;font-size:12px;color:var(--text-muted)">' +
          '回归模型：S_predicted = ' + m.a + ' + ' + m.beta1 + '·S_zone + ' + m.beta2 + '·S_element；' +
          '融合系数 α = ' + m.alpha + '<br>' +
          'S_overall = ' + (m.S_overall != null ? m.S_overall : '--') +
          '，S_zone = ' + (m.S_zone != null ? m.S_zone : '--') +
          '，S_element = ' + (m.S_element != null ? m.S_element : '--') +
          '，S_predicted = ' + m.S_predicted +
          '</div>';
      }
      box.innerHTML = header + tbl;
      bdEl.appendChild(box);
    });

    // 空间区域评分
    var regions = s.region_scores || [];
    if (regions.length > 0) {
      $('region-section').style.display = '';
      var rt = $('region-table');
      var html = '<thead><tr>' +
        '<th>排名</th><th>空间区域</th><th>综合得分</th><th>分级</th>';
      DIM_ORDER.forEach(function (k) {
        html += '<th>' + DIM_LABELS[k] + '</th>';
      });
      html += '</tr></thead><tbody>';
      regions.slice(0, 50).forEach(function (r, i) {
        html += '<tr>' +
          '<td>#' + (i + 1) + '</td>' +
          '<td>' + (r.region || '--') + '</td>' +
          '<td><strong>' + (r.total_score != null ? r.total_score.toFixed(1) : '--') + '</strong></td>' +
          '<td>' + gradePill(r.total_score) + '</td>';
        DIM_ORDER.forEach(function (k) {
          html += '<td>' + smallPill((r.dimensions || {})[k]) + '</td>';
        });
        html += '</tr>';
      });
      html += '</tbody>';
      rt.innerHTML = html;
    } else {
      $('region-section').style.display = 'none';
    }

    $('score-content').style.display = '';
  }

  // ── 入口 ──
  if (!SID) {
    $('loading-state').style.display = 'none';
    $('error-state').style.display = 'block';
    $('error-message').innerHTML =
      '缺少 session id。<br>请从 <a href="/results" style="color:var(--accent)">23 指标结果页</a> 进入评分。';
  } else {
    renderWeightsForm();
    recompute();
  }

  // ── 侧边栏 TOC：点击平滑滚动 + 滚动 spy 高亮 ──
  function setupToc() {
    var links = document.querySelectorAll('.score-toc-link[data-anchor]');
    if (!links.length) return;
    links.forEach(function (a) {
      a.addEventListener('click', function (ev) {
        ev.preventDefault();
        var anchor = a.getAttribute('data-anchor');
        var target = document.getElementById(anchor);
        if (target) {
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      });
    });

    function onScroll() {
      var scrollY = window.scrollY || document.documentElement.scrollTop;
      var best = null;
      var bestTop = -Infinity;
      links.forEach(function (a) {
        var anchor = a.getAttribute('data-anchor');
        var target = document.getElementById(anchor);
        if (!target) return;
        var top = target.getBoundingClientRect().top + scrollY - 120;
        if (top <= scrollY && top > bestTop) {
          bestTop = top;
          best = a;
        }
      });
      links.forEach(function (a) { a.classList.remove('active'); });
      if (best) best.classList.add('active');
    }
    window.addEventListener('scroll', onScroll, { passive: true });
  }
  setupToc();

  // ── 保存模态：默认两项都勾选；自动按选择决定 include_score/score_only ──
  function openSaveModal() {
    if (!SID) { alert('未找到会话 ID，无法保存'); return; }
    var ov = $('sp-overlay');
    if (!ov) return;
    $('sp-folder-input').value = _lastFolderName || ('评分_' + new Date().toISOString().slice(0, 10));
    $('sp-opt-23').checked = true;
    $('sp-opt-score').checked = true;
    updateSaveHint();
    ov.style.display = 'flex';
  }
  function closeSaveModal() {
    var ov = $('sp-overlay');
    if (ov) ov.style.display = 'none';
  }
  function closeSaveModalOutside(e) {
    if (e.target && e.target.id === 'sp-overlay') closeSaveModal();
  }
  function updateSaveHint() {
    var o23 = $('sp-opt-23').checked;
    var os  = $('sp-opt-score').checked;
    var hint = $('sp-hint');
    var warn = $('sp-warn');
    var btn  = $('sp-save-btn');
    if (!o23 && !os) {
      hint.textContent = '请选择导出内容';
      warn.style.display = 'block';
      btn.disabled = true;
      return;
    }
    warn.style.display = 'none';
    btn.disabled = false;
    if (o23 && os) hint.textContent = '将导出 23 指标 + 评分';
    else if (o23)  hint.textContent = '将导出 23 指标结果';
    else           hint.textContent = '将单独导出评分结果';
  }
  ['sp-opt-23', 'sp-opt-score'].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('change', updateSaveHint);
  });

  function doSaveProject() {
    var o23 = $('sp-opt-23').checked;
    var os  = $('sp-opt-score').checked;
    if (!o23 && !os) { updateSaveHint(); return; }

    var folder = ($('sp-folder-input').value || '').trim() || 'SpaceLens项目';
    var btn = $('sp-save-btn');
    btn.disabled = true;
    btn.innerHTML = '<div class="sp-saving-spinner"></div> 打包中…';

    var body = {
      folder_name: folder,
      include_score: o23 && os,
      score_only: !o23 && os,
      ahp_weights: readWeights(),
    };
    // 23 指标导出：默认全部已计算的（metrics=null）

    fetch('/api/save_project/' + SID, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.cancelled) return;
        if (data.error) throw new Error(data.error);
        closeSaveModal();
        var st = $('status-text');
        if (st) {
          var prev = st.textContent;
          st.textContent = '✓ 已保存至：' + (data.path || '本地文件');
          st.style.color = 'var(--success, #22c55e)';
          setTimeout(function () {
            st.textContent = prev;
            st.style.color = '';
          }, 5000);
        }
      })
      .catch(function (err) {
        // 桌面端原生对话框不可用时，降级到浏览器下载
        if (err && err.message && err.message.indexOf('文件对话框') >= 0) {
          fallbackBrowserDownload(body);
        } else {
          alert('保存失败：' + (err && err.message ? err.message : err));
        }
      })
      .finally(function () {
        btn.disabled = false;
        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> 保存到本地';
      });
  }

  function fallbackBrowserDownload(body) {
    fetch('/api/export_project/' + SID, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function (r) {
      if (!r.ok) return r.json().then(function (j) { throw new Error(j.error || ('HTTP ' + r.status)); });
      return r.blob().then(function (b) {
        var url = URL.createObjectURL(b);
        var a = document.createElement('a');
        a.href = url;
        var suffix = body.score_only ? '_评分结果' : (body.include_score ? '_评价与评分结果' : '_评价结果');
        a.download = (body.folder_name || 'SpaceLens项目') + suffix + '.zip';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        closeSaveModal();
      });
    }).catch(function (err) {
      alert('保存失败：' + (err && err.message ? err.message : err));
    });
  }

  window.openSaveModal = openSaveModal;
  window.closeSaveModal = closeSaveModal;
  window.closeSaveModalOutside = closeSaveModalOutside;
  window.doSaveProject = doSaveProject;
})();
