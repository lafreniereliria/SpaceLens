/* ─────────────────────────────────────────────
   SpaceLens v2.0 — App Logic
───────────────────────────────────────────── */

// ─── View definitions ───
const VIEWS = {
  // ── A: 定位分析 ──
  heatmap: {
    title: '到访频次热力图', subtitle: '统计各区域人员到访密度，生成热力分布图',
    chartTitle: '热力图 & 区域频次', endpoint: '/api/heatmap',
    dataTypes: ['img', 'loc'],
    stats: [
      { key: 'total_records', label: '总记录数', unit: '条', cls: '' },
      { key: 'unique_users', label: '唯一用户数', unit: '人', cls: 'teal' },
      { key: 'peak_frequency', label: '峰值频次', unit: '次', cls: 'accent' },
      { key: 'covered_area_pct', label: '覆盖栅格', unit: '%', cls: 'amber' },
    ]
  },
  usetime: {
    title: '使用时长分析', subtitle: '统计各区域人员累计使用时长分布',
    chartTitle: '使用时长热力图 & 区域统计', endpoint: '/api/usetime',
    dataTypes: ['img', 'loc'],
    stats: [
      { key: 'total_records', label: '总记录数', unit: '条', cls: '' },
      { key: 'total_duration_s', label: '总使用时长', unit: 's', cls: 'teal' },
      { key: 'avg_duration_s', label: '平均时长', unit: 's', cls: 'accent' },
      { key: 'max_duration_s', label: '最大时长', unit: 's', cls: '' },
      { key: 'min_duration_s', label: '最小时长', unit: 's', cls: 'amber' },
    ]
  },
  speed: {
    title: '移动速率分析', subtitle: '计算各区域人员平均移动速率热力图',
    chartTitle: '移动速率热力图 & 区域统计', endpoint: '/api/speed',
    dataTypes: ['img', 'loc'],
    stats: [
      { key: 'total_records', label: '总记录数', unit: '条', cls: '' },
      { key: 'global_speed_ms', label: '全局均速', unit: 'm/s', cls: 'teal' },
      { key: 'avg_speed_ms', label: '区域均速', unit: 'm/s', cls: 'accent' },
      { key: 'max_speed_ms', label: '最高速率', unit: 'm/s', cls: '' },
      { key: 'min_speed_ms', label: '最低速率', unit: 'm/s', cls: 'amber' },
    ]
  },
  duration: {
    title: '停留时长分析', subtitle: '统计各区域人员停留时长热力分布',
    chartTitle: '停留时长热力图 & 区域统计', endpoint: '/api/duration',
    dataTypes: ['img', 'loc'],
    stats: [
      { key: 'total_records', label: '总记录数', unit: '条', cls: '' },
      { key: 'total_dwell_s', label: '总停留时长', unit: 's', cls: 'teal' },
      { key: 'avg_dwell_s', label: '平均停留', unit: 's', cls: 'accent' },
      { key: 'max_dwell_s', label: '最长停留', unit: 's', cls: '' },
      { key: 'min_dwell_s', label: '最短停留', unit: 's', cls: 'amber' },
    ]
  },
  cluster: {
    title: '空间聚类分析', subtitle: 'K-means 算法识别空间使用热点区域',
    chartTitle: '聚类分布图 & 各簇点位数', endpoint: '/api/cluster',
    dataTypes: ['img', 'loc', 'cluster_k'],
    stats: [
      { key: 'k', label: '聚类数', unit: '簇', cls: 'accent' },
      { key: 'total_points', label: '总点位数', unit: '个', cls: '' },
      { key: 'inertia', label: '簇内离散度', unit: '', cls: 'amber' },
    ]
  },
  density: {
    title: '人员密度分析', subtitle: '统计各区域独立到访人员数量分布',
    chartTitle: '人员分布热力图 & 区域统计', endpoint: '/api/density',
    dataTypes: ['img', 'loc'],
    stats: [
      { key: 'total_records', label: '总记录数', unit: '条', cls: '' },
      { key: 'unique_users', label: '独立人员数', unit: '人', cls: 'teal' },
      { key: 'avg_density', label: '平均人员数', unit: '人', cls: 'accent' },
      { key: 'max_density', label: '最大人员数', unit: '人', cls: '' },
      { key: 'min_density', label: '最小人员数', unit: '人', cls: 'amber' },
    ]
  },
  openness: {
    title: '空间开放程度', subtitle: '计算各区域人均面积利用率（人/㎡）',
    chartTitle: '开放程度热力图 & 区域统计', endpoint: '/api/openness',
    dataTypes: ['img', 'loc', 'region'],
    stats: [
      { key: 'unique_users', label: '独立人员数', unit: '人', cls: '' },
      { key: 'global_openness', label: '全局开放度', unit: '人/㎡', cls: 'teal' },
      { key: 'avg_openness', label: '平均开放度', unit: '人/㎡', cls: 'accent' },
      { key: 'max_openness', label: '最大开放度', unit: '人/㎡', cls: '' },
      { key: 'min_openness', label: '最小开放度', unit: '人/㎡', cls: 'amber' },
    ]
  },
  topology: {
    title: '拓扑连接关系', subtitle: '分析区域间人员流转关系与连接强度',
    chartTitle: '转移矩阵 & 流入/流出量', endpoint: '/api/topology',
    dataTypes: ['loc'],
    stats: [
      { key: 'region_count', label: '区域数', unit: '个', cls: '' },
      { key: 'total_transitions', label: '总转移次数', unit: '次', cls: 'teal' },
      { key: 'avg_in_flow', label: '平均流入量', unit: '次', cls: 'accent' },
      { key: 'max_in_flow', label: '最大流入量', unit: '次', cls: '' },
      { key: 'avg_out_flow', label: '平均流出量', unit: '次', cls: 'amber' },
    ]
  },
  difference: {
    title: '轨迹差异系数', subtitle: '比较人员与区域轨迹长度离散程度',
    chartTitle: '人员差异系数 & 区域差异系数', endpoint: '/api/difference',
    dataTypes: ['img', 'loc'],
    stats: [
      { key: 'total_users', label: '人员数', unit: '人', cls: '' },
      { key: 'avg_length_m', label: '平均轨迹长', unit: 'm', cls: 'teal' },
      { key: 'region_count', label: '区域数', unit: '个', cls: 'accent' },
    ]
  },
  trajectory: {
    title: '轨迹长度分析', subtitle: '可视化每位人员的移动路径与轨迹长度',
    chartTitle: '轨迹图 & 长度排行', endpoint: '/api/trajectory',
    dataTypes: ['img', 'loc'],
    stats: [
      { key: 'total_users', label: '分析人员数', unit: '人', cls: 'teal' },
      { key: 'avg_length_m', label: '平均轨迹长', unit: 'm', cls: '' },
      { key: 'max_length_m', label: '最长轨迹', unit: 'm', cls: 'accent' },
      { key: 'min_length_m', label: '最短轨迹', unit: 'm', cls: 'amber' },
    ]
  },
  // ── B: 环境分析 ──
  environment: {
    title: '环境参数分析', subtitle: '显示温度/湿度/光照/风速/噪声空间分布',
    chartTitle: '环境参数分布图', endpoint: '/api/environment',
    dataTypes: ['img', 'env', 'env_param'],
    stats: [
      { key: 'param', label: '参数类型', unit: '', cls: '' },
      { key: 'num_points', label: '测点数', unit: '个', cls: 'teal' },
      { key: 'mean', label: '均值', unit: '', cls: 'accent' },
      { key: 'max', label: '最大值', unit: '', cls: 'amber' },
    ]
  },
  // ── C: 行为分析 ──
  behavior_count: {
    title: '行为发生人次', subtitle: '统计各区域不同行为类型的发生人次',
    chartTitle: '行为分布散点 & 各区域人次', endpoint: '/api/behavior_count',
    dataTypes: ['img', 'behavior'],
    stats: [
      { key: 'total_records', label: '总记录数', unit: '条', cls: '' },
      { key: 'behavior_types', label: '行为类型数', unit: '种', cls: 'teal' },
      { key: 'region_count', label: '区域数', unit: '个', cls: 'accent' },
    ]
  },
  behavior_duration: {
    title: '行为时长分析', subtitle: '统计各区域不同行为的累计时长',
    chartTitle: '行为时长热力图 & 区域统计', endpoint: '/api/behavior_duration',
    dataTypes: ['img', 'behavior'],
    stats: [
      { key: 'total_records', label: '总记录数', unit: '条', cls: '' },
      { key: 'total_duration_s', label: '总行为时长', unit: 's', cls: 'teal' },
      { key: 'behavior_types', label: '行为类型数', unit: '种', cls: 'accent' },
    ]
  },
  behavior_rate: {
    title: '行为发生率', subtitle: '各区域不同行为的时间占比',
    chartTitle: '行为发生率 (堆叠 & 分组)', endpoint: '/api/behavior_rate',
    dataTypes: ['behavior'],
    stats: [
      { key: 'total_records', label: '总记录数', unit: '条', cls: '' },
      { key: 'behavior_types', label: '行为类型数', unit: '种', cls: 'teal' },
      { key: 'region_count', label: '区域数', unit: '个', cls: 'accent' },
    ]
  },
  behavior_entropy: {
    title: '行为复合度', subtitle: '用信息熵衡量区域/人员行为多样性',
    chartTitle: '区域 & 使用者行为复合度', endpoint: '/api/behavior_entropy',
    dataTypes: ['behavior'],
    stats: [
      { key: 'region_count', label: '区域数', unit: '个', cls: '' },
      { key: 'user_count', label: '人员数', unit: '人', cls: 'teal' },
      { key: 'avg_reg_entropy', label: '区域平均熵', unit: 'bits', cls: 'accent' },
      { key: 'max_reg_entropy', label: '最大熵', unit: 'bits', cls: '' },
      { key: 'min_reg_entropy', label: '最小熵', unit: 'bits', cls: 'amber' },
    ]
  },
  utilization: {
    title: '功能利用率', subtitle: '各区域单位面积行为时长（s/㎡）',
    chartTitle: '功能利用率堆叠 & 总量', endpoint: '/api/utilization',
    dataTypes: ['behavior', 'region'],
    stats: [
      { key: 'region_count', label: '区域数', unit: '个', cls: '' },
      { key: 'behavior_types', label: '行为类型数', unit: '种', cls: 'teal' },
      { key: 'avg_util', label: '平均利用率', unit: 's/㎡', cls: 'accent' },
      { key: 'max_util', label: '最高利用率', unit: 's/㎡', cls: '' },
      { key: 'min_util', label: '最低利用率', unit: 's/㎡', cls: 'amber' },
    ]
  },
  // ── D: 满意度 ──
  satisfaction: {
    title: '整体满意度', subtitle: '各人员对空间的整体满意度评分分布',
    chartTitle: '个人评分 & 分数分布', endpoint: '/api/satisfaction',
    dataTypes: ['ques'],
    stats: [
      { key: 'total_users', label: '有效问卷数', unit: '份', cls: '' },
      { key: 'avg_score', label: '平均满意度', unit: '分', cls: 'teal' },
      { key: 'max_score', label: '最高分', unit: '分', cls: 'accent' },
      { key: 'min_score', label: '最低分', unit: '分', cls: 'amber' },
    ]
  },
  satisfaction_region: {
    title: '空间区域满意度', subtitle: '各空间区域的平均满意度评分与雷达图',
    chartTitle: '区域满意度柱图 & 雷达图', endpoint: '/api/satisfaction_region',
    dataTypes: ['ques'],
    stats: [
      { key: 'region_count', label: '评价区域数', unit: '个', cls: '' },
      { key: 'avg_score', label: '区域均值', unit: '分', cls: 'teal' },
      { key: 'best_region', label: '最满意区域', unit: '', cls: 'accent' },
      { key: 'worst_region', label: '最低分区域', unit: '', cls: 'amber' },
    ]
  },
  satisfaction_design: {
    title: '设计要素满意度', subtitle: '各设计要素的平均满意度评分与雷达图',
    chartTitle: '设计要素满意度柱图 & 雷达图', endpoint: '/api/satisfaction_design',
    dataTypes: ['ques'],
    stats: [
      { key: 'factor_count', label: '设计要素数', unit: '项', cls: '' },
      { key: 'avg_score', label: '要素均值', unit: '分', cls: 'teal' },
      { key: 'best_factor', label: '最高分要素', unit: '', cls: 'accent' },
      { key: 'worst_factor', label: '最低分要素', unit: '', cls: 'amber' },
    ]
  },
};

// 需要平面图的视图
const NEEDS_IMG = new Set(['heatmap','usetime','speed','duration','cluster','density',
  'openness','difference','trajectory','environment','behavior_count','behavior_duration']);
// 需要定位数据的视图
const NEEDS_LOC = new Set(['heatmap','usetime','speed','duration','cluster','density',
  'openness','topology','difference','trajectory']);
// 需要行为数据
const NEEDS_BEH = new Set(['behavior_count','behavior_duration','behavior_rate','behavior_entropy','utilization']);
// 需要环境数据
const NEEDS_ENV = new Set(['environment']);
// 需要问卷数据
const NEEDS_QUES = new Set(['satisfaction','satisfaction_region','satisfaction_design']);

function getQuestionnaireInputKey(view) {
  if (view === 'satisfaction') return 'overall';
  if (view === 'satisfaction_region') return 'region';
  if (view === 'satisfaction_design') return 'design';
  return null;
}
// 需要区域坐标（可选）
const NEEDS_REGION = new Set(['openness','utilization']);

let currentView = 'heatmap';
let kValue = 5;

// ─── Engine Ready（分析引擎后台预热）───
let _engineReady = false;

function startEngineReadyPoller() {
  const runBtn = document.getElementById('run-btn');
  const originalText = runBtn ? runBtn.textContent : '开始分析';

  function setEngineReady() {
    _engineReady = true;
    if (runBtn) {
      runBtn.disabled = false;
      runBtn.textContent = originalText;
      runBtn.title = '';
    }
  }

  function poll() {
    fetch('/api/ready')
      .then(r => r.json())
      .then(data => {
        if (data.ready) {
          setEngineReady();
        } else {
          setTimeout(poll, 800);
        }
      })
      .catch(() => {
        // Flask 还没就绪，继续轮询
        setTimeout(poll, 1000);
      });
  }

  // 先禁用按钮，开始轮询
  if (runBtn) {
    runBtn.disabled = true;
    runBtn.textContent = '引擎加载中…';
    runBtn.title = '分析引擎正在初始化，请稍候';
  }
  poll();
}

// ─── Init ───
document.addEventListener('DOMContentLoaded', () => {
  bindNav();
  bindUploads();
  bindRunBtn();
  bindDownload();
  bindThemeToggle();
  bindColorSettings();
  restoreAccentColor();
  // 界面加载完立即开始后台轮询引擎就绪状态
  startEngineReadyPoller();
});

// ─── Theme Toggle ───
function bindThemeToggle() {
  const btn = document.getElementById('theme-toggle');
  const html = document.documentElement;
  const saved = localStorage.getItem('theme') || 'light';
  html.setAttribute('data-theme', saved);
  btn.addEventListener('click', () => {
    const current = html.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
  });
}

// ─── Accent Color Settings ───
const PRESET_COLORS = [
  '#7c5cfc', '#6366f1', '#3b82f6', '#0ea5e9', '#06b6d4',
  '#10b981', '#22c55e', '#84cc16', '#eab308', '#f59e0b',
  '#ef4444', '#ec4899', '#d946ef', '#a855f7', '#8b5cf6'
];

function bindColorSettings() {
  const btn = document.getElementById('color-settings-btn');
  const panel = document.getElementById('color-panel');
  const closeBtn = document.getElementById('color-panel-close');
  const swatchesEl = document.getElementById('color-swatches');
  const customInput = document.getElementById('custom-color');

  // 确保初始状态是隐藏
  panel.style.display = 'none';

  // 渲染预设色板
  PRESET_COLORS.forEach(color => {
    const div = document.createElement('div');
    div.className = 'color-swatch';
    div.style.backgroundColor = color;
    div.style.color = color;
    div.dataset.color = color;
    swatchesEl.appendChild(div);
  });

  // 点击设置按钮切换面板
  btn.onclick = (e) => {
    e.stopPropagation();
    const isVisible = panel.style.display === 'block';
    panel.style.display = isVisible ? 'none' : 'block';
  };

  // 关闭按钮
  closeBtn.onclick = () => {
    panel.style.display = 'none';
  };

  // 预设色选择
  swatchesEl.onclick = e => {
    if (e.target.classList.contains('color-swatch')) {
      setAccentColor(e.target.dataset.color);
      updateSwatchActive(e.target);
    }
  };

  // 自定义颜色
  customInput.oninput = e => {
    setAccentColor(e.target.value);
    clearSwatchActive();
  };

  // 点击外部关闭 - 使用 setTimeout 避免立即触发
  setTimeout(() => {
    document.body.onclick = e => {
      if (!panel.contains(e.target) && e.target !== btn) {
        panel.style.display = 'none';
      }
    };
  }, 100);
}

function setAccentColor(hex) {
  const rgb = hexToRgb(hex);
  document.documentElement.style.setProperty('--accent', hex);
  document.documentElement.style.setProperty('--accent-rgb', `${rgb.r},${rgb.g},${rgb.b}`);
  localStorage.setItem('accentColor', hex);
}

const DEFAULT_ACCENT = '#0ea5e9'; // sky blue

function restoreAccentColor() {
  const saved = localStorage.getItem('accentColor') || DEFAULT_ACCENT;
  const rgb = hexToRgb(saved);
  document.documentElement.style.setProperty('--accent', saved);
  document.documentElement.style.setProperty('--accent-rgb', `${rgb.r},${rgb.g},${rgb.b}`);
  // 更新选中状态
  document.querySelectorAll('.color-swatch').forEach(el => {
    el.classList.toggle('active', el.dataset.color === saved);
  });
}

function updateSwatchActive(target) {
  document.querySelectorAll('.color-swatch').forEach(el => el.classList.remove('active'));
  target.classList.add('active');
}

function clearSwatchActive() {
  document.querySelectorAll('.color-swatch').forEach(el => el.classList.remove('active'));
}

function hexToRgb(hex) {
  const r = parseInt(hex.slice(1,3), 16);
  const g = parseInt(hex.slice(3,5), 16);
  const b = parseInt(hex.slice(5,7), 16);
  return { r, g, b };
}

// ─── Nav ───
function bindNav() {
  document.querySelectorAll('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => {
      const view = btn.dataset.view;
      if (view === currentView) return;
      currentView = view;
      document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const cfg = VIEWS[view];
      document.getElementById('page-title').textContent = cfg.title;
      document.getElementById('page-subtitle').textContent = cfg.subtitle;
      updateUploadCards(view);
      hideResult();
    });
  });
}

function updateUploadCards(view) {
  const types = VIEWS[view].dataTypes || [];
  // 平面图
  toggle('drop-img', NEEDS_IMG.has(view));
  // 定位数据
  toggle('drop-loc', NEEDS_LOC.has(view));
  // 行为数据
  toggle('drop-behavior', NEEDS_BEH.has(view));
  // 环境数据
  toggle('drop-env', NEEDS_ENV.has(view));
  // 问卷数据
  toggle('drop-ques', NEEDS_QUES.has(view));
  // 区域坐标（可选）
  toggle('drop-region', NEEDS_REGION.has(view));
  // 聚类参数
  toggle('cluster-param', view === 'cluster');
  // 环境参数选择
  toggle('env-param', view === 'environment');
}

function toggle(id, show) {
  const el = document.getElementById(id);
  if (el) el.style.display = show ? 'flex' : 'none';
}

// ─── Uploads ───
function bindUploads() {
  bindFile('drop-img', 'input-img', 'fname-img');
  bindFile('drop-loc', 'input-loc', 'fname-loc');
  bindFile('drop-behavior', 'input-behavior', 'fname-behavior');
  bindFile('drop-env', 'input-env', 'fname-env');
  bindFile('drop-ques', 'input-ques', 'fname-ques');
  bindFile('drop-region', 'input-region', 'fname-region');
}

function bindFile(dropId, inputId, nameId) {
  const drop = document.getElementById(dropId);
  const input = document.getElementById(inputId);
  const nameEl = document.getElementById(nameId);
  if (!drop || !input) return;

  drop.addEventListener('click', () => input.click());
  input.addEventListener('change', () => {
    if (input.files[0]) {
      nameEl.textContent = input.files[0].name;
      nameEl.setAttribute('title', input.files[0].name);
      nameEl.setAttribute('data-full-text', input.files[0].name);
      drop.classList.add('has-file');
    }
  });
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag-over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('drag-over'));
  drop.addEventListener('drop', e => {
    e.preventDefault(); drop.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (!file) return;
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    nameEl.textContent = file.name;
    nameEl.setAttribute('title', file.name);
    nameEl.setAttribute('data-full-text', file.name);
    drop.classList.add('has-file');
  });
}

// ─── Cluster K ───
function bindClusterK() {
  document.getElementById('k-minus').addEventListener('click', () => {
    if (kValue > 2) { kValue--; document.getElementById('k-val').textContent = kValue; }
  });
  document.getElementById('k-plus').addEventListener('click', () => {
    if (kValue < 12) { kValue++; document.getElementById('k-val').textContent = kValue; }
  });
}

// ─── Run ───
function bindRunBtn() {
  document.getElementById('run-btn').addEventListener('click', runAnalysis);
}

async function runAnalysis() {
  // 双重保险：引擎未就绪则提示等待
  if (!_engineReady) {
    showToast('分析引擎仍在初始化，请稍候...', 'info');
    return;
  }
  const cfg = VIEWS[currentView];
  const fd = new FormData();
  // 附带当前主题和主题色，让后端配色一致
  fd.append('theme', document.documentElement.getAttribute('data-theme') || 'dark');
  const accentColor = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
  fd.append('accent', accentColor);

  // 校验 & 附加文件
  if (NEEDS_IMG.has(currentView)) {
    const f = document.getElementById('input-img').files[0];
    if (!f) { showToast('请上传空间平面图'); return; }
    fd.append('layout_img', f);
    const bgMaskInput = document.getElementById('input-bgmask');
    if (bgMaskInput && bgMaskInput.files[0]) fd.append('background_img', bgMaskInput.files[0]);
  }
  if (NEEDS_LOC.has(currentView)) {
    const f = document.getElementById('input-loc').files[0];
    if (!f) { showToast('请上传定位数据'); return; }
    fd.append('loc_data', f);
  }
  if (NEEDS_BEH.has(currentView)) {
    const f = document.getElementById('input-behavior').files[0];
    if (!f) { showToast('请上传行为数据'); return; }
    fd.append('behavior_data', f);
  }
  if (NEEDS_ENV.has(currentView)) {
    const f = document.getElementById('input-env').files[0];
    if (!f) { showToast('请上传环境数据'); return; }
    fd.append('env_data', f);
    fd.append('param_num', document.getElementById('env-param-select').value);
  }
  if (NEEDS_QUES.has(currentView)) {
    const f = document.getElementById('input-ques').files[0];
    if (!f) { showToast('请上传问卷数据'); return; }
    const qKey = getQuestionnaireInputKey(currentView);
    if (qKey === 'overall') fd.append('ques_data_overall', f);
    else if (qKey === 'region') fd.append('ques_data_region', f);
    else if (qKey === 'design') fd.append('ques_data_design', f);
    else fd.append('ques_data', f);
  }
  if (NEEDS_REGION.has(currentView)) {
    const f = document.getElementById('input-region').files[0];
    if (f) fd.append('region_data', f);  // 可选
  }
  if (currentView === 'cluster') fd.append('k', kValue);
  // 行为时长：是否显示数据点
  if (currentView === 'behavior_duration') {
    const toggle = document.getElementById('show-points-toggle');
    fd.append('show_points', toggle && toggle.checked ? '1' : '0');
  }

  setLoading(true);
  hideResult();

  try {
    const res = await fetch(cfg.endpoint, { method: 'POST', body: fd });
    const data = await res.json();
    if (data.error) { showToast(data.error, 'error'); return; }
    renderResult(data);
  } catch (e) {
    showToast('请求失败：' + e.message, 'error');
  } finally {
    setLoading(false);
  }
}

// ─── Render ───
function renderResult(data) {
  const cfg = VIEWS[currentView];
  document.getElementById('result-section').style.display = 'block';
  document.getElementById('chart-title').textContent = cfg.chartTitle;

  // Stats
  const statsRow = document.getElementById('stats-row');
  statsRow.innerHTML = '';
  const summary = data.summary || {};
  cfg.stats.forEach(s => {
    const raw = summary[s.key] ?? '-';
    const val = (typeof raw === 'number' && !Number.isInteger(raw)) ? raw.toFixed(2) : raw;
    statsRow.insertAdjacentHTML('beforeend', `
      <div class="stat-card ${s.cls}">
        <div class="stat-label">${s.label}</div>
        <div class="stat-value">${val}<span class="stat-unit">${s.unit}</span></div>
      </div>
    `);
  });

  // Chart image
  const img = document.getElementById('result-img');
  img.src = 'data:image/png;base64,' + data.image;
  img.dataset.b64 = data.image;

  // 聚类详情表
  const clusterDetail = document.getElementById('cluster-detail');
  if (currentView === 'cluster' && summary.clusters) {
    clusterDetail.style.display = 'block';
    const tbody = document.querySelector('#cluster-table tbody');
    tbody.innerHTML = '';
    summary.clusters.forEach(c => {
      tbody.insertAdjacentHTML('beforeend',
        `<tr><td><strong>簇 ${c.id}</strong></td><td>${c.size}</td><td>${c.pct}%</td><td>${c.center_x}</td><td>${c.center_y}</td></tr>`);
    });
  } else {
    clusterDetail.style.display = 'none';
  }

  // 拓扑详情表
  const topoDetail = document.getElementById('topology-detail');
  if (currentView === 'topology' && summary.nodes) {
    topoDetail.style.display = 'block';
    const tbody = document.querySelector('#topology-table tbody');
    tbody.innerHTML = '';
    summary.nodes.forEach(n => {
      tbody.insertAdjacentHTML('beforeend',
        `<tr><td><strong>${n.region}</strong></td><td>${n.in}</td><td>${n.out}</td></tr>`);
    });
  } else {
    topoDetail.style.display = 'none';
  }

  // 区域满意度详情表
  const satDetail = document.getElementById('sat-region-detail');
  if (currentView === 'satisfaction_region' && summary.regions) {
    satDetail.style.display = 'block';
    const tbody = document.querySelector('#sat-region-table tbody');
    tbody.innerHTML = '';
    summary.regions.forEach(r => {
      tbody.insertAdjacentHTML('beforeend',
        `<tr><td><strong>${r.region}</strong></td><td>${r.avg_score}</td></tr>`);
    });
  } else {
    satDetail.style.display = 'none';
  }

  document.getElementById('result-section').scrollIntoView({ behavior: 'smooth' });
}

// ─── Download ───
function bindDownload() {
  document.getElementById('download-btn').addEventListener('click', () => {
    const img = document.getElementById('result-img');
    const b64 = img.dataset.b64;
    if (!b64) return;
    const a = document.createElement('a');
    a.href = 'data:image/png;base64,' + b64;
    a.download = `${currentView}_result.png`;
    a.click();
  });
}

// ─── Helpers ───
function setLoading(show) {
  document.getElementById('loading').classList.toggle('show', show);
  document.getElementById('run-btn').disabled = show;
}

function hideResult() {
  document.getElementById('result-section').style.display = 'none';
  document.getElementById('stats-row').innerHTML = '';
  document.getElementById('cluster-detail').style.display = 'none';
  document.getElementById('topology-detail').style.display = 'none';
  document.getElementById('sat-region-detail').style.display = 'none';
}

function showToast(msg, type = 'info') {
  let toast = document.getElementById('toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'toast';
    toast.style.cssText = `
      position:fixed; bottom:24px; left:50%; transform:translateX(-50%);
      background:var(--bg-card); border:1px solid var(--border); color:var(--text-primary);
      padding:10px 18px; border-radius:8px; font-size:13px;
      box-shadow:0 4px 20px rgba(0,0,0,0.5); z-index:9999;
      transition:opacity 0.3s;
    `;
    document.body.appendChild(toast);
  }
  toast.style.borderColor = type === 'error' ? 'var(--red)' : 'var(--border)';
  toast.textContent = msg;
  toast.style.opacity = '1';
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { toast.style.opacity = '0'; }, 3000);
}
