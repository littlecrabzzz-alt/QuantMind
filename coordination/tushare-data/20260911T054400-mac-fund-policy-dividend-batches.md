# Tushare 基金行情、已购政策与分红历史生产批次

- master与云端源码已对齐`907ad7b5`；三套精确批次入口在Mac和生产镜像各通过23项组合测试。
- 基金行情360项全部done，44.713秒、259149行；政策/央行277项为189 done、85 empty、3 split_pending，38.062秒、3711行；分红360项为355 done、5 empty，44.455秒、17200行。
- 合计997次上游调用均为HTTP 200，429为0；997个object、997个observation和907个Parquet实体哈希全部通过。CURRENT保持`data-7be20672…`，本批未发布。
- 基金第一轮在上游前因操作员只读审计进程持有SQLite文件描述符安全失败，0次请求；该进程还导致05:35常规任务`f9861892…`在初始化提交时锁失败。进程关闭后重新冻结相同清单并完成，常规恢复任务`60a25fb1…`于176.329秒后成功。以后在线审计避免对5.4GB活动库做长全表扫描。
- worker与Beat已恢复healthy，worker为2GiB、restart0、OOM false。等待正常固定版发布与Mac单向镜像；完整历史、修订/PIT和RRG状态保持未完成。
- 机器证据：`docs/tushare-exact-history-batches-20260911.evidence.json`；权威闭包位于`validation/{fund-price,paid-policy,dividend}-batch-20260911/`。
