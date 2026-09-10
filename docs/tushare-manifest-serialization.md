# 固定清单：复用 C 编码分块，消除整份字符串拼接

基线 `8193d14`。此候选与未合入的三阶段发布 `bbc818a` 独立：**不引入配置、checkpoint、调度或清单格式变更**，只替换最终清单编码和持久化。没有生产操作。

父提供的新证据是 `56d6bf71` 及重试 `ae6f2d6f` 均在160秒停于 `publish → json_bytes(content) → json.dumps → ''.join(chunks)`。我们没有再次读取生产。CPython3.10源码和本地测试确认，当前参数下json.dumps先以C编码器生成字符串块，再把所有块join成一个字符串，最后json_bytes又将完整字符串转成UTF8 bytes。一个非ASCII字符可以使整个join结果采用更宽的Unicode存储；源码frame不能单独证明云端OOM/CPU原因，但这个全量复制本身可以直接去掉。

## 最小修改

新增同模块 `serialize_manifest_file(directory, content, timing)`。它调用与原json.dumps相同的 `JSONEncoder(ensure_ascii=False, sort_keys=True).iterencode(content, _one_shot=True)`，逐块UTF8编码、写私有临时文件并累积SHA256，flush/fsync完成后返回路径与SHA。`_one_shot=True`保留C编码器，避免切换到逐节点的Python编码热循环；若C编码器不可用，标准库生成器退路仍保持相同字节。

发布者据SHA得到原来的release_id，随后将临时文件rename到标准manifest位置。不可变文件和release目录持久化后才调用原atomic_json切CURRENT。已有目标文件须流式核验SHA；损坏目标不能因名字正确而被跳过。错误/软中断会清理本次私有临时文件，不删除旧release、原文或他人临时文件。硬杀死可能留下未发布的`.manifest-*.tmp`，不进入固定清单；重跑仍沿原重建/retain协议，不把该文件当checkpoint。

分隔符、排序、Unicode、浮点（含负零/原有NaN规则）、null、未知列、全部历史清单均不变。文件mode遵循原atomic_bytes的umask，不使用mkstemp的额外0600限制。旧CURRENT在编码/写盘失败时保持；seal后指针失败可校验同一文件重试。noop不进行序列化。serialize_manifest阶段现在包含临时文件写盘/fsync，因此跨版本比较应合并原serialize+write两个阶段；新增 `publish_timing.serialization` 给chunk生成、总时长、块数、最大块与字节数。

**仍是O(manifest)内存**：C编码器会保留一组字符串块，源对象图也保留；单个巨大字符串仍可能产生巨大块。此改动去掉整份join字符串及整份UTF8副本，不是常量内存/可恢复流式数据库发布。没有提高160/180秒限制，也未改SQL、document_index或retain_previous。

## 代表性大清单结果

[机器证据](tushare-manifest-serialization.evidence.json)记录18个独立Python3.10.19进程，每种Unicode宽度旧/新各3次、交替顺序。每份包含250000个文件引用、750000个闭包子节点、62500个缺口，约102MB；只在临时目录使用合成元数据，不访问源API/数据库。下表为**三次中最长的编码+SHA+写盘+fsync总时长**及进程峰值RSS，不把encoder生成块时间单独冒充整个序列化。

| 内容 | 原最长 | 新最长 | 最长耗时下降 | 原峰值RSS → 新峰值RSS |
|---|---:|---:|---:|---:|
| ASCII | 0.3553s | 0.3443s | 3.1% | 623.9MB → 432.3MB |
| 中文BMP | 0.4033s | 0.3549s | 12.0% | 736.9MB → 443.8MB |
| 中文及非BMP | 0.4240s | 0.3674s | 13.3% | 956.8MB → 459.9MB |

全部旧/新最终文件SHA一致。最长单次encoder调用亦下降：中文0.3631→0.3115s，非BMP0.3838→0.3206s。这是有实际下降的本地代表性样本；不是生产同等百分比提速或整个tick必低于160秒的保证。ASCII收益较小，冷文件系统/并发文档写入/大SQL/云端cgroup差异仍可主导总时间。

## 验证与集成建议

7项新测试覆盖分块与Python退路精确字节、Unicode/float/null/大整数、非法值/循环/孤立代理项、部分编码/fsync/rename/pointer失败、坏seal拒绝、原权限和noop。既有三代真实Mock source→raw/obs/Parquet→manifest、全部gap/attempt/revision/archive字节等价和weakref释放断言继续通过；两条旧测试只把故障/生命周期注入点调整到实际新encoder入口。合计79项相关Python3.10测试、Ruff和diffcheck通过；AST证明除publish及新helper外（包括tick/文档登记）不变。

```bash
PYTHONPATH=scripts:. python -m unittest \
  test_tushare_manifest_serialization test_tushare_publish_timing \
  test_tushare_publish_interval test_tushare_publish_equivalence \
  test_tushare_retain_reuse test_tushare_archive \
  test_tushare_extended_pipeline test_tushare_planning_interval \
  test_tushare_partition_closure
python scripts/benchmark_tushare_manifest_serialization.py \
  --count 250000 --repeats 3 --output /tmp/manifest-serialization-new.json
```

建议父审查后可受控集成这个默认路径修复，沿既有流程核对一次实际发布的阶段时间、SHA/CURRENT及Mac固定镜像；无需新配置或新模块安装名单。不能因本候选已通过就声明生产阻塞解除。若仍软超时，继续按实际stage timing处理；不压缩历史/跳过缺口，也不拿前一未启用staged方案混入本轮。
