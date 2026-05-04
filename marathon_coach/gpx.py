from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

from marathon_coach.coach import Run


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, name: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == name:
            return (child.text or "").strip()
    return None


def _iter_track_points(root: ET.Element) -> list[ET.Element]:
    points: list[ET.Element] = []
    for element in root.iter():
        if _local_name(element.tag) == "trkpt":
            points.append(element)
    if points:
        return points
    for element in root.iter():
        if _local_name(element.tag) == "rtept":
            points.append(element)
    return points


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return 2 * radius_km * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _avg_heart_rate(root: ET.Element) -> float | None:
    values: list[float] = []
    for element in root.iter():
        if _local_name(element.tag).lower() == "hr":
            value = _parse_float(element.text)
            if value is not None:
                values.append(value)
    return sum(values) / len(values) if values else None


def _activity_date(times: list[datetime], fallback: date | None = None) -> date:
    if times:
        return min(times).date()
    if fallback:
        return fallback
    return datetime.now(timezone.utc).date()


def parse_gpx_bytes(
    content: bytes,
    workout_type: str = "easy",
    rpe: float | None = None,
    notes: str = "",
) -> Run:
    """Parse a GPX upload into one training-log row."""
    if not content.strip():
        raise ValueError("GPX 文件为空。")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"GPX 解析失败：{exc}") from exc

    points = _iter_track_points(root)
    if len(points) < 2:
        raise ValueError("GPX 至少需要包含两个轨迹点。")

    coordinates: list[tuple[float, float, float | None, datetime | None]] = []
    for point in points:
        lat = _parse_float(point.attrib.get("lat"))
        lon = _parse_float(point.attrib.get("lon"))
        if lat is None or lon is None:
            continue
        elevation = _parse_float(_child_text(point, "ele"))
        timestamp = _parse_time(_child_text(point, "time"))
        coordinates.append((lat, lon, elevation, timestamp))

    if len(coordinates) < 2:
        raise ValueError("GPX 轨迹点缺少有效经纬度。")

    distance_km = 0.0
    elevation_gain = 0.0
    previous_ele: float | None = None
    for index, (lat, lon, ele, _timestamp) in enumerate(coordinates):
        if index > 0:
            prev_lat, prev_lon, _prev_ele, _prev_timestamp = coordinates[index - 1]
            distance_km += _haversine_km(prev_lat, prev_lon, lat, lon)
        if previous_ele is not None and ele is not None:
            gain = ele - previous_ele
            if gain > 0:
                elevation_gain += gain
        if ele is not None:
            previous_ele = ele

    times = [item[3] for item in coordinates if item[3] is not None]
    if len(times) >= 2:
        duration_min = (max(times) - min(times)).total_seconds() / 60
    else:
        raise ValueError("GPX 缺少足够的时间戳，无法计算训练时长。")

    if distance_km <= 0.01:
        raise ValueError("GPX 距离过短，无法作为一次训练记录。")
    if duration_min <= 0:
        raise ValueError("GPX 时间戳无效，训练时长必须大于 0。")
    if rpe is not None and not 1 <= rpe <= 10:
        raise ValueError("RPE 必须在 1 到 10 之间。")

    allowed_types = {"easy", "recovery", "long", "tempo", "threshold", "interval", "race"}
    normalized_type = workout_type.strip().lower() if workout_type else "easy"
    if normalized_type not in allowed_types:
        normalized_type = "easy"

    return Run(
        date=_activity_date(times),
        distance_km=distance_km,
        duration_min=duration_min,
        avg_hr=_avg_heart_rate(root),
        rpe=rpe,
        elevation_m=elevation_gain,
        workout_type=normalized_type,
        notes=notes.strip(),
    )
