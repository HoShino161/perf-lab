"""压测前准备：把库存拉满、建一个压测账号。

被测服务的库存是有限的，压几分钟就会被买空，
后面所有下单请求都会返回 409，压测结果就没意义了。

库存只能从数据库改——加一个「改库存」的管理接口等于给被测服务开后门。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import uuid
from pathlib import Path

import requests

DEFAULT_QA_DB = Path("D:/vipe/代码/qa-lab/shop.db")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--qa-db", default=str(DEFAULT_QA_DB))
    parser.add_argument("--stock", type=int, default=1_000_000)
    args = parser.parse_args()

    db = Path(args.qa_db)
    if not db.exists():
        print(f"找不到被测库：{db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db)
    conn.execute("UPDATE products SET stock = ?", (args.stock,))
    conn.commit()
    rows = conn.execute("SELECT id, name, stock FROM products ORDER BY id").fetchall()
    conn.close()
    print(f"库存已重置为 {args.stock}：")
    for pid, name, stock in rows:
        print(f"  #{pid} {name}  stock={stock}")

    session = requests.Session()
    session.trust_env = False

    name = f"perf{uuid.uuid4().hex[:8]}"
    pwd = "perf123456"
    session.post(f"{args.url}/api/auth/register", json={"username": name, "password": pwd}, timeout=10)
    r = session.post(f"{args.url}/api/auth/login", json={"username": name, "password": pwd}, timeout=10)
    if r.status_code != 200:
        print(f"建压测账号失败：{r.status_code} {r.text}", file=sys.stderr)
        return 1

    token = r.json()["token"]
    (Path(__file__).resolve().parent / ".token").write_text(token, encoding="utf-8")
    print(f"\n压测账号 {name} 已就绪，token 写入 .token")
    print(f"下单时用：--token {token[:16]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
