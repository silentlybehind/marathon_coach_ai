from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


@dataclass
class Run:
    date: date
    distance_km: float
    duration_min: float
    avg_hr: float | None
    rpe: float | None
    elevation_m: float | None
    workout_type: str
    notes: str

    @property
    def pace_min_km(self) -> float:
        return self.duration_min / self.distance_km if self.distance_km else 0.0

    @property
    def load(self) -> float:
        return self.duration_min * (self.rpe if self.rpe is not None else 5.0)


def maybe_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    return float(value)


def read_runs(path: Path) -> list[Run]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        runs = []
        for row in reader:
            runs.append(
                Run(
                    date=datetime.strptime(row["date"], "%Y-%m-%d").date(),
                    distance_km=float(row["distance_km"]),
                    duration_min=float(row["duration_min"]),
                    avg_hr=maybe_float(row.get("avg_hr")),
                    rpe=maybe_float(row.get("rpe")),
                    elevation_m=maybe_float(row.get("elevation_m")),
                    workout_type=(row.get("workout_type") or "easy").lower(),
                    notes=row.get("notes") or "",
                )
            )
        return sorted(runs, key=lambda item: item.date)


def pace(value: float) -> str:
    minutes = int(value)
    seconds = round((value - minutes) * 60)
    if seconds == 60:
        minutes += 1
        seconds = 0
    return f"{minutes}:{seconds:02d}/km"


def key_for(day: date, period: str) -> str:
    if period == "week":
        year, week, _ = day.isocalendar()
        return f"{year}-W{week:02d}"
    if period == "month":
        return day.strftime("%Y-%m")
    if period == "quarter":
        return f"{day.year}-Q{((day.month - 1) // 3) + 1}"
    if period == "year":
        return str(day.year)
    raise ValueError(period)


def window(runs: list[Run], end: date, days: int) -> list[Run]:
    start = end - timedelta(days=days - 1)
    return [run for run in runs if start <= run.date <= end]


def summarize(runs: list[Run], period: str) -> list[dict[str, object]]:
    grouped: dict[str, list[Run]] = defaultdict(list)
    for run in runs:
        grouped[key_for(run.date, period)].append(run)
    output = []
    for key in sorted(grouped):
        items = grouped[key]
        distance = sum(run.distance_km for run in items)
        duration = sum(run.duration_min for run in items)
        output.append(
            {
                "period": key,
                "runs": len(items),
                "distance_km": round(distance, 2),
                "duration_min": round(duration, 1),
                "avg_pace": pace(duration / distance) if distance else "-",
                "load": round(sum(run.load for run in items), 1),
                "long_run_km": round(max(run.distance_km for run in items), 2),
                "quality_runs": sum(1 for run in items if run.workout_type in {"tempo", "threshold", "interval", "race"}),
            }
        )
    return output


def insights(runs: list[Run]) -> list[str]:
    if not runs:
        return ["No data."]
    end = max(run.date for run in runs)
    last_7 = window(runs, end, 7)
    last_28 = window(runs, end, 28)
    acute = sum(run.load for run in last_7)
    chronic = sum(run.load for run in last_28) / 4
    ratio = acute / chronic if chronic > 0 else None
    quality = sum(1 for run in last_7 if run.workout_type in {"tempo", "threshold", "interval", "race"})
    output = [
        f"Last 7 days: {sum(run.distance_km for run in last_7):.1f} km, {len(last_7)} runs.",
        f"Last 28 days: {sum(run.distance_km for run in last_28):.1f} km, {len(last_28)} runs.",
    ]
    if ratio is not None:
        output.append(f"Acute/chronic load ratio: {ratio:.2f}.")
    if quality > 2:
        output.append("Quality sessions are dense this week; protect recovery.")
    if last_28:
        total = sum(run.distance_km for run in last_28)
        longest = max(run.distance_km for run in last_28)
        if total and longest / total > 0.35:
            output.append("Long-run share is high; spread endurance volume more evenly.")
    return output


def build_context(runs: list[Run]) -> dict[str, object]:
    if not runs:
        return {"message": "No training data."}
    end = max(run.date for run in runs)
    latest = runs[-1]
    return {
        "latest_date": end.isoformat(),
        "latest_run": {
            "date": latest.date.isoformat(),
            "distance_km": latest.distance_km,
            "duration_min": latest.duration_min,
            "pace": pace(latest.pace_min_km),
            "avg_hr": latest.avg_hr,
            "rpe": latest.rpe,
            "workout_type": latest.workout_type,
            "notes": latest.notes,
        },
        "insights": insights(runs),
        "weekly_summary": summarize(window(runs, end, 56), "week")[-8:],
        "monthly_summary": summarize(window(runs, end, 370), "month")[-12:],
        "quarterly_summary": summarize(runs, "quarter")[-8:],
        "yearly_summary": summarize(runs, "year")[-5:],
    }


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python3 build_training_context.py training_log.csv", file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(build_context(read_runs(Path(sys.argv[1]))), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()