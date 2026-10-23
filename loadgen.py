"""多线程压测器：阶梯加压 + 逐秒快照。

为什么不用 Locust：gevent 在 Windows 上装不利索，而我要的东西很简单——
按阶梯起线程、打指定秒数、每秒记一次快照。自己写反而更好控制发压节奏，
也能顺手把服务端 /metrics 一起拉下来存成 CSV。

用法：
    python loadgen.py --stages 10:20,30:30,60:30 --label baseline
    python loadgen.py --stages 60:60 --label after-4workers
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

RESULTS = Path(__file__).resolve().parent / "results"


# ---------- 统计 ----------

@dataclass
class Stats:
    latencies: list[float] = field(default_factory=list)
    ok: int = 0
    fail: int = 0
    by_status: dict[int, int] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, elapsed_ms: float, status: int) -> None:
        with self.lock:
            self.latencies.append(elapsed_ms)
            self.by_status[status] = self.by_status.get(status, 0) + 1
            if 200 <= status < 400:
                self.ok += 1
            else:
                self.fail += 1

    def snapshot(self) -> dict:
        with self.lock:
            data = sorted(self.latencies)
            total = len(data)
            return {
                "total": total,
                "ok": self.ok,
                "fail": self.fail,
                "p50": pct(data, 50),
                "p90": pct(data, 90),
                "p95": pct(data, 95),
                "p99": pct(data, 99),
                "avg": round(sum(data) / total, 2) if total else 0,
                "by_status": dict(sorted(self.by_status.items())),
            }


def pct(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return round(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo), 2)


# ---------- 流量模型 ----------

class Scenario:
    """按权重选动作。权重参考真实电商：看得多、买得少。"""

    def __init__(self, base_url: str, token: str, product_ids: list[int]):
        self.base = base_url.rstrip("/")
        self.token = token
        self.product_ids = product_ids
        self.weights = [("list", 10), ("detail", 6), ("orders", 3), ("create", 1)]

    def pick(self) -> str:
        names = [w[0] for w in self.weights]
        weights = [w[1] for w in self.weights]
        return random.choices(names, weights=weights, k=1)[0]

    def run(self, session: requests.Session) -> int:
        action = self.pick()
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}

        if action == "list":
            r = session.get(f"{self.base}/api/products", headers=headers, timeout=10)
        elif action == "detail":
            pid = random.choice(self.product_ids)
            r = session.get(f"{self.base}/api/products/{pid}", headers=headers, timeout=10)
        elif action == "orders":
            r = session.get(f"{self.base}/api/orders", headers=headers, timeout=10)
        else:
            pid = random.choice(self.product_ids)
            r = session.post(
                f"{self.base}/api/orders",
                json={"items": [{"product_id": pid, "qty": 1}]},
                headers=headers,
                timeout=10,
            )
        return r.status_code


def worker(scenario: Scenario, stats: Stats, stop_at: float) -> None:
    session = requests.Session()
    session.trust_env = False  # 本机服务不走代理
    try:
        while time.time() < stop_at:
            started = time.perf_counter()
            try:
                status = scenario.run(session)
            except requests.RequestException:
                status = -1  # 连接失败/超时单独记
            stats.record((time.perf_counter() - started) * 1000, status)
    finally:
        session.close()


# ---------- 主流程 ----------

def parse_stages(raw: str) -> list[tuple[int, int]]:
    stages = []
    for part in raw.split(","):
        users, secs = part.split(":")
        stages.append((int(users), int(secs)))
    return stages


def fetch_metrics(base_url: str) -> dict:
    try:
        r = requests.get(f"{base_url}/metrics", timeout=5)
        r.raise_for_status()
    except requests.RequestException:
        return {}
    out = {}
    for line in r.text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        out[line.rsplit(" ", 1)[0]] = float(line.rsplit(" ", 1)[1])
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default="", help="下单/查单需要的 token")
    parser.add_argument("--stages", default="10:20,30:30,60:30", help="并发数:持续秒数，逗号分隔")
    parser.add_argument("--label", default="run")
    parser.add_argument("--product-ids", default="1,2")
    args = parser.parse_args()

    RESULTS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    csv_path = RESULTS / f"{args.label}-{stamp}.csv"
    summary_path = RESULTS / f"{args.label}-{stamp}.json"

    product_ids = [int(x) for x in args.product_ids.split(",")]
    stages = parse_stages(args.stages)
    summary = {"label": args.label, "url": args.url, "stages": []}

    print(f"目标 {args.url}  |  阶梯 {stages}")
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["stage_users", "elapsed_s", "total", "qps", "ok", "fail", "p50", "p90", "p95", "p99"]
        )

        for users, duration in stages:
            print(f"\n== {users} 并发 / {duration}s ==")
            scenario = Scenario(args.url, args.token, product_ids)
            stats = Stats()
            stop_at = time.time() + duration
            threads = [
                threading.Thread(target=worker, args=(scenario, stats, stop_at), daemon=True)
                for _ in range(users)
            ]
            for t in threads:
                t.start()

            began = time.time()
            last_total = 0
            while time.time() < stop_at:
                time.sleep(1)
                snap = stats.snapshot()
                elapsed = int(time.time() - began)
                qps = snap["total"] - last_total
                last_total = snap["total"]
                writer.writerow(
                    [users, elapsed, snap["total"], qps, snap["ok"], snap["fail"],
                     snap["p50"], snap["p90"], snap["p95"], snap["p99"]]
                )
                print(
                    f"  {elapsed:>3}s  qps={qps:>4}  总={snap['total']:>6}  "
                    f"p95={snap['p95']:>7}ms  fail={snap['fail']}",
                    end="\r",
                )

            for t in threads:
                t.join(timeout=5)

            final = stats.snapshot()
            stage_result = {
                "users": users,
                "duration_s": duration,
                "requests": final["total"],
                "qps": round(final["total"] / duration, 1),
                "ok": final["ok"],
                "fail": final["fail"],
                "error_rate": round(final["fail"] / final["total"] * 100, 2) if final["total"] else 0,
                "p50": final["p50"],
                "p90": final["p90"],
                "p95": final["p95"],
                "p99": final["p99"],
                "avg": final["avg"],
                "by_status": {str(k): v for k, v in final["by_status"].items()},
            }
            summary["stages"].append(stage_result)
            print(
                f"\n  → 完成 {final['total']} 请求，QPS {stage_result['qps']}，"
                f"P95 {final['p95']}ms，失败 {final['fail']}"
            )

    summary["server_metrics_end"] = fetch_metrics(args.url)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n明细 {csv_path}")
    print(f"汇总 {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
