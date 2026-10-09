"""统一日志配置模块"""

import errno
import logging
import logging.handlers
import sys
import time
from pathlib import Path

from config.settings import settings


class ResilientRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """On a full disk, pause file writes for 30s; console logging continues."""

    retry_interval = 30.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._retry_at = 0.0
        self._dropped = 0
        self._write_failed = False

    @staticmethod
    def _notice(message):
        # Never recurse through logging, or expose original record contents.
        try:
            sys.stderr.write(message + "\n")
        except OSError:
            pass

    def emit(self, record):
        if time.monotonic() < self._retry_at:
            self._dropped += 1
            return
        self._write_failed = False
        super().emit(record)
        if self._dropped and not self._write_failed:
            self._notice(f"File logging recovered; skipped {self._dropped} records")
            self._dropped = 0
            self._retry_at = 0.0

    def handleError(self, record):
        exc = sys.exc_info()[1]
        if not isinstance(exc, OSError) or exc.errno != errno.ENOSPC:
            self._write_failed = True
            return super().handleError(record)
        self._write_failed = True
        self._dropped += 1
        self._retry_at = time.monotonic() + self.retry_interval
        # Reopen on recovery, including errors raised during rollover or flush.
        if self.stream is not None:
            try:
                self.stream.close()
            except OSError:
                pass
            self.stream = None
        self._notice(
            f"File logging paused: ENOSPC; retry in {self.retry_interval:.0f}s; "
            f"skipped {self._dropped} records"
        )


def setup_logging(service_name: str = "quantmind"):
    """设置日志配置

    Args:
        service_name: 服务名称，用于日志文件命名
    """
    # 强制统一东八区，避免宿主机 UTC 导致日志少 8 小时
    try:
        import os as _os
        import time as _time

        _os.environ["TZ"] = "Asia/Shanghai"
        if hasattr(_time, "tzset"):
            _time.tzset()
    except Exception:
        pass

    # 创建根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.logging.log_level.upper()))

    # 清除现有处理器
    root_logger.handlers.clear()

    # 创建格式器
    formatter = logging.Formatter(
        fmt=settings.logging.log_format, datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)

    # 文件处理器（如果配置了日志文件）
    if settings.logging.log_file:
        try:
            log_file = Path(settings.logging.log_file)
            log_file.parent.mkdir(parents=True, exist_ok=True)

            file_handler = ResilientRotatingFileHandler(
                filename=log_file,
                maxBytes=settings.logging.max_log_size,
                backupCount=settings.logging.backup_count,
                encoding="utf-8",
                delay=True,
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.DEBUG)
            root_logger.addHandler(file_handler)
        except OSError as exc:
            sys.stderr.write(
                f"Failed to setup configured file logging: {type(exc).__name__}\n"
            )

    # 为特定服务创建日志文件
    try:
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)

        service_log_file = logs_dir / f"{service_name}.log"
        service_handler = ResilientRotatingFileHandler(
            filename=service_log_file,
            maxBytes=settings.logging.max_log_size,
            backupCount=settings.logging.backup_count,
            encoding="utf-8",
            delay=True,
        )
        service_handler.setFormatter(formatter)
        service_handler.setLevel(logging.DEBUG)
        root_logger.addHandler(service_handler)
    except Exception as e:
        sys.stderr.write(f"Failed to setup file logging: {e}\n")

    # 设置第三方库的日志级别
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("redis").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    logging.info(f"Logging configured for service: {service_name}")


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的日志器

    Args:
        name: 日志器名称

    Returns:
        配置好的日志器实例
    """
    return logging.getLogger(name)


class LoggerMixin:
    """日志器混入类，为类提供日志功能"""

    @property
    def logger(self) -> logging.Logger:
        """获取当前类的日志器"""
        return get_logger(self.__class__.__name__)
