"""
akshare_fetcher.py — 基于 akshare 的行情数据获取模块

完全替代 fetcher.py 中的新浪直连方式，使用 akshare 封装好的接口。
支持：A股指数、港股指数、全球指数、A股个股、汇率、黄金。

依赖:
    pip install akshare pandas

作者: Soyo Quant
"""

import logging
from typing import Optional

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)


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
# 美股指数通过新浪直连获取实时数据
# 其他全球指数通过 akshare index_global_hist_sina 获取历史数据
_SINA_GLOBAL_MAP = {
    "DJIA": "gb_$dji",       # 道琼斯
    "IXIC": "gb_ixic",       # 纳斯达克
    "SPX": "gb_%5Espx",      # 标普500
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
}


def _fetch_global_via_sina(code: str, sina_code: str) -> Optional[QuoteData]:
    """通过新浪直连获取全球指数实时行情。

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
            headers={
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
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


def fetch_global_indices(codes: list[str]) -> dict[str, QuoteData]:
    """获取全球主要指数行情数据。

    美股指数（DJIA、IXIC、SPX）通过新浪直连接口获取实时行情。
    其他全球指数（N225、FTSE、DAX、FCHI）通过 akshare 历史接口获取最新日线数据。

    Args:
        codes: 全球指数代码列表，支持 DJIA、IXIC、SPX、N225 等。

    Returns:
        以指数代码为键的字典，每个值包含 name、price、change、change_pct 等字段。
        获取失败时返回空字典。
    """
    result: dict[str, QuoteData] = {}

    for code in codes:
        # 美股指数走新浪直连（实时）
        if code in _SINA_GLOBAL_MAP:
            quote = _fetch_global_via_sina(code, _SINA_GLOBAL_MAP[code])
        # 其他全球指数走历史接口
        elif code in _GLOBAL_HIST_NAMES:
            quote = _fetch_global_via_hist(code, _GLOBAL_HIST_NAMES[code])
        else:
            logger.warning("未知的全球指数代码: %s", code)
            continue

        if quote:
            result[code] = quote

    return result


# ──────────────────────────────────────────────
# 美元兑人民币汇率
# ──────────────────────────────────────────────

def _parse_usd_cny_values(values: list[str]) -> Optional[QuoteData]:
    """解析美元兑人民币汇率数据（与 fetcher.py 一致）。"""
    try:
        current = float(values[7])
        open_price = float(values[1]) if values[1] else current
        change = current - open_price
        change_pct = (change / open_price * 100) if open_price else 0.0
        return _build_quote("USDCNY", "美元兑人民币(USD/CNY)", current, change, change_pct)
    except (ValueError, IndexError) as e:
        logger.warning("解析美元兑人民币汇率失败: %s", e)
        return None


def fetch_usd_cny_rate() -> Optional[QuoteData]:
    """通过新浪财经接口获取美元兑人民币汇率（与 fetcher.py 一致）。

    Returns:
        包含 name、price、change、change_pct 的 QuoteData，获取失败返回 None。
    """
    import requests as _requests

    try:
        resp = _requests.get(
            "https://hq.sinajs.cn/list=fx_susdcny",
            headers={
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
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


def fetch_usd_cny_rate_sync() -> Optional[QuoteData]:
    """同步版本：获取美元兑人民币汇率。"""
    return fetch_usd_cny_rate()


# ──────────────────────────────────────────────
# 黄金价格
# ──────────────────────────────────────────────

def fetch_gold_price() -> Optional[QuoteData]:
    """通过 akshare (上海黄金交易所) 获取国内黄金（Au99.99）价格。

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


def fetch_gold_price_sync() -> Optional[QuoteData]:
    """同步版本：获取国内黄金价格。"""
    return fetch_gold_price()


# ──────────────────────────────────────────────
# 个股行情
# ──────────────────────────────────────────────

def fetch_stock_quote(code: str) -> Optional[QuoteData]:
    """通过新浪财经接口获取A股个股实时行情。

    使用新浪直连方式（与 fetcher.py 相同），避免 stock_zh_a_spot() 下载全市场数据。

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
            headers={
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
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
        all_data.extend(fetch_global_indices(global_codes).values())

    gold_cfg = config.get("gold", {})
    if gold_cfg.get("enabled"):
        gold = fetch_gold_price_sync()
        if gold:
            all_data.append(gold)

    return all_data


# ──────────────────────────────────────────────
# 打印辅助函数
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


# ──────────────────────────────────────────────
# 自动测试
# ──────────────────────────────────────────────

def run_auto_tests():
    """运行自动测试，验证所有功能正常。"""
    print("=" * 60)
    print("🚀 akshare 自动测试所有功能")
    print("=" * 60)

    # 测试A股指数
    em_data = fetch_em_indices(["000001", "399001", "399006"])
    _print_quotes("A股指数", em_data)

    # 测试港股指数
    hk_data = fetch_hk_indices(["HSI", "HSTECH", "HSCEI"])
    _print_quotes("港股指数", hk_data)

    # 测试全球指数
    global_data = fetch_global_indices(["DJIA", "IXIC", "SPX", "N225"])
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


# ──────────────────────────────────────────────
# 交互模式
# ──────────────────────────────────────────────

def run_interactive_mode():
    """交互模式：用户输入股票代码查询。"""
    print("=" * 60)
    print("🔍 个股行情查询工具 (akshare)")
    print("输入股票代码查询，输入 q 退出")
    print("示例: 600519 (贵州茅台), 000858 (五粮液), 300750 (宁德时代)")
    print("=" * 60)

    while True:
        try:
            code = input("\n请输入股票代码: ").strip()
            if code.lower() in ("q", "quit", "exit"):
                print("👋 再见！")
                break

            if not code.isdigit() or len(code) != 6:
                print("⚠️  请输入6位数字股票代码")
                continue

            q = fetch_stock_quote(code)
            if q is None:
                print(f"❌ 查询 {code} 失败，请检查代码是否正确")
            else:
                print(f"\n  {'='*45}")
                print(f"  📊 {q['name']} ({q['code']})")
                print(f"  {'='*45}")
                print(f"    当前价格: {q['price']:.2f}")
                print(f"    涨跌额:   {q['change']:+.2f}")
                print(f"    涨跌幅:   {q['change_pct']:+.2f}%")
                print(f"  {'='*45}")

        except KeyboardInterrupt:
            print("\n👋 再见！")
            break
        except Exception as e:
            print(f"❌ 发生错误: {e}")


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] in ("interactive", "i", "-i"):
        run_interactive_mode()
    else:
        run_auto_tests()
