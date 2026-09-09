# cross6 / sentiment7 固定版云端只读验收

text_contracts经现有cloud-compose quantmind python -S顺序执行已审SHA的两脚本，固定版data-41d91a26636bde7c6c83020e36671e012aa845af1c2ea8e07f6772aae9f80435；云端仅/tmp脚本和报告写入，无Tushare、DB修改、enable、publish。完成报告原字节base64回传Mac并校验云/本地SHA一致。此为云端固定版离线读取与sentiment loopback API验收，不是Mac镜像数据验收。

- cross6：12样本296已知列，verified_sample_only；所有raw→观察→Parquet、固定版独立去重/日期默认显式过滤通过，6个非空原码同日范围对照全列相同；0gap。
- sentiment7：49样本101已知列，verified_with_gaps；已存全部行保留验证，3动态非空对照全列相等。39gap为2个饱和+同两样本的non-success完整性提示+35 market_output_mapping_unverified；这不是2个空响应。tdx_member/kpl_concept_cons各3000行未证明完整，市场request身份保留不能推出供应商data_type业务映射已证实。
- sentiment只读loopback匿名401+7查询共8次，scope内全列相同、0HTTPgap。超过2000行数据集显式限定已观察code并记录排除数；不宣称全HTTP覆盖。全列样本通过不等于所有供应商未来字段、完整历史或PIT通过。

报告（云端与Mac同路径）：
- `/tmp/cross6-cloud-preenable.json`: `27b31865ead84a850b5490d2cf480747767ff46403fe75d91d529160344deb6f`；source probe SHA `6484d2fad354c689450cb12ba8787ea59e5525b2600bfe3116a47f76d8a1f733`，验证文件36。
- `/tmp/sentiment7-cloud-preenable.json`: `fc3e425104b0e5ed997ed5d09983c79b36ce19a6d267cece0c483a8350360ccd`；source probe SHA `56eb20129adc1a67659932dfbe38a1b08b9084b602cb4ac9d6165ece5b5df4f1`，验证文件147。

逐API行数/状态见 `/tmp/cross-sentiment-fixed-summary-20260909.json`。归属结束，交父据缺口决定启用。
