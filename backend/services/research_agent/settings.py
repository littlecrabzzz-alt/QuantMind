"""Private node configuration. Never include credentials in checkpoints or code jobs."""

import hashlib
import json
import os
from pathlib import Path

from psycopg.conninfo import make_conninfo


class Settings:
    def __init__(self):
        self.data = Path(os.environ.get("RESEARCH_DATA_ROOT", "/data"))
        self.root = self.data / "research" / "agent"
        self.cfg = json.loads((self.data / "research/settings.json").read_text())
        self.host_data = Path(os.environ["HOST_RUNTIME_PATH"]) / "data"
        if (
            self.cfg["role"] != os.environ["QM_NODE_ROLE"]
            or Path(self.cfg["host_data"]) != self.host_data
        ):
            raise ValueError("研究节点与数据挂载不匹配")
        self.source = Path(self.cfg["source"])
        if not self.source.resolve().is_relative_to(
            (self.data / "research/inputs").resolve()
        ):
            raise ValueError("固定数据目录不在本节点输入区")
        if (
            hashlib.sha256((self.source / "manifest.json").read_bytes()).hexdigest()
            != self.cfg["manifest_sha256"]
        ):
            raise ValueError("输入清单已改变")
        self.base = json.loads((self.source / "snapshot/config.json").read_text())
        self.node = self.cfg["node_id"]
        self.root.mkdir(parents=True, exist_ok=True)
        secret_path = Path(
            os.environ.get("RESEARCH_LLM_CONFIG_FILE", "/run/secrets/research-llm.json")
        )
        if secret_path.stat().st_mode & 0o077:
            raise ValueError("模型凭据权限必须为0600")
        self.llm = json.loads(secret_path.read_text())
        if not self.llm["base_url"].startswith("https://"):
            raise ValueError("模型服务必须使用HTTPS")
        self.models = [
            m.split("[")[0]
            for m in self.llm.get(
                "models", self.llm.get("requested_models", ["glm-5.3-flash", "glm-5.3"])
            )
        ]
        self.internal_secret = os.environ["INTERNAL_CALL_SECRET"]
        if not self.internal_secret:
            raise ValueError("缺少内部服务凭据")
        self.gateway = os.environ.get("RESEARCH_ENGINE_URL") or os.environ.get(
            "INTERNAL_API_GATEWAY_URL", "http://quantmind:8001"
        )
        self.dsn = make_conninfo(
            host=os.environ.get("DB_HOST", "db"),
            port=os.environ.get("DB_PORT", "5432"),
            dbname=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
        )

    def host_path(self, path):
        return str(self.host_data / Path(path).relative_to(self.data))

    def workspace(self, ident):
        if len(ident) != 32 or any(c not in "0123456789abcdef" for c in ident):
            raise ValueError("课题编号无效")
        path = self.root / ident / "workspace"
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(
            0o777
        )  # Only this topic directory is mounted in UID 65534 containers.
        return path

    def inventory(self):
        return {
            "snapshot_id": self.cfg["snapshot_id"],
            "manifest_sha256": self.cfg["manifest_sha256"],
            "market": self.base.get("market"),
            "universe": self.base.get("universe"),
            "dates": self.base.get("split"),
            "features": self.base.get("features"),
            "portfolio": self.base.get("portfolio"),
            "fees": self.base.get("exchange"),
            "files": "/frozen/config.json; /frozen/quantdb; /frozen/qlib; /frozen/code",
            "tools": [
                "隔离Python和文件",
                "后台代码作业",
                "因子候选入库",
                "策略草稿保存到AI-IDE",
                "冻结模板训练与CnExchange回测",
            ],
            "limits": [
                "输入固定于此快照；其他市场/日期需要另备数据",
                "代码容器无法联网、访问密钥或实盘",
                "沙盒代码结果为探索证据；正式回测另做账务核验",
            ],
        }
