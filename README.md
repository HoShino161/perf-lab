# perf-lab

给 [qa-lab](../qa-lab) 那个订单服务做压测。阶梯加压，每秒记一次快照，支持两组结果对比出图。

## 怎么跑

前置：qa-lab 的服务起在 8000 端口。

```bash
python prepare.py                 # 库存拉满 + 建压测账号，token 写进 .token
python loadgen.py --stages 10:20,30:30,60:30 --label baseline --token $(cat .token)
python report.py                  # 读 results/*.json，生成 results/report.html
```

## 参数

```
--url         目标地址，默认 http://127.0.0.1:8000
--token       下单和查单要带
--stages      并发数:持续秒数，逗号分隔，默认 10:20,30:30,60:30
--label       结果文件名前缀，默认 run
```

## 输出

`results/` 下三个文件：

```
{label}-{时间}.csv    逐秒快照，画曲线用
{label}-{时间}.json   每档汇总
report.html           对比报告
```

跑过的两组数据在 [docs/report.md](docs/report.md)。

## 流量模型

按权重随机选动作：列表 10、详情 6、查单 3、下单 1。删 `Scenario.weights` 可以改。

## 目录

```
prepare.py     库存重置 + 建压测账号
loadgen.py     阶梯压测器
report.py      生成 HTML 报告
results/       CSV、JSON、报告
docs/          压测结果
```

## 已知限制

- 发压端和被压端同一台机器，客户端也抢 CPU，60 并发以上的数据不准
- 流量按权重随机，不复现真实用户路径
- 每档之间不清空累计统计，只按档独立算 QPS

## 还没做

- 连接池、订单列表分页、换 PostgreSQL 后重跑
