#!/usr/bin/env python3
"""Build a report data pack from a SpaceLens result folder."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


DIMENSION_MAP = {
    "到访频次热力图": "movement",
    "使用时长": "movement",
    "移动速率": "movement",
    "空间停留时长": "movement",
    "空间聚类": "movement",
    "人员密度": "movement",
    "空间开放程度": "movement",
    "拓扑连接关系": "movement",
    "轨迹差异系数": "movement",
    "轨迹长度": "movement",
    "环境参数_温度": "physical_environment",
    "环境参数_湿度": "physical_environment",
    "环境参数_光照": "physical_environment",
    "环境参数_风速": "physical_environment",
    "环境参数_噪声": "physical_environment",
    "行为人次": "behavior",
    "行为持续时长": "behavior",
    "行为平均发生率": "behavior",
    "行为复合程度": "behavior",
    "空间功能利用率": "behavior",
    "整体满意度": "satisfaction",
    "空间单元满意度": "satisfaction",
    "设计要素满意度": "satisfaction",
}

METRIC_ALIASES = {
    "停留时长": "空间停留时长",
    "行为发生人次": "行为人次",
    "行为时长": "行为持续时长",
    "行为发生率": "行为平均发生率",
    "行为复合度": "行为复合程度",
    "功能利用率": "空间功能利用率",
    "空间满意度": "空间单元满意度",
}

WIDE_TABLE_COLUMN_LIMIT = 80


def json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def records_from_frame(df: pd.DataFrame, max_rows: int) -> list[dict[str, Any]]:
    trimmed = df.head(max_rows).copy()
    records: list[dict[str, Any]] = []
    for row in trimmed.to_dict(orient="records"):
        records.append({str(k): json_safe(v) for k, v in row.items()})
    return records


def numeric_summary(df: pd.DataFrame) -> dict[str, dict[str, float | int]]:
    summary: dict[str, dict[str, float | int]] = {}
    for col in df.columns:
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if series.empty:
            continue
        summary[str(col)] = {
            "count": int(series.count()),
            "mean": round(float(series.mean()), 4),
            "min": round(float(series.min()), 4),
            "max": round(float(series.max()), 4),
        }
    return summary


def overall_numeric_summary(df: pd.DataFrame) -> dict[str, float | int | None]:
    numeric = df.apply(pd.to_numeric, errors="coerce")
    values = numeric.to_numpy().ravel()
    values = values[~pd.isna(values)]
    if len(values) == 0:
        return {"count": 0, "mean": None, "min": None, "max": None}
    return {
        "count": int(len(values)),
        "mean": round(float(values.mean()), 4),
        "min": round(float(values.min()), 4),
        "max": round(float(values.max()), 4),
    }


def should_summarize_table(sheet_name: str, df: pd.DataFrame, matrix_mode: str) -> bool:
    if matrix_mode == "full":
        return False
    return "矩阵" in sheet_name or df.shape[1] > WIDE_TABLE_COLUMN_LIMIT


def read_excel_tables(path: Path, max_rows: int, matrix_mode: str) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    workbook = pd.ExcelFile(path)
    for sheet_name in workbook.sheet_names:
        df = workbook.parse(sheet_name)
        df = df.where(pd.notna(df), None)
        summarize = should_summarize_table(sheet_name, df, matrix_mode)
        table = {
            "source_file": str(path),
            "columns": [str(c) for c in df.columns[:WIDE_TABLE_COLUMN_LIMIT]],
            "column_count": int(len(df.columns)),
            "row_count": int(len(df)),
            "wide_table": bool(summarize),
            "truncated": bool(len(df) > max_rows or summarize),
        }
        if summarize:
            table.update(
                {
                    "records": [],
                    "records_omitted_reason": "wide matrix summarized; use source_file for full backing data",
                    "matrix_summary": overall_numeric_summary(df),
                    "numeric_summary": {},
                }
            )
        else:
            table.update(
                {
                    "records": records_from_frame(df, max_rows),
                    "numeric_summary": numeric_summary(df),
                }
            )
        tables[sheet_name] = {
            **table,
        }
    return tables


def canonical_metric_name(name: str) -> str:
    return METRIC_ALIASES.get(name, name)


def known_metric_names(summary: dict[str, Any] | None = None) -> list[str]:
    names = set(DIMENSION_MAP)
    names.update(METRIC_ALIASES.values())
    names.update(METRIC_ALIASES)
    if summary:
        names.update(summary.keys())
    return sorted(names, key=len, reverse=True)


def metric_name_from_data_file(path: Path) -> str:
    return canonical_metric_name(path.stem)


def metric_name_from_image_file(path: Path, summary: dict[str, Any]) -> tuple[str, str]:
    stem = path.stem
    for metric_name in known_metric_names(summary):
        canonical = canonical_metric_name(metric_name)
        if stem == metric_name:
            return canonical, metric_name
        prefix = f"{metric_name}_"
        if stem.startswith(prefix):
            return canonical, stem[len(prefix):]
    return canonical_metric_name(stem), stem


def parse_readme(result_folder: Path) -> dict[str, str]:
    readme = result_folder / "README.txt"
    metadata: dict[str, str] = {}
    if not readme.exists():
        return metadata
    for line in readme.read_text(encoding="utf-8").splitlines():
        if "：" not in line:
            continue
        key, value = line.split("：", 1)
        metadata[key.strip()] = value.strip()
    return metadata


def ensure_metric(metrics: dict[str, Any], metric_name: str) -> dict[str, Any]:
    metric_name = canonical_metric_name(metric_name)
    return metrics.setdefault(
        metric_name,
        {
            "display_name": metric_name,
            "dimension": DIMENSION_MAP.get(metric_name, "other"),
            "summary": {},
            "tables": {},
            "images": [],
        },
    )


def build_pack(result_folder: Path, project_name: str, max_rows: int, matrix_mode: str) -> dict[str, Any]:
    result_folder = result_folder.resolve()
    summary_file = result_folder / "summary.json"
    data_dir = result_folder / "data"
    images_dir = result_folder / "images"
    readme_metadata = parse_readme(result_folder)

    data_gaps: list[str] = []
    if summary_file.exists():
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
    else:
        summary = {}
        data_gaps.append(f"Missing summary file: {summary_file}")

    metrics: dict[str, Any] = {}
    for metric_name, metric_summary in summary.items():
        metric = ensure_metric(metrics, metric_name)
        metric["summary"] = metric_summary

    if data_dir.exists():
        for data_file in sorted(data_dir.glob("*.xlsx")):
            metric_name = metric_name_from_data_file(data_file)
            metric = ensure_metric(metrics, metric_name)
            metric["source_data_file"] = str(data_file)
            try:
                metric["tables"] = read_excel_tables(data_file, max_rows, matrix_mode)
            except Exception as exc:  # pragma: no cover - defensive CLI behavior
                data_gaps.append(f"Could not read {data_file}: {exc}")
    else:
        data_gaps.append(f"Missing data directory: {data_dir}")

    if images_dir.exists():
        for image_file in sorted(images_dir.glob("*.png")):
            metric_name, figure_name = metric_name_from_image_file(image_file, summary)
            metric = ensure_metric(metrics, metric_name)
            metric["images"].append(
                {
                    "path": str(image_file),
                    "figure_name": figure_name,
                    "caption": f"{metric_name} - {figure_name}" if figure_name != metric_name else metric_name,
                }
            )
    else:
        data_gaps.append(f"Missing images directory: {images_dir}")

    final_project_name = project_name or readme_metadata.get("项目名称") or result_folder.name

    return {
        "schema_version": "1.0",
        "project": {
            "name": final_project_name,
            "building_type": readme_metadata.get("建筑类型", ""),
            "evaluation_scope": "",
            "collection_date": "",
            "report_language": "zh-CN",
            "spaces": [],
        },
        "source": {
            "result_folder": str(result_folder),
            "summary_file": str(summary_file) if summary_file.exists() else "",
            "readme_metadata": readme_metadata,
            "data_files": [str(p) for p in sorted(data_dir.glob("*.xlsx"))] if data_dir.exists() else [],
            "image_files": [str(p) for p in sorted(images_dir.glob("*.png"))] if images_dir.exists() else [],
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "matrix_mode": matrix_mode,
        },
        "metrics": metrics,
        "score_model": {
            "grade_thresholds": [
                {"label": "优秀", "min": 85, "max": 100},
                {"label": "良好", "min": 70, "max": 85},
                {"label": "一般", "min": 60, "max": 70},
                {"label": "待改进", "min": 0, "max": 60},
            ],
            "dimension_weights": {},
            "metric_rules": {},
        },
        "data_gaps": data_gaps,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_folder", type=Path, help="SpaceLens result folder, e.g. GUI_评价结果")
    parser.add_argument("--out", type=Path, default=Path("report_data_pack.json"))
    parser.add_argument("--project-name", default="", help="Project/building name for the report")
    parser.add_argument("--max-rows", type=int, default=5000, help="Maximum records saved per Excel sheet")
    parser.add_argument(
        "--matrix-mode",
        choices=["summary", "full"],
        default="summary",
        help="Use summary to keep heatmap/interpolation matrices compact; use full to embed all matrix rows.",
    )
    args = parser.parse_args()

    pack = build_pack(args.result_folder, args.project_name, args.max_rows, args.matrix_mode)
    args.out.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.out} with {len(pack['metrics'])} metrics")
    if pack["data_gaps"]:
        print("Data gaps:")
        for gap in pack["data_gaps"]:
            print(f"- {gap}")


if __name__ == "__main__":
    main()
