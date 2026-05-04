# Marathon Coach AI Project

个人马拉松训练教练项目。每次上传训练数据后，不只看单次训练，还会结合最近一周、月份、季度、年度的训练历史，判断当前状态、负荷变化、风险点和下一步改进方向。

## 项目流程

当前主流程是网页上传 GPX 训练数据：

1. 在网页选择手表、手机或跑步 App 导出的 `.gpx` 文件。
2. 填写训练类型、RPE 和备注。
3. 系统解析距离、时长、日期、累计爬升、平均配速和可用的心率数据。
4. 训练记录合并写入 `data/training_log.csv`。
5. 网页报告页实时可视化展示周、月、季度、年度训练总结，并生成 AI 教练 JSON 上下文。

## CSV 数据格式

上传 CSV，字段如下：

```csv
date,distance_km,duration_min,avg_hr,rpe,elevation_m,workout_type,notes
2026-05-01,14.00,78,159,7,55,tempo,steady but tired
```

核心字段是 `date`、`distance_km`、`duration_min`。其他字段可以为空。

`workout_type` 建议使用：`easy`、`recovery`、`long`、`tempo`、`threshold`、`interval`、`race`。

CSV 仍可通过命令行导入，适合批量补历史训练。

## 命令行使用

```bash
cd /Users/huwei/Downloads/code/ai_project/marthon_coach_ai
python3 run.py import examples/sample_upload.csv
python3 run.py report
python3 run.py context
```

默认训练日志写入 `data/training_log.csv`，HTML 报告写入 `data/reports/latest_report.html`。

如果仍然需要 Markdown 报告：

```bash
python3 run.py report --format markdown
```

## 网页上传 GPX

启动本地网页：

```bash
python3 run.py web
```

打开：

```text
http://127.0.0.1:8765
```

页面支持选择 GPX 文件、填写训练类型、RPE 和备注。上传后会自动解析：

- 距离
- 时长
- 平均配速
- 累计爬升
- 日期

上传文件会保存到 `data/uploads/`，训练记录会合并到 `data/training_log.csv`，报告页可从网页右上角打开。

可以用示例 GPX 测试：

```text
examples/sample_activity.gpx
```

上传成功后会生成或更新：

```text
data/training_log.csv
data/reports/latest_report.html
data/uploads/
```

## AI 教练上下文

`python3 run.py context` 会输出一个紧凑 JSON，包含：

- 最新一次训练表现
- 最近 8 周周总结
- 最近 12 个月月总结
- 最近 8 个季度总结
- 最近 5 年年度总结
- 负荷、长距离跑比例、强度课数量等风险和改进信号

后续可以把这段 JSON 发送给 OpenAI API，让模型生成更自然的训练建议、下一周训练安排和比赛周期调整。

## Skill

本项目内置 Codex skill：

```text
/Users/huwei/Downloads/code/ai_project/marthon_coach_ai/skills/marathon-coach
```

分析跑步训练、马拉松备赛、上传训练 CSV、生成周期总结时，可以显式说：

```text
Use $marathon-coach to analyze this training upload.
```
