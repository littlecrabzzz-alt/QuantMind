"""内置策略。"""

from .lowvol_trend import LowVolTrend
from .industry_lowvol import IndustryLowVol
from .vol_target import VolTarget

__all__ = ["LowVolTrend", "IndustryLowVol", "VolTarget"]
