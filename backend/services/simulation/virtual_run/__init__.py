"""R01 虚拟运行（H2.2）：持续虚拟盘每日运行链路。

p02r owner（h2-scope.json H2.2）：交易日运行流水线、月度调仓+每日审查
语义、幂等/锁/恢复、无内置默认调度。账本引擎/身份复用 p03 的
``backend/services/simulation/replay/``（R01Ledger，r01vr- 前缀已合入），
不另写撮合。数据就绪门控消费 p02 日增量包接口（D1/D2 尚未合入时用
fixture stub，标注待联调）。

模块划分（h2-scope 冻结文件清单）：

- ``clock``    可控时钟（工程验收/故障注入不依赖真实等待）
- ``locks``    Redis 日锁（SET NX + TTL，双 worker/崩溃残留防护）
- ``states``   运行配置/阶段状态/心跳/run_status/停止恢复三段状态机
- ``gating``   每日数据就绪门控（日增量包身份五元组 + 质量检查）
- ``recovery`` 检查点存取与对账（复用 ReplayLedgerCheckpoint 语义）
- ``pipeline`` 交易日运行流水线（stage 幂等键 {run}:{date}:{stage}）
"""

from backend.services.simulation.virtual_run.clock import (
    FrozenClock,
    RunClock,
    SystemClock,
    shanghai,
)
from backend.services.simulation.virtual_run.pipeline import (
    DayRunResult,
    NeedsManualReview,
    VirtualRunPipeline,
)
from backend.services.simulation.virtual_run.states import (
    STAGES,
    VirtualRunConfig,
    make_task_id,
)

__all__ = [
    "RunClock",
    "SystemClock",
    "FrozenClock",
    "shanghai",
    "VirtualRunPipeline",
    "DayRunResult",
    "NeedsManualReview",
    "VirtualRunConfig",
    "STAGES",
    "make_task_id",
]
