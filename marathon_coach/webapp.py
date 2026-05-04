from __future__ import annotations

import html
import json
import re
from email import policy
from email.parser import BytesParser
import errno
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from marathon_coach.coach import DEFAULT_LOG, DEFAULT_REPORT_DIR, Run, build_ai_context, fmt_pace, generate_html_report, load_runs, merge_runs, write_runs
from marathon_coach.gpx import parse_gpx_bytes


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"
ARTICLE_DIR = PROJECT_ROOT / "data" / "articles"


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


TEXT = {
    "zh": {
        "upload": "上传",
        "report": "报告",
        "ai_context": "AI 上下文",
        "upload_title": "上传 GPX 活动",
        "upload_desc": "导入手表、手机或跑步 App 导出的 GPX 文件。上传后会自动计算距离、时长、累计爬升、配速，并合并到历史训练数据中。",
        "drop_title": "选择或拖入你的 GPX 文件",
        "drop_desc": "选择 `.gpx` 轨迹文件，体验类似 Strava 的活动上传流程。",
        "workout_type": "训练类型",
        "rpe": "RPE 1-10",
        "rpe_placeholder": "例如 6",
        "notes": "备注",
        "notes_placeholder": "身体状态、天气、补给、疼痛、心率异常等",
        "upload_gpx": "上传 GPX",
        "view_report": "查看报告",
        "recent_activities": "最近活动",
        "recent_desc": "最近上传会像活动流一样出现在这里。",
        "resources_title": "跑步训练资源",
        "resources_desc": "这里可以放训练文章、比赛经验、备赛知识、装备链接或你常用的参考资料。",
        "read_article": "阅读文章",
        "no_activities": "还没有活动。上传一个 GPX 文件开始。",
        "pace": "配速",
        "duration": "时长",
        "elev": "爬升 m",
        "no_notes": "暂无备注",
        "not_found": "页面不存在",
        "choose_gpx": "请选择 GPX 文件。",
        "success": "上传成功",
        "easy": "轻松跑",
        "recovery": "恢复跑",
        "long": "长距离",
        "tempo": "节奏跑",
        "threshold": "阈值跑",
        "interval": "间歇",
        "race": "比赛",
    },
    "en": {
        "upload": "Upload",
        "report": "Report",
        "ai_context": "AI Context",
        "upload_title": "Upload GPX Activity",
        "upload_desc": "Import GPX files exported from your watch, phone, or running app. The app calculates distance, duration, elevation gain, and pace, then merges the activity into your training history.",
        "drop_title": "Choose or drop your GPX file",
        "drop_desc": "Select a `.gpx` track file for a Strava-like activity upload flow.",
        "workout_type": "Workout Type",
        "rpe": "RPE 1-10",
        "rpe_placeholder": "e.g. 6",
        "notes": "Notes",
        "notes_placeholder": "Body state, weather, fueling, pain, abnormal heart rate, etc.",
        "upload_gpx": "Upload GPX",
        "view_report": "View Report",
        "recent_activities": "Recent Activities",
        "recent_desc": "Recent uploads appear here as an activity feed.",
        "resources_title": "Training Resources",
        "resources_desc": "A place for useful articles, race preparation notes, gear links, and references.",
        "read_article": "Read Article",
        "no_activities": "No activities yet. Upload a GPX file to start.",
        "pace": "pace",
        "duration": "duration",
        "elev": "elev m",
        "no_notes": "No notes",
        "not_found": "Not Found",
        "choose_gpx": "Please choose a GPX file.",
        "success": "Uploaded",
        "easy": "Easy",
        "recovery": "Recovery",
        "long": "Long Run",
        "tempo": "Tempo",
        "threshold": "Threshold",
        "interval": "Interval",
        "race": "Race",
    },
}


RESOURCE_LINKS = {
    "zh": [
        {
            "title": "马拉松训练周期怎么安排",
            "desc": "基础期、专项期、减量期的跑量和强度安排思路。",
            "url": "https://www.runnersworld.com/training/",
        },
        {
            "title": "RPE 主观强度使用指南",
            "desc": "用 1-10 分记录训练体感，帮助判断疲劳和恢复。",
            "url": "https://www.trainingpeaks.com/blog/joe-friel-s-quick-guide-to-setting-zones/",
        },
        {
            "title": "长距离跑补给参考",
            "desc": "长距离训练和比赛日的碳水、饮水、电解质补给原则。",
            "url": "https://www.runnersworld.com/nutrition-weight-loss/",
        },
    ],
    "en": [
        {
            "title": "Marathon Training Basics",
            "desc": "Build a simple structure for base, specific, and taper phases.",
            "url": "https://www.runnersworld.com/training/",
        },
        {
            "title": "Using RPE",
            "desc": "Track perceived effort from 1-10 to understand fatigue and recovery.",
            "url": "https://www.trainingpeaks.com/blog/joe-friel-s-quick-guide-to-setting-zones/",
        },
        {
            "title": "Long Run Fueling",
            "desc": "Carbs, fluids, and electrolytes for long runs and race day.",
            "url": "https://www.runnersworld.com/nutrition-weight-loss/",
        },
    ],
}


def normalize_lang(value: str | None) -> str:
    return "en" if value == "en" else "zh"


def page_shell(title: str, body: str, lang: str = "zh") -> bytes:
    lang = normalize_lang(lang)
    text = TEXT[lang]
    return f"""<!doctype html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <style>
    :root {{
      --bg: #f4f5f2;
      --panel: #fff;
      --ink: #20282b;
      --muted: #647071;
      --line: #d9dfdb;
      --orange: #fc4c02;
      --green: #15785e;
      --blue: #2d6f9f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
    }}
    header {{
      background: #11191c;
      color: white;
      border-bottom: 4px solid var(--orange);
    }}
    .nav {{
      width: min(1160px, calc(100% - 32px));
      margin: 0 auto;
      min-height: 62px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
    }}
    .brand {{ font-size: 22px; font-weight: 800; letter-spacing: 0; }}
    .brand span {{ color: var(--orange); }}
    .links {{ display: flex; gap: 10px; align-items: center; }}
    .links a, .button {{
      appearance: none;
      border: 1px solid transparent;
      border-radius: 6px;
      background: var(--orange);
      color: white;
      padding: 9px 13px;
      text-decoration: none;
      font-weight: 700;
      font-size: 14px;
      cursor: pointer;
    }}
    .links a.secondary, .button.secondary {{ background: transparent; border-color: rgba(255,255,255,.28); }}
    main {{ width: min(1160px, calc(100% - 32px)); margin: 26px auto 52px; }}
    .layout {{ display: grid; grid-template-columns: minmax(0, .92fr) minmax(360px, .48fr); gap: 18px; align-items: start; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 8px 24px rgba(28, 40, 43, .06);
    }}
    .upload {{ padding: 22px; }}
    h1 {{ margin: 0 0 8px; font-size: clamp(28px, 4vw, 44px); letter-spacing: 0; }}
    h2 {{ margin: 0 0 14px; font-size: 18px; letter-spacing: 0; }}
    p {{ color: var(--muted); line-height: 1.6; }}
    .drop {{
      margin: 18px 0;
      padding: 30px 18px;
      border: 2px dashed #b9c2bd;
      border-radius: 8px;
      text-align: center;
      background: #fbfcfb;
    }}
    .drop strong {{ display: block; font-size: 20px; margin-bottom: 8px; }}
    input[type=file] {{ width: 100%; max-width: 430px; }}
    .form-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 14px; }}
    label {{ display: grid; gap: 6px; font-size: 13px; color: #405052; font-weight: 700; }}
    input, select, textarea {{
      width: 100%;
      border: 1px solid #cfd7d3;
      border-radius: 6px;
      padding: 10px 11px;
      font: inherit;
      color: var(--ink);
      background: white;
    }}
    textarea {{ min-height: 88px; resize: vertical; }}
    .full {{ grid-column: 1 / -1; }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-top: 16px; }}
    .feed {{ padding: 0; overflow: hidden; }}
    .feed-head {{ padding: 16px 18px; border-bottom: 1px solid var(--line); }}
    .activity {{ padding: 16px 18px; border-bottom: 1px solid var(--line); }}
    .activity:last-child {{ border-bottom: 0; }}
    .activity-title {{ font-weight: 800; margin-bottom: 10px; }}
    .resources {{ margin-top: 18px; padding: 18px; }}
    .resource-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 14px; }}
    .resource-link {{
      display: block;
      min-height: 118px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfb;
      color: inherit;
      text-decoration: none;
    }}
    .resource-link:hover {{ border-color: #9eb5ac; background: #f3f7f5; }}
    .resource-title {{ font-weight: 800; margin-bottom: 8px; }}
    .resource-desc {{ color: var(--muted); font-size: 13px; line-height: 1.5; }}
    .resource-meta {{ margin-top: 12px; color: var(--green); font-size: 12px; font-weight: 800; }}
    .article {{ padding: 24px; max-width: 900px; margin: 0 auto; }}
    .article-body {{ color: #2e3b3f; line-height: 1.78; }}
    .article-body h2 {{ margin-top: 28px; padding-top: 18px; border-top: 1px solid var(--line); }}
    .article-body ul {{ margin: 8px 0 18px; padding-left: 22px; }}
    .article-body li {{ margin: 7px 0; }}
    .article-actions {{ margin-bottom: 18px; }}
    .stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }}
    .stat {{ background: #f6f8f6; border-radius: 6px; padding: 10px; }}
    .stat-value {{ font-size: 20px; font-weight: 800; }}
    .stat-label {{ color: var(--muted); font-size: 12px; margin-top: 2px; }}
    .notice {{ padding: 12px 14px; border-radius: 8px; margin-bottom: 16px; border: 1px solid var(--line); background: #fff; }}
    .notice.ok {{ border-color: #acd1c4; background: #eef8f4; }}
    .notice.err {{ border-color: #e4aaa0; background: #fff1ee; }}
    iframe {{ width: 100%; height: 760px; border: 0; border-radius: 8px; background: white; }}
    @media (max-width: 900px) {{
      .layout, .form-grid, .resource-grid {{ grid-template-columns: 1fr; }}
      .links {{ flex-wrap: wrap; justify-content: flex-end; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="nav">
      <div class="brand">Marathon<span>Coach</span></div>
      <nav class="links">
        <a class="secondary" href="/?lang={lang}">{esc(text["upload"])}</a>
        <a class="secondary" href="/report?lang={lang}" target="_blank">{esc(text["report"])}</a>
        <a href="/context" target="_blank">{esc(text["ai_context"])}</a>
        <a class="secondary" href="/?lang=zh">中文</a>
        <a class="secondary" href="/?lang=en">English</a>
      </nav>
    </div>
  </header>
  <main>{body}</main>
</body>
</html>""".encode("utf-8")


def activity_card(run: Run, lang: str = "zh") -> str:
    text = TEXT[normalize_lang(lang)]
    workout = text.get(run.workout_type, run.workout_type.title())
    return f"""
    <article class="activity">
      <div class="activity-title">{esc(run.date.isoformat())} · {esc(workout)}</div>
      <div class="stats">
        <div class="stat"><div class="stat-value">{run.distance_km:.2f}</div><div class="stat-label">km</div></div>
        <div class="stat"><div class="stat-value">{fmt_pace(run.pace_min_km)}</div><div class="stat-label">{esc(text["pace"])}</div></div>
        <div class="stat"><div class="stat-value">{run.duration_min:.0f}</div><div class="stat-label">{esc(text["duration"])} min</div></div>
      </div>
      <p>{esc(run.notes or text["no_notes"])}</p>
    </article>
    """


def slugify(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", value.strip()).strip("-")
    return slug or "article"


def article_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def article_description(content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        return stripped[:96]
    return ""


def load_articles() -> list[dict[str, str]]:
    if not ARTICLE_DIR.exists():
        return []
    articles = []
    for path in sorted(ARTICLE_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        title = article_title(content, path.stem)
        articles.append(
            {
                "title": title,
                "desc": article_description(content),
                "slug": path.stem,
                "content": content,
            }
        )
    return articles


def render_article_body(content: str) -> str:
    blocks: list[str] = []
    list_items: list[str] = []

    def flush_list() -> None:
        if list_items:
            blocks.append("<ul>" + "".join(list_items) + "</ul>")
            list_items.clear()

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            flush_list()
            continue
        if line.startswith("# "):
            flush_list()
            blocks.append(f"<h1>{esc(line[2:].strip())}</h1>")
        elif line.startswith("## "):
            flush_list()
            blocks.append(f"<h2>{esc(line[3:].strip())}</h2>")
        elif line.startswith("- "):
            list_items.append(f"<li>{esc(line[2:].strip())}</li>")
        else:
            flush_list()
            blocks.append(f"<p>{esc(line)}</p>")
    flush_list()
    return "\n".join(blocks)


def article_page(slug: str, lang: str = "zh") -> bytes:
    lang = normalize_lang(lang)
    for article in load_articles():
        if article["slug"] == slug:
            body = f"""
            <section class="panel article">
              <div class="article-actions">
                <a class="button secondary" href="/upload?lang={lang}">{esc(TEXT[lang]["upload"])}</a>
              </div>
              <div class="article-body">{render_article_body(article["content"])}</div>
            </section>
            """
            return page_shell(article["title"], body, lang)
    return page_shell(TEXT[lang]["not_found"], f"<h1>{esc(TEXT[lang]['not_found'])}</h1>", lang)


def resource_panel(lang: str = "zh") -> str:
    lang = normalize_lang(lang)
    text = TEXT[lang]
    article_links = "".join(
        f"""
        <a class="resource-link" href="/article/{quote(item["slug"])}?lang={lang}">
          <div class="resource-title">{esc(item["title"])}</div>
          <div class="resource-desc">{esc(item["desc"])}</div>
          <div class="resource-meta">{esc(text["read_article"])}</div>
        </a>
        """
        for item in load_articles()
    )
    links = "".join(
        f"""
        <a class="resource-link" href="{esc(item["url"])}" target="_blank" rel="noopener noreferrer">
          <div class="resource-title">{esc(item["title"])}</div>
          <div class="resource-desc">{esc(item["desc"])}</div>
        </a>
        """
        for item in RESOURCE_LINKS[lang]
    )
    return f"""
    <section class="panel resources">
      <h2>{esc(text["resources_title"])}</h2>
      <p>{esc(text["resources_desc"])}</p>
      <div class="resource-grid">{article_links}{links}</div>
    </section>
    """


def parse_multipart_form(handler: BaseHTTPRequestHandler) -> tuple[dict[str, str], dict[str, tuple[str, bytes]]]:
    content_type = handler.headers.get("Content-Type", "")
    content_length = int(handler.headers.get("Content-Length", "0"))
    body = handler.rfile.read(content_length)
    raw = (
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
        + body
    )
    message = BytesParser(policy=policy.default).parsebytes(raw)
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}
    for part in message.iter_parts():
        disposition = part.get_content_disposition()
        if disposition != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            files[name] = (filename, payload)
        else:
            fields[name] = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    return fields, files


def upload_page(message: str = "", error: bool = False, lang: str = "zh") -> bytes:
    lang = normalize_lang(lang)
    text = TEXT[lang]
    runs = load_runs(DEFAULT_LOG)
    latest = list(reversed(runs[-5:]))
    notice = ""
    if message:
        notice = f'<div class="notice {"err" if error else "ok"}">{esc(message)}</div>'
    feed = "".join(activity_card(run, lang) for run in latest) or f'<div class="activity"><p>{esc(text["no_activities"])}</p></div>'
    body = f"""
    {notice}
    <div class="layout">
      <section class="panel upload">
        <h1>{esc(text["upload_title"])}</h1>
        <p>{esc(text["upload_desc"])}</p>
        <form action="/upload?lang={lang}" method="post" enctype="multipart/form-data">
          <div class="drop">
            <strong>{esc(text["drop_title"])}</strong>
            <p>{esc(text["drop_desc"])}</p>
            <input type="file" name="gpx" accept=".gpx,application/gpx+xml" required>
          </div>
          <div class="form-grid">
            <label>{esc(text["workout_type"])}
              <select name="workout_type">
                <option value="easy">{esc(text["easy"])}</option>
                <option value="recovery">{esc(text["recovery"])}</option>
                <option value="long">{esc(text["long"])}</option>
                <option value="tempo">{esc(text["tempo"])}</option>
                <option value="threshold">{esc(text["threshold"])}</option>
                <option value="interval">{esc(text["interval"])}</option>
                <option value="race">{esc(text["race"])}</option>
              </select>
            </label>
            <label>{esc(text["rpe"])}
              <input name="rpe" type="number" min="1" max="10" step="0.5" placeholder="{esc(text["rpe_placeholder"])}">
            </label>
            <label class="full">{esc(text["notes"])}
              <textarea name="notes" placeholder="{esc(text["notes_placeholder"])}"></textarea>
            </label>
          </div>
          <div class="actions">
            <button class="button" type="submit">{esc(text["upload_gpx"])}</button>
            <a class="button secondary" href="/report?lang={lang}" target="_blank">{esc(text["view_report"])}</a>
          </div>
        </form>
      </section>
      <aside class="panel feed">
        <div class="feed-head">
          <h2>{esc(text["recent_activities"])}</h2>
          <p>{esc(text["recent_desc"])}</p>
        </div>
        {feed}
      </aside>
    </div>
    {resource_panel(lang)}
    """
    return page_shell(text["upload_title"], body, lang)


class MarathonCoachHandler(BaseHTTPRequestHandler):
    def send_html(self, content: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, content: dict[str, object]) -> None:
        payload = json.dumps(content, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        lang = normalize_lang(query.get("lang", ["zh"])[0])
        if parsed.path in {"/", "/upload"}:
            self.send_html(upload_page(query.get("message", [""])[0], query.get("error", ["0"])[0] == "1", lang))
            return
        if parsed.path.startswith("/article/"):
            slug = unquote(parsed.path.removeprefix("/article/"))
            self.send_html(article_page(slug, lang))
            return
        if parsed.path == "/report":
            self.send_html(generate_html_report(load_runs(DEFAULT_LOG), lang).encode("utf-8"))
            return
        if parsed.path == "/context":
            self.send_json(build_ai_context(load_runs(DEFAULT_LOG)))
            return
        self.send_html(page_shell(TEXT[lang]["not_found"], f"<h1>{esc(TEXT[lang]['not_found'])}</h1>", lang), 404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        lang = normalize_lang(query.get("lang", ["zh"])[0])
        text = TEXT[lang]
        if parsed.path != "/upload":
            self.send_html(page_shell(text["not_found"], f"<h1>{esc(text['not_found'])}</h1>", lang), 404)
            return
        try:
            fields, files = parse_multipart_form(self)
            if "gpx" not in files:
                raise ValueError(text["choose_gpx"])
            filename, content = files["gpx"]
            if not (filename or "").lower().endswith(".gpx"):
                raise ValueError(text["choose_gpx"])
            rpe_text = fields.get("rpe", "").strip()
            rpe = float(rpe_text) if rpe_text else None
            run = parse_gpx_bytes(
                content,
                workout_type=fields.get("workout_type", "easy"),
                rpe=rpe,
                notes=fields.get("notes", ""),
            )
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            safe_filename = Path(filename or "activity.gpx").name
            if (UPLOAD_DIR / safe_filename).exists():
                safe_filename = f"{datetime_stamp()}-{safe_filename}"
            (UPLOAD_DIR / safe_filename).write_bytes(content)
            merged = merge_runs(load_runs(DEFAULT_LOG), [run])
            write_runs(DEFAULT_LOG, merged)
            DEFAULT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
            (DEFAULT_REPORT_DIR / "latest_report.html").write_text(generate_html_report(merged, lang), encoding="utf-8")
            message = f"{text['success']}：{run.date.isoformat()} · {run.distance_km:.2f} km · {fmt_pace(run.pace_min_km)}"
            self.send_response(303)
            self.send_header("Location", f"/?lang={lang}&message={quote(message)}")
            self.end_headers()
        except Exception as exc:
            self.send_response(303)
            self.send_header("Location", f"/?lang={lang}&error=1&message={quote(str(exc))}")
            self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    try:
        server = ThreadingHTTPServer((host, port), MarathonCoachHandler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            raise SystemExit(
                f"端口 {port} 已被占用。请先关闭已有服务，或换一个端口启动：\n"
                f"python3 run.py web --port {port + 1}"
            ) from exc
        raise
    print(f"Marathon Coach web uploader: http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


def datetime_stamp() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d%H%M%S")
