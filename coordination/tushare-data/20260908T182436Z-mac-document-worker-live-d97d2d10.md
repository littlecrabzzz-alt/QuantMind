# 独立附件消费已部署，首批待完成
- 任务01a0817d-7378-7673-9b7f-59c302713981，Mac协调云端；接续181254 worker ready。
- 发布基线5cba1cc，两端4323文件源码/Git核对通过，已推送master；实现db2bacf，进度更新f394a48。新consumer纳入快照停写名单。
- quantmind-tushare-document-worker已运行、1536MiB/0.5CPU/并发1；pipeline.config使用document_execution=worker、100份/90秒上限。API和附件同时active：5b26f8c3、f2334d59；原批次自然完成后只重启Tushare worker，无其他业务重启。
- 首次资源检查API336MiB、附件220MiB；当前只是单时点，不代替峰值/长期稳定性。云端Tushare目录du约4.52GiB，SSD剩316GiB，未触100GiB保留线。
- 下一步核对document-worker-status首轮实际结果、Mac镜像；global17类尚未生产探测启用，读取API尚未挂载/Agent接入；清单分块与历史完整性仍待继续。

验收补充：18:24:34Z首附件批次90.327秒处理15项，累计25 parsed/1 parse_timeout/18retry/123499pending；同周期API347请求成功发布。下一附件任务9e4e72ca已接收，两路运行恢复。完整目标未完成，保留parse_timeout与待下载，不宣称100份预算等于吞吐。
