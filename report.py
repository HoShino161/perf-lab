"""读 results/*.json 生成 HTML 对比报告。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"


def latest(prefix: str) -> Path | None:
    files = sorted(RESULTS.glob(f"{prefix}*.json"))
    return files[-1] if files else None


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def row_html(stage: dict) -> str:
    return (
        f"<tr><td>{stage['users']}</td><td>{stage['requests']}</td>"
        f"<td>{stage['qps']}</td><td>{stage['p50']}</td><td>{stage['p90']}</td>"
        f"<td>{stage['p95']}</td><td>{stage['p99']}</td>"
        f"<td>{stage['error_rate']}%</td></tr>"
    )


def build(base: dict | None, target: dict | None) -> str:
    labels: list[str] = []
    series: dict[str, dict[str, list]] = {}

    for name, data in (("基线", base), ("优化后", target)):
        if not data:
            continue
        users = [s["users"] for s in data["stages"]]
        if not labels:
            labels = users
        series[name] = {
            "qps": [s["qps"] for s in data["stages"]],
            "p95": [s["p95"] for s in data["stages"]],
        }

    table_base = "".join(row_html(s) for s in base["stages"]) if base else ""
    table_target = "".join(row_html(s) for s in target["stages"]) if target else ""

    def gain(metric: str) -> str:
        if not base or not target:
            return "-"
        a = base["stages"][-1][metric]
        b = target["stages"][-1][metric]
        if metric == "p95":
            return f"{a} → {b} ms（{(b - a) / a * 100:+.0f}%）"
        return f"{a} → {b}（{(b - a) / a * 100:+.0f}%）"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>压测报告</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  body {{ font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
         max-width: 900px; margin: 40px auto; padding: 0 20px; line-height: 1.7;
         color: #1a1a1a; }}
  h1 {{ font-size: 22px; font-weight: 500; }}
  h2 {{ font-size: 16px; font-weight: 500; margin-top: 34px;
        border-left: 3px solid #333; padding-left: 10px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin: 12px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 7px 10px; text-align: right; }}
  th {{ background: #f5f5f5; font-weight: 500; text-align: right; }}
  td:first-child, th:first-child {{ text-align: left; }}
  .note {{ background: #fafafa; border-left: 3px solid #bbb; padding: 10px 14px;
           font-size: 13px; color: #444; margin: 14px 0; }}
  code {{ background: #f2f2f2; padding: 1px 5px; border-radius: 3px; font-size: 12px; }}
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin: 18px 0; }}
  canvas {{ max-height: 260px; }}
</style>
</head>
<body>
<h1>电商订单服务压测报告</h1>
<p>被测服务：FastAPI + SQLite，单机本地。压测客户端与目标同机，数据仅用于横向对比，不代表生产容量。</p>

<h2>阶梯结果</h2>
<p>基线（单进程）：</p>
<table>
<tr><th>并发</th><th>请求数</th><th>QPS</th><th>P50</th><th>P90</th><th>P95</th><th>P99</th><th>错误率</th></tr>
{table_base}
</table>

<p>优化后：</p>
<table>
<tr><th>并发</th><th>请求数</th><th>QPS</th><th>P50</th><th>P90</th><th>P95</th><th>P99</th><th>错误率</th></tr>
{table_target}
</table>

<div class="charts">
  <div><canvas id="qpsChart"></canvas></div>
  <div><canvas id="p95Chart"></canvas></div>
</div>

<h2>优化对比（60 并发档）</h2>
<table>
<tr><th>指标</th><th>基线</th><th>优化后</th><th>变化</th></tr>
<tr><td>QPS</td><td>{base['stages'][-1]['qps'] if base else '-'}</td>
<td>{target['stages'][-1]['qps'] if target else '-'}</td><td>{gain('qps')}</td></tr>
<tr><td>P95</td><td>{base['stages'][-1]['p95'] if base else '-'} ms</td>
<td>{target['stages'][-1]['p95'] if target else '-'} ms</td><td>{gain('p95')}</td></tr>
</table>

<h2>口径说明</h2>
<p>QPS = 该档总请求数 ÷ 该档持续秒数。延迟为客户端侧测量，含网络与序列化开销。
每档开始时不清空累计统计，但 QPS 按档独立计算。</p>

<script>
const labels = {json.dumps(labels, ensure_ascii=False)};
const series = {json.dumps(series, ensure_ascii=False)};

function line(id, field, title, unit) {{
  const ctx = document.getElementById(id);
  new Chart(ctx, {{
    type: 'line',
    data: {{
      labels: labels,
      datasets: Object.entries(series).map(([name, v], i) => ({{
        label: name,
        data: v[field],
        borderColor: i === 0 ? '#c0392b' : '#2c7a4b',
        backgroundColor: 'transparent',
        borderWidth: 2,
        tension: 0.25,
        pointRadius: 4,
      }}))
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ position: 'bottom' }},
                  title: {{ display: true, text: title, font: {{ size: 13, weight: 'normal' }} }} }},
      scales: {{
        x: {{ title: {{ display: true, text: '并发数' }} }},
        y: {{ title: {{ display: true, text: unit }} }}
      }}
    }}
  }});
}}
line('qpsChart', 'qps', 'QPS 随并发变化', 'req/s');
line('p95Chart', 'p95', 'P95 随并发变化', 'ms');
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", help="基线汇总 json 前缀，默认 baseline")
    parser.add_argument("--target", help="优化后汇总 json 前缀，默认 after-4workers")
    parser.add_argument("--out", default="report.html")
    args = parser.parse_args()

    base_path = latest(args.baseline or "baseline")
    target_path = latest(args.target or "after-")
    if not base_path and not target_path:
        print("results/ 下没有汇总文件，先跑 loadgen.py")
        return 1

    base = load(base_path) if base_path else None
    target = load(target_path) if target_path else None

    out = RESULTS / args.out
    out.write_text(build(base, target), encoding="utf-8")
    print(f"报告已生成：{out}")
    if base_path:
        print(f"  基线：{base_path.name}")
    if target_path:
        print(f"  对比：{target_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
