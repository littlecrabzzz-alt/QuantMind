# cross6 / sentiment7 Mac固定离线验收闭环

父明确标准mirror完成（8758新增/247648文件verified）后，text_contracts以已安装tushare-client venv，在固定data-41d91a26636bde7c6c83020e36671e012aa845af1c2ea8e07f6772aae9f80435执行两份原SHA verifier。均无cloud-api，脚本禁止socket/DNS/providersecret；无Tushare请求，无重跑mirror，无权威库修改。

两族 cloud/Mac六键逐结构完整相等：release_id、probe_report_sha256、probe_samples、dataset_checks、date_axis_overlap、gaps。cross6为verified_sample_only/0gap，sentiment7为verified_with_gaps/39gap（两饱和+同两样本non-success提示+35市场映射待证）；未降低限制。各验证36/147个原文观察Parquet引用。HTTP仅云端报告包含，未强行比较完整报告或宣称Mac测试HTTP。

- `/tmp/cross6-mac-verified.json` SHA256 `ebc9b7b608081a7a4771b9e94376448faf2eee528c680452897fe177f9385720`。
- `/tmp/sentiment7-mac-verified.json` SHA256 `93ead6a13669230315f47d181d8797d1e0837c38804c911d33ea1780ae85a19b`。

共同键证明 `/tmp/cross-sentiment-cloud-mac-common-verified.json` SHA256 `0288032e693747e7119d9067481dee40baef83102adb0a852a27c627d0ac0144`。父可据此结束固定版验收，后续自动history响应仍独立于本固定版。
