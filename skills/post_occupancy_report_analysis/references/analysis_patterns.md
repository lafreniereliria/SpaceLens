# Analysis Patterns

This reference condenses the report-writing logic found in prior post-occupancy evaluation reports. It is a style and reasoning guide, not a fixed text library.

## Core Report Logic

Use this sequence for every analytical unit:

1. State the metric scope and data basis.
2. Describe the overall level, distribution range, and top or weak spaces.
3. Identify the main driver metrics or observed spatial pattern.
4. Interpret the pattern against the building type and space function.
5. Convert the diagnosis into targeted design, management, or monitoring recommendations.

Preferred paragraph frame:

`从整体分布来看，{space_count}个空间单元的{dimension}得分介于{min}-{max}分之间，均值为{mean}分，整体处于{grade}水平。{top_spaces}表现较好，说明其在{drivers}方面具有优势；{weak_spaces}相对偏低，主要受{weak_drivers}影响，反映出{diagnosis}。因此，后续优化应重点围绕{recommendation_focus}展开。`

## Dimension Patterns

### 物理环境感知

Inputs:
- temperature, humidity, light, noise, wind, CO2, PM2.5
- heatmaps, point measurements, per-space statistics, normalized scores

Interpretation:
- Temperature: comfort, HVAC zoning, heat accumulation, sun exposure, occupancy load.
- Humidity: enclosure, ventilation, HVAC stability, outdoor air influence.
- Light: daylight access, glare, insufficient lighting, exhibit or reading needs.
- Noise: crowd, equipment, multimedia, nearby classrooms, hard surfaces, acoustic separation.
- Wind: natural ventilation, draft discomfort, stagnant air, semi-open space performance.
- CO2/PM2.5: ventilation, crowd density, filtration, outdoor infiltration, cleaning disturbance.

Recommendations:
- Dynamic HVAC zoning, added shading, uniform lighting, glare control, acoustic absorption, ventilation scheduling, filtration, continuous monitoring.

### 动线感知

Inputs:
- visit frequency, use duration, moving speed, dwell duration, openness/density, topology flows, trajectory length, trajectory variation

Interpretation:
- High visit frequency indicates attraction or necessary traffic; pair with dwell duration to distinguish "destination" from "pass-through".
- Long dwell duration usually indicates attraction, comfort, or bottleneck; check behavior type and density before judging positive.
- High speed can mean clear traffic flow or lack of stopping interest; low speed can mean deep experience or congestion.
- High topology flow marks important connection corridors; weak in/out flow can reveal isolated spaces.
- Large trajectory variation means flexible exploration or confusing navigation; interpret by building type.

Recommendations:
- Add decision-point signage, improve path continuity, introduce rest or service nodes, separate static and moving flows, strengthen weak connections, manage peak-time circulation.

### 行为感知

Inputs:
- `行为人次`, `行为持续时长`, `行为平均发生率`, `行为复合程度`, `空间功能利用率`

Interpretation:
- High count with short duration: active but fast-moving use.
- Low count and low duration: underused or poorly located space.
- High duration with low diversity: single-function dependence.
- High diversity: functional adaptability, but check for conflicting behaviors.
- Functional utilization should be read against area; high utilization in small spaces may imply crowding or strong demand.

Recommendations:
- Add behavior-specific facilities, clarify zones, create flexible nodes, separate conflicting behaviors, activate underused spaces, adapt operation by weekday/weekend or peak/off-peak.

### 主观心理感知

Inputs:
- `整体满意度`, `空间单元满意度`, `设计要素满意度`, IPA/radar if available

Interpretation:
- Compare overall and local satisfaction; mismatches indicate compensating factors or hidden pain points.
- Low satisfaction in facilities, signage, lighting, noise, temperature, or layout should be connected to objective metrics when available.
- High satisfaction does not cancel objective problems; frame it as "perceived acceptance with measurable optimization space".

Recommendations:
- Convert low-scoring design elements into actionable facility, layout, environment, or management interventions.

### 综合评价

Inputs:
- dimension scores, comprehensive scores, weights, grading thresholds, type groups

Interpretation:
- Report grade distribution first.
- Identify best spaces as benchmarks and weak spaces as intervention priorities.
- Explain dimension contribution: e.g. physical environment dominant in outdoor/semi-open spaces, subjective experience dominant in reading/learning spaces, movement and behavior as support dimensions.
- Compare space types: exhibition vs rest, high-frequency vs low-frequency, stay spaces vs circulation spaces.

Recommendations:
- Give prioritized improvements by dimension and by space type.

## Metric Interpretation Cheatsheet

| Metric | High Value Often Means | Low Value Often Means | Caution |
| --- | --- | --- | --- |
| 到访频次 | attraction, necessary route, core node | weak attraction, poor access, edge space | pair with dwell time |
| 使用时长/停留时长 | strong use, interest, comfort | pass-through, low attraction | long time can also mean congestion |
| 移动速率 | clear route or fast pass-through | slow experience or congestion | interpret with density and trajectory |
| 人员密度/空间开放程度 | strong occupancy or crowding | spare capacity or low activation | area normalization matters |
| 拓扑流入流出 | spatial connection importance | isolated or one-way space | check direction imbalance |
| 轨迹长度 | exploration depth | short visit, limited route | building type changes meaning |
| 轨迹差异系数 | route diversity or wayfinding uncertainty | uniform route | not automatically good or bad |
| 行为发生人次 | behavior demand | inactive space | filter invalid behavior labels |
| 行为持续时长 | deep engagement | shallow use | behavior type matters |
| 行为平均发生率 | behavior intensity | weak activity | normalize by sample/time |
| 行为复合程度 | multifunctional capacity | single-function space | mixed behaviors may conflict |
| 空间功能利用率 | area efficiency | area redundancy | high value may imply overload |
| 整体满意度 | broad acceptance | overall experience problem | subjective bias possible |
| 空间单元满意度 | local experience quality | local design issue | compare with objective metrics |
| 设计要素满意度 | design factor performance | design-element shortboard | connect to spatial and objective evidence |

## Recommendation Patterns

- Environment shortboard: "建立监测-诊断-调控闭环", with HVAC, lighting, acoustic, ventilation, or filtration actions.
- Movement shortboard: add signage, clarify route hierarchy, reduce decision ambiguity, add rest nodes, improve weak links.
- Behavior shortboard: introduce facilities matched to observed behavior, create flexible areas, separate conflicting behaviors.
- Satisfaction shortboard: prioritize low satisfaction elements that are also supported by objective data.
- Integrated shortboard: rank improvements by score impact, user impact, and implementation difficulty.

## Data Integrity Rules

- Preserve the difference between raw value, percentage, normalized score, and weighted contribution.
- Do not compare values with different units.
- If sample size is small, say "样本量有限，结论宜作为趋势判断".
- If tables and charts disagree, trust backing tables first and flag the mismatch.
- If a metric is missing, keep the section but mark it as unavailable only when the report structure requires it.
