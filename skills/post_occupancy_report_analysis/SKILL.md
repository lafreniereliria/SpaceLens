---
name: post_occupancy_report_analysis
description: Use when generating building post-occupancy evaluation reports from SpaceLens statistical results, including movement, behavior, physical environment, satisfaction, and integrated scoring data. The skill turns saved result data packs into formal analysis, diagnosis, and optimization recommendations.
---

# Post-Occupancy Report Analysis

Use this skill to turn SpaceLens result exports into a formal building post-occupancy evaluation report.

## Inputs

Prefer a saved report data pack produced by `scripts/build_report_data_pack.py`.

If the user provides a SpaceLens result folder instead, first build the data pack. The current SpaceLens result folder contract is:

```text
<结果文件夹>/
├── README.txt      # 项目名称、建筑类型、导出指标数、导出时间
├── summary.json    # 每个指标的核心数值摘要
├── data/           # 每个指标背后的 Excel 数据
└── images/         # 每个指标的 PNG 图表，命名为“指标名_图名.png”
```

Build the data pack with:

```bash
python skills/post_occupancy_report_analysis/scripts/build_report_data_pack.py GUI_评价结果 --out report_data_pack.json
```

For large heatmap/interpolation matrices, the script keeps compact summaries by default and preserves the source Excel path. Use `--matrix-mode full` only when a report section truly needs every matrix cell embedded in JSON.

Required context:
- project metadata: building name, building type, evaluation scope, collection date, evaluated floors or spaces
- space map: region id, space name, optional type such as exhibition, reading, circulation, rest, courtyard
- SpaceLens summaries and backing tables from `summary.json`, `data/*.xlsx`, and image manifest
- optional scoring settings: dimension weights, metric directions, target intervals, grading thresholds

Read `references/report_data_schema.json` when checking whether the data pack is complete.
Read `references/analysis_patterns.md` before writing analytical sections.

## Workflow

1. Validate the data pack.
   - Confirm which dimensions are available: physical environment, movement, behavior, satisfaction, integrated scores.
   - Record missing metrics explicitly instead of inventing values.
   - Preserve original units and distinguish measured values from normalized scores.

2. Build the evidence map.
   - For every metric, identify overall level, range, top spaces, weak spaces, and dominant drivers.
   - Cross-check image names with table names so figure references match the report. Image captions are derived from `指标名_图名.png`.
   - Keep a `data_gaps` list for missing sheets, truncated rows, absent space names, or low sample size.

3. Write each metric analysis using this ladder:
   - Result: what the data shows, with key numbers.
   - Pattern: spatial, temporal, behavioral, or group difference.
   - Interpretation: why this likely happens, using building type and space function.
   - Impact: what it means for comfort, efficiency, experience, or management.
   - Recommendation: targeted design, operation, or monitoring action.

4. Write dimension summaries.
   - Physical environment: evaluate temperature, humidity, light, noise, wind, CO2, PM2.5 if present.
   - Movement: evaluate visit frequency, duration, speed, dwell, openness, topology, trajectory length and variation.
   - Behavior: evaluate behavior count, behavior duration, average behavior rate, behavior diversity, and spatial functional utilization.
   - Satisfaction: evaluate overall satisfaction, space-unit satisfaction, and design-element satisfaction.
   - Integrated result: explain score distribution, best and weak spaces, dimension contributions, and type contrasts.

5. Combine subjective and objective evidence.
   - Highlight agreement, e.g. low light score plus low light satisfaction.
   - Highlight mismatch, e.g. high satisfaction but low behavior activity, or high traffic but low comfort.
   - Treat mismatches as diagnostic findings, not errors.

6. Generate the report.
   - Default structure: project overview, data and method, metric analysis, dimension evaluation, integrated diagnosis, optimization recommendations, limitations.
   - Use formal Chinese. Keep claims data-grounded.
   - Do not mention software implementation details unless the user asks.
   - When generating DOCX, follow the `documents` skill render-and-verify workflow.

## Output Rules

- Use section titles matching report style, such as `物理环境感知评价`, `动线感知评价`, `行为感知评价`, `主观心理感知评价`, `建筑主客观综合分析结果`, `优化建议`.
- Prefer "现象-原因-影响-建议" paragraphs over loose commentary.
- Use precise qualifiers: "显著高于", "相对偏低", "分化明显", "整体良好但局部存在短板".
- Never fabricate rankings, scores, sample sizes, or figure numbers.
- If only charts are available and backing data is missing, state that the analysis is based on chart interpretation and mark it as lower confidence.

## Current SpaceLens Metric Names

Use these names when looking up data in the pack:

- 动线感知: `到访频次热力图`, `使用时长`, `移动速率`, `空间停留时长`, `空间聚类`, `人员密度`, `空间开放程度`, `拓扑连接关系`, `轨迹差异系数`, `轨迹长度`
- 物理环境感知: `环境参数_温度`, `环境参数_湿度`, `环境参数_光照`, `环境参数_风速`, `环境参数_噪声`
- 行为感知: `行为人次`, `行为持续时长`, `行为平均发生率`, `行为复合程度`, `空间功能利用率`
- 主观心理感知: `整体满意度`, `空间单元满意度`, `设计要素满意度`

Older aliases may appear in historical exports; normalize them before writing: `停留时长` → `空间停留时长`, `行为时长` → `行为持续时长`, `行为发生率` → `行为平均发生率`, `行为复合度` → `行为复合程度`, `功能利用率` → `空间功能利用率`, `空间满意度` → `空间单元满意度`.
