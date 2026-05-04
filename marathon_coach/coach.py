from __future__ import annotations

import argparse
import csv
import html
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = PROJECT_ROOT / "data" / "training_log.csv"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "data" / "reports"


@dataclass
class Run:
    date: date
    distance_km: float
    duration_min: float
    avg_hr: float | None = None
    rpe: float | None = None
    elevation_m: float | None = None
    workout_type: str = "easy"
    notes: str = ""

    @property
    def pace_min_km(self) -> float:
        return self.duration_min / self.distance_km if self.distance_km else 0.0

    @property
    def load(self) -> float:
        return self.duration_min * (self.rpe if self.rpe is not None else 5.0)


FIELDNAMES = ["date", "distance_km", "duration_min", "avg_hr", "rpe", "elevation_m", "workout_type", "notes"]


def parse_date(value: str) -> date:
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def to_float(value: str | None) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(value)


def load_runs(path: Path) -> list[Run]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return sorted(
            [
                Run(
                    date=parse_date(row["date"]),
                    distance_km=float(row["distance_km"]),
                    duration_min=float(row["duration_min"]),
                    avg_hr=to_float(row.get("avg_hr")),
                    rpe=to_float(row.get("rpe")),
                    elevation_m=to_float(row.get("elevation_m")),
                    workout_type=(row.get("workout_type") or "easy").strip().lower(),
                    notes=(row.get("notes") or "").strip(),
                )
                for row in reader
                if row.get("date") and row.get("distance_km") and row.get("duration_min")
            ],
            key=lambda run: run.date,
        )


def write_runs(path: Path, runs: Iterable[Run]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for run in sorted(runs, key=lambda item: item.date):
            writer.writerow(
                {
                    "date": run.date.isoformat(),
                    "distance_km": f"{run.distance_km:.2f}",
                    "duration_min": f"{run.duration_min:.1f}",
                    "avg_hr": "" if run.avg_hr is None else f"{run.avg_hr:.0f}",
                    "rpe": "" if run.rpe is None else f"{run.rpe:.1f}",
                    "elevation_m": "" if run.elevation_m is None else f"{run.elevation_m:.0f}",
                    "workout_type": run.workout_type,
                    "notes": run.notes,
                }
            )


def merge_runs(existing: list[Run], incoming: list[Run]) -> list[Run]:
    merged = {(run.date, run.workout_type, round(run.distance_km, 2)): run for run in existing}
    for run in incoming:
        merged[(run.date, run.workout_type, round(run.distance_km, 2))] = run
    return sorted(merged.values(), key=lambda item: item.date)


def fmt_pace(pace: float) -> str:
    minutes = int(pace)
    seconds = round((pace - minutes) * 60)
    if seconds == 60:
        minutes += 1
        seconds = 0
    return f"{minutes}:{seconds:02d}/km"


def period_key(run_date: date, period: str) -> str:
    if period == "week":
        year, week, _ = run_date.isocalendar()
        return f"{year}-W{week:02d}"
    if period == "month":
        return run_date.strftime("%Y-%m")
    if period == "quarter":
        return f"{run_date.year}-Q{((run_date.month - 1) // 3) + 1}"
    if period == "year":
        return str(run_date.year)
    raise ValueError(f"Unsupported period: {period}")


def summarize(runs: list[Run], period: str) -> list[dict[str, object]]:
    grouped: dict[str, list[Run]] = defaultdict(list)
    for run in runs:
        grouped[period_key(run.date, period)].append(run)
    summaries = []
    for key in sorted(grouped):
        items = grouped[key]
        total_distance = sum(run.distance_km for run in items)
        total_duration = sum(run.duration_min for run in items)
        total_load = sum(run.load for run in items)
        summaries.append(
            {
                "period": key,
                "runs": len(items),
                "distance_km": round(total_distance, 2),
                "duration_min": round(total_duration, 1),
                "avg_pace": fmt_pace(total_duration / total_distance) if total_distance else "-",
                "load": round(total_load, 1),
                "long_run_km": round(max(run.distance_km for run in items), 2),
                "quality_runs": sum(1 for run in items if run.workout_type in {"tempo", "threshold", "interval", "race"}),
            }
        )
    return summaries


def recent_window(runs: list[Run], end_date: date, days: int) -> list[Run]:
    start = end_date - timedelta(days=days - 1)
    return [run for run in runs if start <= run.date <= end_date]


def trend(current: float, previous: float) -> str:
    if previous <= 0:
        return "new baseline"
    change = (current - previous) / previous
    if change > 0.15:
        return f"up {change:.0%}"
    if change < -0.15:
        return f"down {abs(change):.0%}"
    return "stable"


def generate_insights(runs: list[Run]) -> list[str]:
    if not runs:
        return ["No training data yet. Upload a CSV to create the first baseline."]
    end_date = max(run.date for run in runs)
    last_7 = recent_window(runs, end_date, 7)
    prev_7 = [run for run in runs if end_date - timedelta(days=13) <= run.date <= end_date - timedelta(days=7)]
    last_28 = recent_window(runs, end_date, 28)
    dist_7 = sum(run.distance_km for run in last_7)
    prev_dist_7 = sum(run.distance_km for run in prev_7)
    load_7 = sum(run.load for run in last_7)
    chronic = sum(run.load for run in last_28) / 4
    ratio = load_7 / chronic if chronic > 0 else None
    quality_count = sum(1 for run in last_7 if run.workout_type in {"tempo", "threshold", "interval", "race"})
    insights = [
        f"Last 7 days: {dist_7:.1f} km across {len(last_7)} runs, distance trend is {trend(dist_7, prev_dist_7)}.",
        f"Recent training load: {load_7:.0f} points based on duration x RPE.",
    ]
    if ratio is not None:
        if ratio > 1.5:
            status = "high injury-risk ramp; reduce intensity or volume for several days"
        elif ratio < 0.8:
            status = "low stimulus; add volume carefully if recovery is good"
        else:
            status = "balanced load"
        insights.append(f"Acute/chronic load ratio: {ratio:.2f}, interpreted as {status}.")
    if last_28:
        long_run = max(last_28, key=lambda run: run.distance_km)
        long_share = long_run.distance_km / max(sum(run.distance_km for run in last_28), 1)
        if long_share > 0.35:
            insights.append(f"Longest run in the last 28 days is {long_run.distance_km:.1f} km, a large share of total volume; spread endurance work more evenly.")
        else:
            insights.append(f"Longest run in the last 28 days is {long_run.distance_km:.1f} km.")
    if quality_count > 2:
        insights.append("More than two quality sessions appeared in the last week; protect easy days.")
    elif quality_count == 0 and dist_7 >= 25:
        insights.append("No quality session found this week; consider one controlled tempo or interval workout if healthy.")
    return insights


def markdown_table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "No data."
    headers = list(rows[0].keys())
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row[h]) for h in headers) + " |")
    return "\n".join(lines)


def html_escape(value: object) -> str:
    return html.escape("" if value is None else str(value))


TABLE_LABELS = {
    "period": "周期",
    "runs": "次数",
    "distance_km": "距离 km",
    "duration_min": "时长 min",
    "avg_pace": "平均配速",
    "load": "训练负荷",
    "long_run_km": "最长跑 km",
    "quality_runs": "质量课",
}


def html_table(rows: list[dict[str, object]], lang: str = "en") -> str:
    if not rows:
        return '<p class="empty">暂无数据。</p>' if lang == "zh" else '<p class="empty">No data yet.</p>'
    headers = list(rows[0].keys())
    head = "".join(
        f"<th>{html_escape(TABLE_LABELS.get(header, header.replace('_', ' ').title()) if lang == 'zh' else header.replace('_', ' ').title())}</th>"
        for header in headers
    )
    body = []
    for row in rows:
        cells = "".join(f"<td>{html_escape(row.get(header, ''))}</td>" for header in headers)
        body.append(f"<tr>{cells}</tr>")
    return f"<div class=\"table-wrap\"><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"


def bar_chart(rows: list[dict[str, object]], metric: str, label: str) -> str:
    if not rows:
        return '<p class="empty">No chart data.</p>'
    values = [float(row.get(metric, 0) or 0) for row in rows]
    max_value = max(values) if values else 0
    bars = []
    for row, value in zip(rows, values):
        height = 8 if max_value <= 0 else max(8, int((value / max_value) * 132))
        bars.append(
            "<div class=\"bar-item\">"
            f"<div class=\"bar-value\">{value:g}</div>"
            f"<div class=\"bar\" style=\"height:{height}px\"></div>"
            f"<div class=\"bar-label\">{html_escape(row['period'])}</div>"
            "</div>"
        )
    return f"<div class=\"chart\" aria-label=\"{html_escape(label)}\">{''.join(bars)}</div>"


def metric_card(label: str, value: object, detail: str) -> str:
    return (
        '<section class="metric">'
        f'<div class="metric-label">{html_escape(label)}</div>'
        f'<div class="metric-value">{html_escape(value)}</div>'
        f'<div class="metric-detail">{html_escape(detail)}</div>'
        "</section>"
    )


def generate_insights_zh(runs: list[Run]) -> list[str]:
    if not runs:
        return ["还没有训练数据。先上传一个 GPX 文件或 CSV 文件建立基础档案。"]
    end_date = max(run.date for run in runs)
    last_7 = recent_window(runs, end_date, 7)
    prev_7 = [run for run in runs if end_date - timedelta(days=13) <= run.date <= end_date - timedelta(days=7)]
    last_28 = recent_window(runs, end_date, 28)
    dist_7 = sum(run.distance_km for run in last_7)
    prev_dist_7 = sum(run.distance_km for run in prev_7)
    load_7 = sum(run.load for run in last_7)
    chronic = sum(run.load for run in last_28) / 4
    ratio = load_7 / chronic if chronic > 0 else None
    quality_count = sum(1 for run in last_7 if run.workout_type in {"tempo", "threshold", "interval", "race"})
    trend_text = {"new baseline": "新的基准", "stable": "基本稳定"}.get(trend(dist_7, prev_dist_7), trend(dist_7, prev_dist_7).replace("up", "上升").replace("down", "下降"))
    insights = [
        f"最近 7 天：共 {dist_7:.1f} km，{len(last_7)} 次训练，跑量趋势为 {trend_text}。",
        f"近期训练负荷：约 {load_7:.0f} 点，按 时长 x RPE 估算。",
    ]
    if ratio is not None:
        if ratio > 1.5:
            status = "增长偏快，受伤风险升高，建议短期降低强度或跑量"
        elif ratio < 0.8:
            status = "刺激偏低，如果恢复良好可以谨慎增加跑量"
        else:
            status = "负荷较均衡"
        insights.append(f"急慢性负荷比：{ratio:.2f}，判断为{status}。")
    if last_28:
        long_run = max(last_28, key=lambda run: run.distance_km)
        long_share = long_run.distance_km / max(sum(run.distance_km for run in last_28), 1)
        if long_share > 0.35:
            insights.append(f"最近 28 天最长距离为 {long_run.distance_km:.1f} km，占总跑量偏高，建议把耐力训练分布得更均匀。")
        else:
            insights.append(f"最近 28 天最长距离为 {long_run.distance_km:.1f} km。")
    if quality_count > 2:
        insights.append("最近 7 天质量课超过 2 次，注意保护轻松跑和恢复日。")
    elif quality_count == 0 and dist_7 >= 25:
        insights.append("本周暂无质量课；如果身体状态良好，可以安排一次可控的节奏跑或间歇训练。")
    return insights


def build_ai_context(runs: list[Run]) -> dict[str, object]:
    if not runs:
        return {"message": "No training data available."}
    end_date = max(run.date for run in runs)
    latest = runs[-1]
    return {
        "latest_date": end_date.isoformat(),
        "latest_run": {
            "date": latest.date.isoformat(),
            "distance_km": latest.distance_km,
            "duration_min": latest.duration_min,
            "pace": fmt_pace(latest.pace_min_km),
            "avg_hr": latest.avg_hr,
            "rpe": latest.rpe,
            "elevation_m": latest.elevation_m,
            "workout_type": latest.workout_type,
            "notes": latest.notes,
        },
        "insights": generate_insights(runs),
        "weekly_summary": summarize(recent_window(runs, end_date, 56), "week")[-8:],
        "monthly_summary": summarize(recent_window(runs, end_date, 370), "month")[-12:],
        "quarterly_summary": summarize(runs, "quarter")[-8:],
        "yearly_summary": summarize(runs, "year")[-5:],
    }


def generate_report(runs: list[Run]) -> str:
    context = build_ai_context(runs)
    if "message" in context:
        return str(context["message"])
    sections = [
        "# Marathon Coach Training Report",
        "## Current State",
        "\n".join(f"- {item}" for item in context["insights"]),
        "## Weekly Summary",
        markdown_table(context["weekly_summary"]),
        "## Monthly Summary",
        markdown_table(context["monthly_summary"]),
        "## Quarterly Summary",
        markdown_table(context["quarterly_summary"]),
        "## Yearly Summary",
        markdown_table(context["yearly_summary"]),
        "## AI Coach Prompt",
        "Act as a personal marathon coach. Use the latest run together with the weekly, monthly, quarterly, and yearly summaries below. Diagnose current fitness, fatigue, risk, and the next 7-14 day training adjustment. Avoid medical certainty; recommend professional help for pain, dizziness, chest symptoms, or persistent abnormal fatigue.",
        "```json\n" + json.dumps(context, ensure_ascii=False, indent=2, default=str) + "\n```",
    ]
    return "\n\n".join(sections) + "\n"


def generate_html_report(runs: list[Run], lang: str = "zh") -> str:
    lang = "zh" if lang == "zh" else "en"
    context = build_ai_context(runs)
    if "message" in context:
        message = "暂无训练数据。" if lang == "zh" else context["message"]
        return f"<!doctype html><html lang=\"{lang}\"><head><meta charset=\"utf-8\"><title>Marathon Coach</title></head><body>{html_escape(message)}</body></html>"

    latest = context["latest_run"]
    weekly = context["weekly_summary"]
    monthly = context["monthly_summary"]
    quarterly = context["quarterly_summary"]
    yearly = context["yearly_summary"]
    latest_week = weekly[-1] if weekly else {}
    latest_month = monthly[-1] if monthly else {}
    coach_context = json.dumps(context, ensure_ascii=False, indent=2, default=str)
    labels = {
        "zh": {
            "title": "训练报告",
            "eyebrow": "个人马拉松教练",
            "subtitle": "结合最新一次训练和最近周、月、季度、年度数据，快速判断当前状态，并为下一阶段训练调整提供依据。",
            "latest_run": "最新训练",
            "this_week": "本周跑量",
            "this_month": "本月跑量",
            "latest_date": "最新日期",
            "runs": "次训练",
            "load": "负荷",
            "long": "最长",
            "no_notes": "暂无备注",
            "current_state": "当前状态",
            "weekly_distance": "周跑量趋势",
            "weekly_summary": "周总结",
            "monthly_distance": "月跑量趋势",
            "monthly_summary": "月总结",
            "quarterly_summary": "季度总结",
            "yearly_summary": "年度总结",
            "ai_context": "AI 教练上下文",
            "view_json": "查看 JSON 上下文",
            "back_upload": "返回上传",
        },
        "en": {
            "title": "Training Report",
            "eyebrow": "Personal Marathon Coach",
            "subtitle": "Latest run plus recent weekly, monthly, quarterly, and yearly context for the next training adjustment.",
            "latest_run": "Latest Run",
            "this_week": "This Week",
            "this_month": "This Month",
            "latest_date": "Latest Date",
            "runs": "runs",
            "load": "load",
            "long": "long",
            "no_notes": "No notes",
            "current_state": "Current State",
            "weekly_distance": "Weekly Distance",
            "weekly_summary": "Weekly Summary",
            "monthly_distance": "Monthly Distance",
            "monthly_summary": "Monthly Summary",
            "quarterly_summary": "Quarterly Summary",
            "yearly_summary": "Yearly Summary",
            "ai_context": "AI Coach Context",
            "view_json": "View JSON context",
            "back_upload": "Back to Upload",
        },
    }[lang]
    visible_insights = generate_insights_zh(runs) if lang == "zh" else context["insights"]
    insights = "".join(f"<li>{html_escape(item)}</li>" for item in visible_insights)
    cards = "".join(
        [
            metric_card(labels["latest_run"], f"{latest['distance_km']} km", f"{latest['pace']} · {latest['workout_type']} · RPE {latest.get('rpe') or '-'}"),
            metric_card(labels["this_week"], f"{latest_week.get('distance_km', '-')} km", f"{latest_week.get('runs', '-')} {labels['runs']} · {labels['load']} {latest_week.get('load', '-')}"),
            metric_card(labels["this_month"], f"{latest_month.get('distance_km', '-')} km", f"{latest_month.get('runs', '-')} {labels['runs']} · {labels['long']} {latest_month.get('long_run_km', '-')} km"),
            metric_card(labels["latest_date"], latest["date"], latest.get("notes") or labels["no_notes"]),
        ]
    )
    return f"""<!doctype html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Marathon Coach {html_escape(labels["title"])}</title>
  <style>
    :root {{
      --bg: #f6f7f4;
      --panel: #ffffff;
      --ink: #1e2528;
      --muted: #647071;
      --line: #dce2df;
      --green: #1f7a5b;
      --blue: #2d6f9f;
      --coral: #c95845;
      --gold: #a8791a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
    }}
    header {{
      padding: 34px clamp(18px, 4vw, 52px) 22px;
      background: linear-gradient(135deg, #173f3a 0%, #20576a 54%, #6b5131 100%);
      color: white;
    }}
    .eyebrow {{ margin: 0 0 8px; font-size: 12px; text-transform: uppercase; letter-spacing: 0; opacity: .78; }}
    .language {{ float: right; display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }}
    .language a {{ color: white; border: 1px solid rgba(255,255,255,.34); border-radius: 6px; padding: 7px 10px; text-decoration: none; font-size: 13px; font-weight: 700; }}
    h1 {{ margin: 0; font-size: clamp(30px, 4vw, 48px); line-height: 1.05; letter-spacing: 0; }}
    .subtitle {{ max-width: 760px; margin: 14px 0 0; color: rgba(255,255,255,.82); font-size: 16px; line-height: 1.6; }}
    main {{ width: min(1180px, calc(100% - 32px)); margin: 24px auto 56px; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 20px;
    }}
    .metric, .section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 8px 22px rgba(31, 42, 45, .06);
    }}
    .metric {{ padding: 16px; min-height: 118px; }}
    .metric-label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0; }}
    .metric-value {{ margin-top: 8px; font-size: clamp(24px, 3vw, 34px); font-weight: 760; letter-spacing: 0; }}
    .metric-detail {{ margin-top: 8px; color: var(--muted); font-size: 13px; line-height: 1.45; overflow-wrap: anywhere; }}
    .grid {{ display: grid; grid-template-columns: 1.08fr .92fr; gap: 16px; align-items: start; }}
    .section {{ padding: 18px; margin-bottom: 16px; }}
    h2 {{ margin: 0 0 14px; font-size: 18px; letter-spacing: 0; }}
    ul {{ margin: 0; padding-left: 20px; color: #2e3b3f; line-height: 1.7; }}
    .chart {{ height: 190px; display: flex; align-items: end; gap: 10px; padding: 12px 4px 0; border-bottom: 1px solid var(--line); overflow-x: auto; }}
    .bar-item {{ min-width: 66px; display: grid; grid-template-rows: 22px 1fr 26px; align-items: end; justify-items: center; }}
    .bar {{ width: 30px; border-radius: 6px 6px 0 0; background: linear-gradient(180deg, var(--green), var(--blue)); }}
    .bar-value {{ color: var(--muted); font-size: 12px; align-self: start; }}
    .bar-label {{ color: var(--muted); font-size: 11px; align-self: center; white-space: nowrap; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; background: white; min-width: 760px; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; font-size: 13px; white-space: nowrap; }}
    th {{ background: #edf2ef; color: #415052; font-weight: 700; }}
    tr:last-child td {{ border-bottom: 0; }}
    details {{ border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; background: #fbfcfb; }}
    summary {{ cursor: pointer; font-weight: 700; }}
    pre {{ margin: 12px 0 0; overflow: auto; max-height: 420px; padding: 14px; border-radius: 8px; background: #172124; color: #d8f0e7; font-size: 12px; line-height: 1.5; }}
    .empty {{ color: var(--muted); margin: 0; }}
    @media (max-width: 860px) {{
      .metrics, .grid {{ grid-template-columns: 1fr; }}
      header {{ padding-top: 26px; }}
    }}
  </style>
</head>
<body>
  <header>
    <nav class="language"><a href="/upload?lang={lang}">{html_escape(labels["back_upload"])}</a><a href="/report?lang=zh">中文</a><a href="/report?lang=en">English</a></nav>
    <p class="eyebrow">{html_escape(labels["eyebrow"])}</p>
    <h1>{html_escape(labels["title"])}</h1>
    <p class="subtitle">{html_escape(labels["subtitle"])}</p>
  </header>
  <main>
    <div class="metrics">{cards}</div>
    <div class="grid">
      <section class="section">
        <h2>{html_escape(labels["current_state"])}</h2>
        <ul>{insights}</ul>
      </section>
      <section class="section">
        <h2>{html_escape(labels["weekly_distance"])}</h2>
        {bar_chart(weekly, "distance_km", labels["weekly_distance"])}
      </section>
    </div>
    <section class="section">
      <h2>{html_escape(labels["weekly_summary"])}</h2>
      {html_table(weekly, lang)}
    </section>
    <section class="section">
      <h2>{html_escape(labels["monthly_distance"])}</h2>
      {bar_chart(monthly, "distance_km", labels["monthly_distance"])}
    </section>
    <section class="section">
      <h2>{html_escape(labels["monthly_summary"])}</h2>
      {html_table(monthly, lang)}
    </section>
    <section class="section">
      <h2>{html_escape(labels["quarterly_summary"])}</h2>
      {html_table(quarterly, lang)}
    </section>
    <section class="section">
      <h2>{html_escape(labels["yearly_summary"])}</h2>
      {html_table(yearly, lang)}
    </section>
    <section class="section">
      <h2>{html_escape(labels["ai_context"])}</h2>
      <details>
        <summary>{html_escape(labels["view_json"])}</summary>
        <pre>{html_escape(coach_context)}</pre>
      </details>
    </section>
  </main>
</body>
</html>
"""


def cmd_import(args: argparse.Namespace) -> None:
    incoming = load_runs(Path(args.upload))
    existing = load_runs(Path(args.log))
    merged = merge_runs(existing, incoming)
    write_runs(Path(args.log), merged)
    print(f"Imported {len(incoming)} rows. Training log now has {len(merged)} runs: {args.log}")


def cmd_report(args: argparse.Namespace) -> None:
    runs = load_runs(Path(args.log))
    report = generate_html_report(runs) if args.format == "html" else generate_report(runs)
    suffix = "html" if args.format == "html" else "md"
    output = Path(args.output) if args.output else DEFAULT_REPORT_DIR / f"latest_report.{suffix}"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
        print(f"Wrote report: {output}")
    else:
        print(report)


def cmd_context(args: argparse.Namespace) -> None:
    runs = load_runs(Path(args.log))
    print(json.dumps(build_ai_context(runs), ensure_ascii=False, indent=2, default=str))


def cmd_web(args: argparse.Namespace) -> None:
    from marathon_coach.webapp import run_server

    run_server(args.host, args.port)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Personal marathon training coach")
    parser.add_argument("--log", default=str(DEFAULT_LOG), help="Path to the persistent training log CSV")
    subparsers = parser.add_subparsers(required=True)
    import_parser = subparsers.add_parser("import", help="Import an uploaded training CSV")
    import_parser.add_argument("upload", help="CSV file with training rows")
    import_parser.set_defaults(func=cmd_import)
    report_parser = subparsers.add_parser("report", help="Generate a training report")
    report_parser.add_argument("--format", choices=["html", "markdown"], default="html", help="Report output format")
    report_parser.add_argument("--output", default=None, help="Output path. Defaults to latest_report.html or latest_report.md")
    report_parser.set_defaults(func=cmd_report)
    context_parser = subparsers.add_parser("context", help="Print compact JSON context for an AI coach")
    context_parser.set_defaults(func=cmd_context)
    web_parser = subparsers.add_parser("web", help="Start the local GPX upload web app")
    web_parser.add_argument("--host", default="127.0.0.1", help="Host for the local web server")
    web_parser.add_argument("--port", type=int, default=8765, help="Port for the local web server")
    web_parser.set_defaults(func=cmd_web)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
