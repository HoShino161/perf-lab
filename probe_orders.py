"""订单列表耗时随数据量变化的探测。

压测时 60 并发 QPS 掉头，怀疑 GET /api/orders 没分页、随订单增长变慢。
这个脚本直接造 N 条订单，测这条接口的耗时，看是不是线性的。
"""
from __future__ import annotations

import argparse
import sqlite3
import statistics
import time
import uuid
from pathlib import Path

import requests

DEFAULT_DB = Path("D:/vipe/代码/qa-lab/shop.db")


def seed_orders(db: Path, user_id: int, count: int) -> None:
    conn = sqlite3.connect(db)
    rows = [
        (user_id, "created", 10000, "2026-10-23 00:00:00")
        for _ in range(count)
    ]
    conn.executemany(
        "INSERT INTO orders(user_id, status, total_cents, created_at) VALUES (?,?,?,?)", rows
    )
    conn.commit()
    conn.close()


def clear_orders(db: Path, user_id: int) -> None:
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM orders WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def measure(base: str, token: str, rounds: int = 15) -> tuple[float, float]:
    """连续打同一个接口，返回中位数和 P95（毫秒）。"""
    times = []
    s = requests.Session()
    s.trust_env = False
    for _ in range(rounds):
        started = time.perf_counter()
        r = s.get(f"{base}/api/orders", headers={"Authorization": f"Bearer {token}"}, timeout=30)
        r.raise_for_status()
        times.append((time.perf_counter() - started) * 1000)
    s.close()
    times.sort()
    p95 = times[int(len(times) * 0.95) - 1]
    return statistics.median(times), p95


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--steps", default="0,100,1000,5000,20000")
    args = parser.parse_args()

    db = Path(args.db)

    s = requests.Session()
    s.trust_env = False
    name = f"probe{uuid.uuid4().hex[:8]}"
    s.post(f"{args.url}/api/auth/register", json={"username": name, "password": "probe123456"}, timeout=10)
    token = s.post(
        f"{args.url}/api/auth/login", json={"username": name, "password": "probe123456"}, timeout=10
    ).json()["token"]
    me = s.get(f"{args.url}/api/users/me", headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    uid = me["id"]
    s.close()

    print(f"探针账号 {name} (id={uid})")
    print(f"{'订单数':>8}  {'中位数(ms)':>10}  {'P95(ms)':>10}")
    print("-" * 34)

    total = 0
    for step in [int(x) for x in args.steps.split(",")]:
        add = step - total
        if add > 0:
            seed_orders(db, uid, add)
            total = step
        median, p95 = measure(args.url, token)
        print(f"{step:>8}  {median:>10.1f}  {p95:>10.1f}")

    clear_orders(db, uid)
    print("\n探针数据已清理")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
