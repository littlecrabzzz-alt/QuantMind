"""
向量化回测引擎
提供高性能的向量化回测功能
旧版（2026-10-13 起）：已由 backend/shared/ashare_lab_bridge 替代，保留仅供对照
"""

from .engine import VectorizedBacktestEngine

__all__ = ["VectorizedBacktestEngine"]
