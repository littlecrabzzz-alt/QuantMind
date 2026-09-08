# Global与财务批量能力实测
- 任务01a0817d-7378-7673-9b7f-59c302713981，Mac父协调云端，进度进行中；基线39fff3d。
- 父负责global/VIP小样本请求、权限与批量阈值证据、后续global/structured合同修正；text agent独占pipeline父子分区v4与新增test，structured agent独占API/QuantBot工具接入。临时探测脚本/tmp/tushare-global-vip-probe.py，不携带凭据。
- 云端仅在pipeline.lock空闲时通过现有quantmind容器发23个显式只读API请求；原始响应/观察/Parquet和attempts仍写正式Tushare链路并发布。未证实饱和只保留quality，避免按普通100阈值自动扩出数万股票请求。共享账号/API持久频控照常保留。
- 先暂停专属acquire消费等待当前批次自然完成；附件worker持续。探测后恢复原consumer，不动其他服务。全部API/历史尚未完成，未知与拒绝显式记录。
