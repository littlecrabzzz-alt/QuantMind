"""Pure stock-listing bounds shared by Tushare history planners."""

from datetime import datetime
import re

CODE = re.compile(r"T?[0-9]{6}\.(SH|SZ|BJ)")


def valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def stock_list_dates(identifiers):
    """Return earliest observed official list_date; missing metadata stays unbounded."""
    values = (identifiers or {}).get("stock_lifecycles", ())
    if not isinstance(values, (list, tuple)):
        raise ValueError("stock_lifecycles must be a list of records")
    result = {}
    for item in values:
        if not isinstance(item, dict):
            raise ValueError("stock_lifecycles must contain records")
        code, list_date = item.get("ts_code"), item.get("list_date")
        if not isinstance(code, str) or not CODE.fullmatch(code):
            raise ValueError("Invalid stock lifecycle code")
        if list_date is None:
            continue
        if not valid_date(list_date):
            raise ValueError("Invalid stock lifecycle list_date")
        result[code] = min(list_date, result.get(code, list_date))
    return result


def clip_params(params, code, list_dates):
    """Clip a legal day/range request to listing; None means wholly pre-listing."""
    list_date = list_dates.get(code)
    if list_date is None:
        return params
    if "trade_date" in params:
        return params if params["trade_date"] >= list_date else None
    start, end = params.get("start_date"), params.get("end_date")
    if start is None or end is None:
        return params
    if end < list_date:
        return None
    return {**params, "start_date": max(start, list_date)}
