# Tushare 发布闭包与公告首批生产验收

- master和云端源码基线为`9c383c8d`。发布任务软/硬时限已部署为600/630秒；首个到期任务138.544秒发布`data-051d825b…`，固定版四批任务引用和物理哈希闭包通过。
- Mac LaunchAgent第148轮下载8991个文件并核验725606个文件，exit 0、错误日志0；断网、空Token、只读挂载的`fund_daily@20190410`读取返回5行且0上游调用。
- 停写窗口内基金行情第3批360次、分红第2批360次、公告第1批221次，共941次调用；940个HTTP 200、0个429、1个可重试ReadTimeout，返回1574777行。公告219项因2000行上限继续日期二分，140项未在90秒窗口启动。
- 第一份公告操作员闭包因错误的pending假设失败并保留；v2按可重试传输错误语义重新核验，所有完整payload实体哈希通过。worker和Beat恢复healthy、restart0、OOM false，消费已恢复。
- 新三批仍在活动authority中，等待下一次正常小时发布和Mac单向镜像。全历史、历史修订/PIT和RRG数据准入未闭合；证据见`docs/tushare-publication-announcement-wave2-20260911.evidence.json`。
