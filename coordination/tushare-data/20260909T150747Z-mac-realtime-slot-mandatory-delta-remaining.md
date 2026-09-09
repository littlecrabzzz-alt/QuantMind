# realtime runtime mandatory slot guard delta

更正20260909T150340Z候选：父review指出仅同日不足，旧同日slot仍可发请求。已加严格当前family配置epoch验证/匹配；缺失/非法/未来/非当日配置0HTTP(snapshot_invalid_config_epoch)，旧同日任务0HTTP(snapshot_superseded)。竞价历史和其他旧family仍不受影响。

独立branch codex/tushare-realtime-runtime；pick顺序必须99497d4e51f430982b105e25a111ce2a80cdd98c → 7de205f（完整SHA见branch），不能只上线前提交。delta仅registry11行逻辑、专项test、运行说明，无production/pipeline/配置改动。新slot不同ID可运行，旧拒绝保留状态/0tries/0attempts，未覆盖raw。

Python3.10全706tests/43.404s/OK，日志/tmp/tushare-realtime-runtime-slot-full310.log SHA8077382a87da5277cb616d6121de503060b1fa120808e90e8f99e5d26393fb03；最新专项10tests/1.040s（9API旧08slot→新09slot、缺配置实际run全0HTTP、非法配置/同日未来/上海日界），Ruff/diffcheck通过。父统一review/pick，无生产操作。
