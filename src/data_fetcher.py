"""
data_fetcher.py — 行情数据获取模块

基于 akshare 封装的数据获取接口，提供统一的行情数据结构。
支持：A股指数、港股指数、全球指数、汇率、黄金、个股。

以 akshare_fetcher.py 的实现为准，保持与 tradingbot.py 兼容的异步接口。

依赖:
    pip install akshare pandas requests aiohttp
"""

import logging
import asyncio
import json
import os
from typing import Optional

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 指数关注列表（持久化存储）
# ──────────────────────────────────────────────

# 关注列表文件路径（与 data_fetcher.py 同目录）
_WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "watchlist.json")

# 默认关注列表（首次使用时自动创建）
_DEFAULT_WATCHLIST = [
    # A股指数
    {"code": "000001", "source": "akshare_em", "name": "上证指数"},
    {"code": "399001", "source": "akshare_em", "name": "深证成指"},
    {"code": "399006", "source": "akshare_em", "name": "创业板指"},
    # 港股指数
    {"code": "HSI", "source": "akshare_hk", "name": "恒生指数"},
    {"code": "HSTECH", "source": "akshare_hk", "name": "恒生科技指数"},
    {"code": "HSCEI", "source": "akshare_hk", "name": "恒生中国企业指数"},
    # 全球指数
    {"code": "DJIA", "source": "akshare_global", "name": "道琼斯"},
    {"code": "IXIC", "source": "akshare_global", "name": "纳斯达克"},
    {"code": "SPX", "source": "akshare_global", "name": "标普500"},
    {"code": "N225", "source": "akshare_global", "name": "日经225指数"},
]


def _load_watchlist() -> list[dict]:
    """从 JSON 文件加载关注列表。"""
    if not os.path.exists(_WATCHLIST_FILE):
        # 首次使用，创建默认关注列表
        _save_watchlist(_DEFAULT_WATCHLIST)
        return list(_DEFAULT_WATCHLIST)
    try:
        with open(_WATCHLIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("读取关注列表失败: %s，使用默认列表", e)
        return list(_DEFAULT_WATCHLIST)


def _save_watchlist(watchlist: list[dict]):
    """保存关注列表到 JSON 文件。"""
    try:
        with open(_WATCHLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(watchlist, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("保存关注列表失败: %s", e)


def get_watchlist() -> list[dict]:
    """获取当前关注列表。"""
    return _load_watchlist()


def add_to_watchlist(code: str) -> tuple[bool, str]:
    """将指数代码添加到关注列表。

    Args:
        code: 指数代码，如 "000001"、"HSI"、"DJIA" 等。

    Returns:
        (成功标志, 消息)
    """
    watchlist = _load_watchlist()

    # 检查是否已存在
    for item in watchlist:
        if item["code"] == code:
            return False, f"指数 {code} 已在关注列表中"

    # 判断指数来源
    if code.startswith(("0", "1", "2", "3", "5", "6", "9")):
        source = "akshare_em"
    elif code in ("HSI", "HSTECH", "HSCEI", "HSCCI", "VHSI"):
        source = "akshare_hk"
    else:
        source = "akshare_global"


    watchlist.append({"code": code, "source": source, "name": code})
    _save_watchlist(watchlist)
    return True, f"添加成功：{code}"


def remove_from_watchlist(code: str) -> tuple[bool, str]:
    """将指数代码从关注列表中移除。

    Args:
        code: 指数代码，如 "000001"、"HSI"、"DJIA" 等。

    Returns:
        (成功标志, 消息)
    """
    watchlist = _load_watchlist()
    for i, item in enumerate(watchlist):
        if item["code"] == code:
            watchlist.pop(i)
            _save_watchlist(watchlist)
            return True, f"移除成功：{code}"
    return False, f"指数 {code} 不在关注列表中"



# ──────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────

class QuoteData(dict):
    """行情数据统一结构，兼容 dict 接口。"""
    def __init__(self, code: str, name: str, price: float, change: float, change_pct: float):
        super().__init__(
            code=code,
            name=name,
            price=price,
            change=change,
            change_pct=change_pct,
        )
        self.code = code
        self.name = name
        self.price = price
        self.change = change
        self.change_pct = change_pct


def _build_quote(code: str, name: str, price: float, change: float, change_pct: float) -> QuoteData:
    """构建统一的行情数据结构。"""
    return QuoteData(code, name, price, change, change_pct)


# ──────────────────────────────────────────────
# A股指数
# ──────────────────────────────────────────────

# A股指数代码映射（新浪格式 → 统一代码）
_A_INDEX_MAP = {
    "sh000001": "000001",  # 上证指数
    "sh000002": "000002",  # A股指数
    "sh000003": "000003",  # B股指数
    "sh000016": "000016",  # 上证50
    "sh000300": "000300",  # 沪深300
    "sh000688": "000688",  # 科创50
    "sz399001": "399001",  # 深证成指
    "sz399005": "399005",  # 中小100
    "sz399006": "399006",  # 创业板指
    "sz399852": "399852",  # 中证1000
}


def fetch_em_indices(codes: list[str]) -> dict[str, QuoteData]:
    """通过 akshare (新浪源) 获取A股指数行情数据。

    Args:
        codes: A股指数代码列表，如 ["000001", "399001", "000300"]。

    Returns:
        以指数代码为键的字典，每个值包含 name、price、change、change_pct 等字段。
        获取失败时返回空字典。
    """
    try:
        df = ak.stock_zh_index_spot_sina()
    except Exception as e:
        logger.warning("获取A股指数失败: %s", e)
        return {}

    result: dict[str, QuoteData] = {}
    for _, row in df.iterrows():
        raw_code = str(row.get("代码", ""))
        # 统一代码格式：去掉 sh/sz 前缀
        code = _A_INDEX_MAP.get(raw_code, raw_code)
        # 如果不在映射表中，尝试去掉 sh/sz 前缀
        if code not in codes and raw_code.startswith(("sh", "sz")):
            code = raw_code[2:]
        if code not in codes:
            continue
        try:
            result[code] = _build_quote(
                code=code,
                name=str(row.get("名称", "")),
                price=float(row.get("最新价", 0)),
                change=float(row.get("涨跌额", 0)),
                change_pct=float(row.get("涨跌幅", 0)),
            )
        except (ValueError, TypeError) as e:
            logger.warning("解析A股指数 %s 数据失败: %s", code, e)
    return result


# ──────────────────────────────────────────────
# 港股指数
# ──────────────────────────────────────────────

# 港股指数代码映射（akshare 返回的代码 → 统一代码）
_HK_INDEX_MAP = {
    "HSI": "HSI",          # 恒生指数
    "HSTECH": "HSTECH",    # 恒生科技指数
    "HSCEI": "HSCEI",      # 恒生中国企业指数
    "HSCCI": "HSCCI",      # 恒生香港中资企业指数
    "VHSI": "VHSI",        # 恒指波幅指数
}


def fetch_hk_indices(codes: list[str]) -> dict[str, QuoteData]:
    """通过 akshare (新浪源) 获取港股指数行情数据。

    Args:
        codes: 港股指数代码列表，如 ["HSI", "HSTECH", "HSCEI"]。

    Returns:
        以指数代码为键的字典，每个值包含 name、price、change、change_pct 等字段。
        获取失败时返回空字典。
    """
    try:
        df = ak.stock_hk_index_spot_sina()
    except Exception as e:
        logger.warning("获取港股指数失败: %s", e)
        return {}

    result: dict[str, QuoteData] = {}
    for _, row in df.iterrows():
        raw_code = str(row.get("代码", "")).strip()
        code = _HK_INDEX_MAP.get(raw_code, raw_code)
        if code not in codes:
            continue
        try:
            result[code] = _build_quote(
                code=code,
                name=str(row.get("名称", "")),
                price=float(row.get("最新价", 0)),
                change=float(row.get("涨跌额", 0)),
                change_pct=float(row.get("涨跌幅", 0)),
            )
        except (ValueError, TypeError) as e:
            logger.warning("解析港股指数 %s 数据失败: %s", code, e)
    return result


# ──────────────────────────────────────────────
# 全球指数
# ──────────────────────────────────────────────

# 新浪全球指数代码映射（统一代码 → 新浪接口代码）
_SINA_GLOBAL_MAP = {
    "DJIA": "gb_$dji",       # 道琼斯
    "IXIC": "gb_ixic",       # 纳斯达克
    "SPX": "gb_$inx",        # 标普500 (gb_$inx 是标普500指数，gb_%5Espx 返回空)
}


# 可通过新浪实时接口获取的港股指数（统一代码 → 新浪接口代码）
_SINA_HK_MAP = {
    "HSI": "rt_hkHSI",       # 恒生指数
}

# 可通过 index_global_hist_sina 获取的全球指数（使用中文名作为参数）
_GLOBAL_HIST_NAMES = {
    "N225": "日经225指数",
    "FTSE": "英国富时100指数",
    "DAX": "德国DAX 30种股价指数",
    "FCHI": "法CAC40指数",
}

# 全球指数显示名称
_GLOBAL_DISPLAY_NAMES = {
    "DJIA": "道琼斯",
    "IXIC": "纳斯达克",
    "SPX": "标普500",
    "N225": "日经225指数",
    "FTSE": "英国富时100指数",
    "DAX": "德国DAX 30种股价指数",
    "FCHI": "法CAC40指数",
    "HSI": "恒生指数",
}


# 新浪财经请求头
_SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def _fetch_global_via_sina(code: str, sina_code: str) -> Optional[QuoteData]:
    """通过新浪直连获取全球指数实时行情。

    支持两种数据格式：
    - 美股格式: name,price,change_pct,...,change,...
    - 港股格式: code,name,open,prev_close,high,low,price,change,change_pct,...

    Args:
        code: 统一代码，如 "DJIA"
        sina_code: 新浪接口代码，如 "gb_$dji"

    Returns:
        QuoteData 或 None
    """
    import requests as _requests

    try:
        resp = _requests.get(
            f"https://hq.sinajs.cn/list={sina_code}",
            headers=_SINA_HEADERS,
            timeout=10,
        )
        resp.encoding = "gbk"
    except Exception as e:
        logger.warning("获取全球指数 %s 失败: %s", code, e)
        return None

    text = resp.text.strip()
    if "=" not in text:
        return None

    values = text.split("=", 1)[1].strip('";').split(",")
    if len(values) < 5:
        return None

    try:
        # 判断数据格式：港股格式第一个字段是代码（如 "HSI"），第二个字段是名称
        if sina_code.startswith("rt_"):
            # 港股格式: code,name,open,prev_close,high,low,price,change,change_pct
            name = values[1]
            price = float(values[6])
            change = float(values[7])
            change_pct = float(values[8])
        else:
            # 美股格式: name,price,change_pct,...,change,...
            name = values[0]
            price = float(values[1])
            change = float(values[4])      # 涨跌额
            change_pct = float(values[2])  # 涨跌幅%
        return _build_quote(code, name, price, change, change_pct)
    except (ValueError, IndexError) as e:
        logger.warning("解析全球指数 %s 数据失败: %s", code, e)
        return None



def _fetch_global_via_hist(code: str, name_cn: str) -> Optional[QuoteData]:
    """通过 akshare 历史接口获取全球指数行情（最新一条）。

    Args:
        code: 统一代码，如 "N225"
        name_cn: 中文名，如 "日经225指数"

    Returns:
        QuoteData 或 None
    """
    try:
        df = ak.index_global_hist_sina(symbol=name_cn)
        if df.empty:
            logger.warning("全球指数 %s (%s) 数据为空", code, name_cn)
            return None

        latest = df.iloc[-1]
        close = float(latest.get("close", 0))
        if len(df) >= 2:
            prev_close = float(df.iloc[-2].get("close", 0))
            change = close - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0.0
        else:
            change = 0.0
            change_pct = 0.0

        return _build_quote(
            code=code,
            name=name_cn,
            price=close,
            change=round(change, 2),
            change_pct=round(change_pct, 2),
        )
    except Exception as e:
        logger.warning("获取全球指数 %s (%s) 失败: %s", code, name_cn, e)
        return None


def fetch_global_indices_sync(codes: list[str]) -> dict[str, QuoteData]:
    """获取全球主要指数行情数据（同步版本）。

    美股指数（DJIA、IXIC、SPX）通过新浪直连接口获取实时行情。
    港股指数（HSI）通过新浪直连接口获取实时行情。
    其他全球指数（N225、FTSE、DAX、FCHI）通过 akshare 历史接口获取最新日线数据。

    Args:
        codes: 全球指数代码列表，支持 DJIA、IXIC、SPX、N225、HSI 等。

    Returns:
        以指数代码为键的字典，每个值包含 name、price、change、change_pct 等字段。
        获取失败时返回空字典。
    """
    result: dict[str, QuoteData] = {}

    for code in codes:
        # 美股指数走新浪直连（实时）
        if code in _SINA_GLOBAL_MAP:
            quote = _fetch_global_via_sina(code, _SINA_GLOBAL_MAP[code])
        # 港股指数走新浪直连（实时）
        elif code in _SINA_HK_MAP:
            quote = _fetch_global_via_sina(code, _SINA_HK_MAP[code])
        # 其他全球指数走历史接口
        elif code in _GLOBAL_HIST_NAMES:
            quote = _fetch_global_via_hist(code, _GLOBAL_HIST_NAMES[code])
        else:
            logger.warning("未知的全球指数代码: %s", code)
            continue

        if quote:
            result[code] = quote

    return result



# 从 tradingbot.py 的 sina_map 到标准代码的反向映射
# tradingbot.py 中 sina_map 的格式: {"SPX": "int_sp500", "标普500": "int_sp500", "HSI": "rt_hkHSI", ...}
# 这里建立 sina_map 值（如 "int_sp500"）到标准代码（如 "SPX"）的映射
_SINA_CODE_TO_STANDARD = {
    "int_sp500": "SPX",
    "int_dji": "DJIA",
    "int_nikkei": "N225",
    "rt_hkHSI": "HSI",
}


async def fetch_global_indices(sina_map: dict, codes: list[str]) -> dict[str, QuoteData]:
    """获取全球主要指数行情数据（异步接口，兼容 tradingbot.py）。

    使用同步的 fetch_global_indices_sync 实现，通过 asyncio.to_thread 异步执行。
    sina_map 参数用于将中文别名（如"标普500"）解析为标准代码（如"SPX"）。

    Args:
        sina_map: 代码映射表，如 {"SPX": "int_sp500", "标普500": "int_sp500", ...}
        codes: 全球指数代码列表，支持 SPX、DJIA、N225、HSI 等标准代码或中文别名。

    Returns:
        以指数代码为键的字典，每个值包含 name、price、change、change_pct 等字段。
    """
    # 所有支持的标准代码集合
    _ALL_STANDARD_CODES = set(_SINA_GLOBAL_MAP) | set(_SINA_HK_MAP) | set(_GLOBAL_HIST_NAMES)

    # 构建别名 → 标准代码的映射
    alias_to_std = {}
    for alias, sina_code in sina_map.items():
        # 如果别名本身就是标准代码（如 "SPX"），直接映射
        if alias in _ALL_STANDARD_CODES:
            alias_to_std[alias] = alias
        # 否则通过新浪代码找到标准代码
        elif sina_code in _SINA_CODE_TO_STANDARD:
            alias_to_std[alias] = _SINA_CODE_TO_STANDARD[sina_code]
        else:
            # 尝试在所有映射中反向查找
            for std_code, s_code in _SINA_GLOBAL_MAP.items():
                if s_code == sina_code:
                    alias_to_std[alias] = std_code
                    break
            else:
                for std_code, s_code in _SINA_HK_MAP.items():
                    if s_code == sina_code:
                        alias_to_std[alias] = std_code
                        break

    # 解析代码：中文别名 → 标准代码
    resolved_codes = []
    for code in codes:
        if code in _ALL_STANDARD_CODES:
            # 已经是标准代码
            resolved_codes.append(code)
        elif code in _GLOBAL_DISPLAY_NAMES:
            # 在显示名称映射中（如 "标普500"）
            # 反向查找标准代码
            for std_code, display_name in _GLOBAL_DISPLAY_NAMES.items():
                if code == display_name:
                    resolved_codes.append(std_code)
                    break
            else:
                resolved_codes.append(code)
        elif code in alias_to_std:
            resolved_codes.append(alias_to_std[code])
        else:
            logger.warning("未知的指数代码: %s", code)


    if not resolved_codes:
        return {}

    # 使用 asyncio.to_thread 将同步调用转为异步
    return await asyncio.to_thread(fetch_global_indices_sync, resolved_codes)


# ──────────────────────────────────────────────
# 美元兑人民币汇率
# ──────────────────────────────────────────────

def _parse_usd_cny_values(values: list[str]) -> Optional[QuoteData]:
    """解析美元兑人民币汇率数据。"""
    try:
        current = float(values[7])
        open_price = float(values[1]) if values[1] else current
        change = current - open_price
        change_pct = (change / open_price * 100) if open_price else 0.0
        return _build_quote("USDCNY", "美元兑人民币(USD/CNY)", current, change, change_pct)
    except (ValueError, IndexError) as e:
        logger.warning("解析美元兑人民币汇率失败: %s", e)
        return None


def fetch_usd_cny_rate_sync() -> Optional[QuoteData]:
    """通过新浪财经接口获取美元兑人民币汇率（同步版本）。

    Returns:
        包含 name、price、change、change_pct 的 QuoteData，获取失败返回 None。
    """
    import requests as _requests

    try:
        resp = _requests.get(
            "https://hq.sinajs.cn/list=fx_susdcny",
            headers=_SINA_HEADERS,
            timeout=10,
        )
        resp.encoding = "gbk"
    except Exception as e:
        logger.warning("获取美元兑人民币汇率失败: %s", e)
        return None

    text = resp.text.strip()
    if "=" not in text:
        return None

    values = text.split("=", 1)[1].strip('";').split(",")
    if len(values) < 8:
        return None

    return _parse_usd_cny_values(values)


async def fetch_usd_cny_rate() -> Optional[QuoteData]:
    """通过新浪财经接口获取美元兑人民币汇率（异步接口）。

    Returns:
        包含 name、price、change、change_pct 的 QuoteData，获取失败返回 None。
    """
    return await asyncio.to_thread(fetch_usd_cny_rate_sync)


# ──────────────────────────────────────────────
# 黄金价格
# ──────────────────────────────────────────────

def fetch_gold_price_sync() -> Optional[QuoteData]:
    """通过 akshare (上海黄金交易所) 获取国内黄金（Au99.99）价格（同步版本）。

    Returns:
        包含 name、price、change、change_pct 的 QuoteData，获取失败返回 None。
    """
    try:
        df = ak.spot_golden_benchmark_sge()
        if df.empty:
            logger.warning("国内黄金数据为空，可能处于非交易时段")
            return None

        # 取最新一条数据
        latest = df.iloc[-1]
        # 使用晚盘价（如果有）或早盘价
        price = float(latest.get("晚盘价", 0))
        if price == 0:
            price = float(latest.get("早盘价", 0))

        # 计算涨跌（与前一条比较）
        if len(df) >= 2:
            prev = float(df.iloc[-2].get("晚盘价", 0))
            if prev == 0:
                prev = float(df.iloc[-2].get("早盘价", 0))
            change = price - prev
            change_pct = (change / prev * 100) if prev else 0.0
        else:
            change = 0.0
            change_pct = 0.0

        return _build_quote(
            code="AU9999",
            name="国内黄金(Au99.99)",
            price=price,
            change=round(change, 2),
            change_pct=round(change_pct, 2),
        )
    except Exception as e:
        logger.warning("获取国内黄金价格失败: %s", e)
        return None


async def fetch_gold_price() -> Optional[QuoteData]:
    """通过 akshare 获取国内黄金价格（异步接口）。

    Returns:
        包含 name、price、change、change_pct 的 QuoteData，获取失败返回 None。
    """
    return await asyncio.to_thread(fetch_gold_price_sync)


def fetch_london_gold_price_sync() -> Optional[QuoteData]:
    """通过新浪财经接口获取伦敦金（XAU/USD）实时价格（同步版本）。

    Returns:
        包含 name、price、change、change_pct 的 QuoteData，获取失败返回 None。
    """
    import requests as _requests

    try:
        resp = _requests.get(
            "https://hq.sinajs.cn/list=hf_XAU",
            headers=_SINA_HEADERS,
            timeout=10,
        )
        resp.encoding = "gbk"
    except Exception as e:
        logger.warning("获取伦敦金价格失败: %s", e)
        return None

    text = resp.text.strip()
    if "=" not in text:
        return None

    values = text.split("=", 1)[1].strip('";').split(",")
    if not values[0].strip():
        logger.warning("伦敦金数据为空，可能处于非交易时段")
        return None

    try:
        current = float(values[0])
        open_price = float(values[7].strip()) if values[7].strip() else current
        change = current - open_price
        change_pct = (change / open_price * 100) if open_price else 0
        return _build_quote(
            code="XAU",
            name="伦敦金(XAU/USD)",
            price=current,
            change=change,
            change_pct=change_pct,
        )
    except (ValueError, IndexError) as e:
        logger.warning("解析伦敦金价格失败: %s", e)
        return None


async def fetch_london_gold_price() -> Optional[QuoteData]:
    """通过新浪财经接口获取伦敦金（XAU/USD）实时价格（异步接口）。

    Returns:
        包含 name、price、change、change_pct 的 QuoteData，获取失败返回 None。
    """
    return await asyncio.to_thread(fetch_london_gold_price_sync)


# ──────────────────────────────────────────────
# 个股行情
# ──────────────────────────────────────────────

def fetch_stock_quote(code: str) -> Optional[QuoteData]:
    """通过新浪财经接口获取A股个股实时行情。

    Args:
        code: 6位股票代码，如 "600519"（贵州茅台）、"000858"（五粮液）。

    Returns:
        包含 name、price、change、change_pct 的 QuoteData，获取失败返回 None。
    """
    import requests as _requests

    # 上海代码以 5/6/9 开头，深圳代码以 0/2/3 开头
    if code.startswith(("5", "6", "9")):
        sina_code = f"s_sh{code}"
    else:
        sina_code = f"s_sz{code}"

    try:
        resp = _requests.get(
            f"https://hq.sinajs.cn/list={sina_code}",
            headers=_SINA_HEADERS,
            timeout=10,
        )
        resp.encoding = "gbk"
    except Exception as e:
        logger.warning("获取个股 %s 失败: %s", code, e)
        return None

    # 解析新浪返回数据: "var hq_str_s_sh600519="贵州茅台,1500.00,...";"
    text = resp.text.strip()
    if "=" not in text:
        logger.warning("个股 %s 返回数据格式异常", code)
        return None

    values = text.split("=", 1)[1].strip('";').split(",")
    if len(values) < 4:
        logger.warning("个股 %s 数据字段不足", code)
        return None

    try:
        return _build_quote(
            code=code,
            name=str(values[0]),
            price=float(values[1]),
            change=float(values[2]),
            change_pct=float(values[3]),
        )
    except (ValueError, IndexError) as e:
        logger.warning("解析个股 %s 数据失败: %s", code, e)
        return None


# ──────────────────────────────────────────────
# 开放式基金（通过 akshare 东方财富接口获取净值）
# ──────────────────────────────────────────────

# 开放式基金数据缓存（避免重复请求）
_OPEN_FUND_DF: Optional[pd.DataFrame] = None


def _fetch_open_fund_df() -> Optional[pd.DataFrame]:
    """获取开放式基金全量数据（带缓存）。

    Returns:
        DataFrame，包含基金代码、简称、最新净值、日增长率等字段。
    """
    global _OPEN_FUND_DF
    try:
        df = ak.fund_open_fund_daily_em()
        if df.empty:
            return None
        _OPEN_FUND_DF = df
        return df
    except Exception as e:
        logger.warning("获取开放式基金数据失败: %s", e)
        return None


def fetch_open_fund_quote(code: str) -> Optional[QuoteData]:
    """通过 akshare 东方财富接口获取开放式基金最新净值。

    数据格式说明：
    - 列名动态包含日期，如 "2026-06-16-单位净值"、"2026-06-15-单位净值"
    - 最新日期列在最前面，依次类推
    - 当日净值未更新时，对应列为空字符串

    Args:
        code: 6位基金代码，如 "017730"、"161725"。

    Returns:
        包含 name、price、change、change_pct 的 QuoteData，获取失败返回 None。
    """
    df = _fetch_open_fund_df()
    if df is None:
        return None

    # 查找基金
    row = df[df["基金代码"] == code]
    if row.empty:
        return None

    row = row.iloc[0]
    name = str(row.get("基金简称", code))

    # 动态查找所有净值列：列名格式为 "YYYY-MM-DD-单位净值"
    nav_cols = sorted(
        [col for col in df.columns if col.endswith("-单位净值")],
        reverse=True,  # 最新日期在前
    )

    if not nav_cols:
        return None

    # 找到第一个有数据的净值列（当日净值可能未更新）
    price = None
    for col in nav_cols:
        val = str(row.get(col, "")).strip()
        if val:
            try:
                price = float(val)
                break
            except ValueError:
                continue

    if price is None:
        return None

    # 获取日增长率（如果当日净值未更新，日增长率为空）
    change_pct_str = str(row.get("日增长率", "")).strip()
    change_pct = 0.0
    if change_pct_str and change_pct_str not in ("", "nan"):
        try:
            change_pct = float(change_pct_str)
        except ValueError:
            pass

    # 计算涨跌额
    change = price * change_pct / 100 if change_pct != 0 else 0.0

    return _build_quote(
        code=code,
        name=name,
        price=price,
        change=round(change, 4),
        change_pct=round(change_pct, 2),
    )



# ──────────────────────────────────────────────
# 聚合函数
# ──────────────────────────────────────────────


def fetch_all_indices(config: dict) -> list[QuoteData]:
    """根据配置聚合获取所有指数（A股、港股、全球）及黄金行情数据。

    Args:
        config: 配置字典，包含：
            - indices: 指数列表，每项有 source 和 code
                source 支持: "akshare_em"(A股), "akshare_hk"(港股), "akshare_global"(全球)
            - gold: 黄金配置，enabled 为 True 时获取

    Returns:
        所有行情数据的列表。
    """
    all_data: list[QuoteData] = []
    em_codes: list[str] = []
    hk_codes: list[str] = []
    global_codes: list[str] = []

    for item in config.get("indices", []):
        source = item.get("source", "")
        code = item.get("code", "")
        if source == "akshare_em":
            em_codes.append(code)
        elif source == "akshare_hk":
            hk_codes.append(code)
        elif source == "akshare_global":
            global_codes.append(code)

    if em_codes:
        all_data.extend(fetch_em_indices(em_codes).values())

    if hk_codes:
        all_data.extend(fetch_hk_indices(hk_codes).values())

    if global_codes:
        all_data.extend(fetch_global_indices_sync(global_codes).values())

    gold_cfg = config.get("gold", {})
    if gold_cfg.get("enabled"):
        gold = fetch_gold_price_sync()
        if gold:
            all_data.append(gold)

    return all_data


# ──────────────────────────────────────────────
# 自动测试
# ──────────────────────────────────────────────

def _print_quote(title: str, data: Optional[QuoteData]):
    """格式化打印一条行情数据。"""
    if data is None:
        print(f"  {title}: ❌ 获取失败")
        return
    print(f"  {title}: {data['name']}  {data['price']:.2f}  "
          f"{data['change']:+.2f}  {data['change_pct']:+.2f}%")


def _print_quotes(title: str, data: dict[str, QuoteData]):
    """格式化打印多条行情数据。"""
    print(f"\n📊 {title}:")
    if not data:
        print("  (无数据)")
        return
    for code, q in data.items():
        print(f"  {code:6s} {q['name']:12s}  {q['price']:>10.2f}  "
              f"{q['change']:>+8.2f}  {q['change_pct']:>+6.2f}%")


def run_auto_tests():
    """运行自动测试，验证所有功能正常。"""
    print("=" * 60)
    print("🚀 data_fetcher 自动测试所有功能")
    print("=" * 60)

    # 测试A股指数
    em_data = fetch_em_indices(["000001", "399001", "399006"])
    _print_quotes("A股指数", em_data)

    # 测试港股指数
    hk_data = fetch_hk_indices(["HSI", "HSTECH", "HSCEI"])
    _print_quotes("港股指数", hk_data)

    # 测试全球指数
    global_data = fetch_global_indices_sync(["DJIA", "IXIC", "SPX", "N225"])
    _print_quotes("全球指数", global_data)

    # 测试汇率
    usd = fetch_usd_cny_rate_sync()
    _print_quote("美元汇率", usd)

    # 测试黄金
    gold = fetch_gold_price_sync()
    _print_quote("国内黄金", gold)

    # 测试个股
    print("\n📈 个股测试:")
    for test_code in ["600519", "000858", "300750"]:
        q = fetch_stock_quote(test_code)
        _print_quote(test_code, q)

    print("\n" + "=" * 60)
    print("✅ 自动测试完成")
    print("=" * 60)


if __name__ == "__main__":
    run_auto_tests()
