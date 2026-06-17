import logging
import asyncio
import aiohttp
import requests
from typing import TypedDict, Optional

logger = logging.getLogger(__name__)

_SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


class QuoteData(TypedDict):
    """行情数据统一结构"""
    code: str
    name: str
    price: float
    change: float
    change_pct: float


# ──────────────────────────────────────────────
# 内部辅助函数
# ──────────────────────────────────────────────

def _parse_sina_line(line: str) -> tuple[Optional[str], Optional[list[str]]]:
    """解析新浪返回的单行 JS 变量数据。

    Args:
        line: 形如 'var hq_str_s_sh000001="上证指数,3201.95,...";' 的字符串

    Returns:
        (var_name, values_list) 或 (None, None)
    """
    if "=" not in line:
        return None, None
    var_part, val_part = line.split("=", 1)
    var_name = var_part.replace("var hq_str_", "").strip()
    values = val_part.strip('";').split(",")
    return var_name, values


def _calc_change(current: float, open_price: float) -> tuple[float, float]:
    """计算涨跌额和涨跌幅。"""
    change = current - open_price
    change_pct = (change / open_price * 100) if open_price else 0.0
    return change, change_pct


def _build_quote(code: str, name: str, price: float, change: float, change_pct: float) -> QuoteData:
    """构建统一的行情数据结构。"""
    return {
        "code": code,
        "name": name,
        "price": price,
        "change": change,
        "change_pct": change_pct,
    }


# ──────────────────────────────────────────────
# A股指数
# ──────────────────────────────────────────────

def fetch_em_indices(codes: list[str]) -> dict[str, QuoteData]:
    """通过新浪财经接口获取A股指数行情数据。

    Args:
        codes: A股指数代码列表，如 ["000001", "399001"]。

    Returns:
        以指数代码为键的字典，每个值包含 name、price、change、change_pct 等字段。
        获取失败时返回空字典。
    """
    sina_codes = []
    code_map: dict[str, str] = {}
    for code in codes:
        if code.startswith("000"):
            sina_code = f"s_sh{code}"
        elif code.startswith("399"):
            sina_code = f"s_sz{code}"
        else:
            sina_code = f"s_sh{code}"
        sina_codes.append(sina_code)
        code_map[sina_code] = code

    try:
        resp = requests.get(
            f"https://hq.sinajs.cn/list={','.join(sina_codes)}",
            headers=_SINA_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.warning("获取A股指数失败: %s", e)
        return {}

    result: dict[str, QuoteData] = {}
    for line in resp.text.strip().split("\n"):
        var_name, values = _parse_sina_line(line)
        if var_name is None or values is None or len(values) < 4:
            continue
        raw_code = code_map.get(var_name, var_name)
        try:
            result[raw_code] = _build_quote(
                code=raw_code,
                name=values[0],
                price=float(values[1]),
                change=float(values[2]),
                change_pct=float(values[3]),
            )
        except (ValueError, IndexError) as e:
            logger.warning("解析A股指数 %s 数据失败: %s", raw_code, e)
    return result


# ──────────────────────────────────────────────
# 全球指数
# ──────────────────────────────────────────────

# 新浪全球指数字段索引（通用格式）
# [0]=名称, [1]=最新价, [2]=涨跌幅%, [3]=时间, [4]=涨跌额, [5]=开盘价, ...
_GLOBAL_IDX_NAME = 0
_GLOBAL_IDX_PRICE = 1
_GLOBAL_IDX_CHANGE_PCT = 2  # 注意：这是百分比字符串如 "0.92"
_GLOBAL_IDX_CHANGE = 4      # 涨跌额


def _parse_global_quote(values: list[str], code: str) -> Optional[QuoteData]:
    """解析新浪全球指数的一行数据。"""
    try:
        name = values[_GLOBAL_IDX_NAME]
        price = float(values[_GLOBAL_IDX_PRICE])
        change = float(values[_GLOBAL_IDX_CHANGE])
        change_pct = float(values[_GLOBAL_IDX_CHANGE_PCT])
        return _build_quote(code, name, price, change, change_pct)
    except (ValueError, IndexError) as e:
        logger.warning("解析全球指数 %s 数据失败: %s", code, e)
        return None


async def fetch_global_indices(sina_map: dict[str, str], codes: list[str]) -> dict[str, QuoteData]:
    """通过新浪财经接口异步获取全球主要指数行情数据。

    Args:
        sina_map: 代码映射字典，如 {"DJIA": "gb_$dji", "IXIC": "gb_ixic"}。
        codes: 全球指数代码列表，支持 DJIA、IXIC 等。

    Returns:
        以指数代码为键的字典，每个值包含 name、price、change、change_pct 等字段。
        获取失败时返回空字典。
    """
    sina_codes = []
    code_lookup: dict[str, str] = {}
    for code in codes:
        sina = sina_map.get(code, code)
        sina_codes.append(sina)
        code_lookup[sina] = code

    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://hq.sinajs.cn/list={','.join(sina_codes)}"
            async with session.get(url, headers=_SINA_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                text = await resp.text(encoding='gbk')
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.warning("获取全球指数失败: %s", e)
        return {}

    result: dict[str, QuoteData] = {}
    for line in text.strip().split("\n"):
        var_name, values = _parse_sina_line(line)
        if var_name is None or values is None or len(values) < 5:
            continue
        raw_code = code_lookup.get(var_name, var_name)
        quote = _parse_global_quote(values, raw_code)
        if quote:
            result[raw_code] = quote
    return result


# ──────────────────────────────────────────────
# 美元兑人民币汇率
# ──────────────────────────────────────────────

def _parse_usd_cny_values(values: list[str]) -> Optional[QuoteData]:
    """解析美元兑人民币汇率数据。"""
    try:
        current = float(values[7])
        open_price = float(values[1]) if values[1] else current
        change, change_pct = _calc_change(current, open_price)
        return _build_quote("USDCNY", "美元兑人民币(USD/CNY)", current, change, change_pct)
    except (ValueError, IndexError) as e:
        logger.warning("解析美元兑人民币汇率失败: %s", e)
        return None


async def fetch_usd_cny_rate() -> Optional[QuoteData]:
    """通过新浪财经接口异步获取美元兑人民币汇率。"""
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://hq.sinajs.cn/list=fx_susdcny"
            async with session.get(url, headers=_SINA_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                text = await resp.text(encoding='gbk')
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.warning("获取美元兑人民币汇率失败: %s", e)
        return None

    _, values = _parse_sina_line(text.strip())
    if values is None:
        return None
    return _parse_usd_cny_values(values)


def fetch_usd_cny_rate_sync() -> Optional[QuoteData]:
    """通过新浪财经接口获取美元兑人民币汇率（同步版本）。"""
    try:
        resp = requests.get(
            "https://hq.sinajs.cn/list=fx_susdcny",
            headers=_SINA_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.warning("获取美元兑人民币汇率失败: %s", e)
        return None

    _, values = _parse_sina_line(resp.text.strip())
    if values is None:
        return None
    return _parse_usd_cny_values(values)


# ──────────────────────────────────────────────
# 黄金价格（国内 Au99.99 / 伦敦金 XAU/USD）
# ──────────────────────────────────────────────

def _parse_gold_values(values: list[str], code: str, name: str) -> Optional[QuoteData]:
    """解析黄金价格数据（国内黄金或伦敦金共用）。"""
    try:
        if not values[0].strip():
            logger.warning("%s 数据为空，可能处于非交易时段", name)
            return None
        current = float(values[0])
        open_price = float(values[7].strip()) if values[7].strip() else current
        change, change_pct = _calc_change(current, open_price)
        return _build_quote(code, name, current, change, change_pct)
    except (ValueError, IndexError) as e:
        logger.warning("解析 %s 价格失败: %s", name, e)
        return None


async def _fetch_gold_async(url: str, code: str, name: str) -> Optional[QuoteData]:
    """异步获取黄金价格的通用实现。"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=_SINA_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                text = await resp.text(encoding='gbk')
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.warning("获取 %s 价格失败: %s", name, e)
        return None

    _, values = _parse_sina_line(text.strip())
    if values is None:
        return None
    return _parse_gold_values(values, code, name)


def _fetch_gold_sync(url: str, code: str, name: str) -> Optional[QuoteData]:
    """同步获取黄金价格的通用实现。"""
    try:
        resp = requests.get(url, headers=_SINA_HEADERS, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("获取 %s 价格失败: %s", name, e)
        return None

    _, values = _parse_sina_line(resp.text.strip())
    if values is None:
        return None
    return _parse_gold_values(values, code, name)


async def fetch_gold_price() -> Optional[QuoteData]:
    """通过新浪财经接口异步获取国内黄金（Au99.99）实时价格。"""
    return await _fetch_gold_async(
        "https://hq.sinajs.cn/list=hf_AU",
        "AU9999",
        "国内黄金(Au99.99)",
    )


def fetch_gold_price_sync() -> Optional[QuoteData]:
    """通过新浪财经接口获取国内黄金（Au99.99）实时价格（同步版本）。"""
    return _fetch_gold_sync(
        "https://hq.sinajs.cn/list=hf_AU",
        "AU9999",
        "国内黄金(Au99.99)",
    )


async def fetch_london_gold_price() -> Optional[QuoteData]:
    """通过新浪财经接口异步获取伦敦金（XAU/USD）实时价格。"""
    return await _fetch_gold_async(
        "https://hq.sinajs.cn/list=hf_XAU",
        "XAU",
        "伦敦金(XAU/USD)",
    )


def fetch_london_gold_price_sync() -> Optional[QuoteData]:
    """通过新浪财经接口获取伦敦金（XAU/USD）实时价格（同步版本）。"""
    return _fetch_gold_sync(
        "https://hq.sinajs.cn/list=hf_XAU",
        "XAU",
        "伦敦金(XAU/USD)",
    )


# ──────────────────────────────────────────────
# 个股行情
# ──────────────────────────────────────────────

# 新浪个股字段索引
# [0]=名称, [1]=当前价, [2]=涨跌额, [3]=涨跌幅%, [4]=成交量, [5]=成交额
_STOCK_IDX_NAME = 0
_STOCK_IDX_PRICE = 1
_STOCK_IDX_CHANGE = 2
_STOCK_IDX_CHANGE_PCT = 3


def fetch_stock_quote(code: str) -> Optional[QuoteData]:
    """通过新浪财经接口获取个股实时行情。

    Args:
        code: 6位股票代码，如 "600519"（贵州茅台）、"000858"（五粮液）。

    Returns:
        包含 name、price、change、change_pct 的字典，获取失败返回 None。
    """
    # 上海代码以 5/6/9 开头，深圳代码以 0/2/3 开头
    if code.startswith(("5", "6", "9")):
        sina_code = f"s_sh{code}"
    else:
        sina_code = f"s_sz{code}"

    try:
        resp = requests.get(
            f"https://hq.sinajs.cn/list={sina_code}",
            headers=_SINA_HEADERS,
            timeout=10,
        )
        resp.encoding = 'gbk'
    except Exception as e:
        logger.warning("获取个股 %s 失败: %s", code, e)
        return None

    _, values = _parse_sina_line(resp.text.strip())
    if values is None or len(values) < 4:
        logger.warning("个股 %s 数据为空或字段不足", code)
        return None

    try:
        return _build_quote(
            code=code,
            name=values[_STOCK_IDX_NAME],
            price=float(values[_STOCK_IDX_PRICE]),
            change=float(values[_STOCK_IDX_CHANGE]),
            change_pct=float(values[_STOCK_IDX_CHANGE_PCT]),
        )
    except (ValueError, IndexError) as e:
        logger.warning("解析个股 %s 数据失败: %s", code, e)
        return None


# ──────────────────────────────────────────────
# 聚合函数
# ──────────────────────────────────────────────

def fetch_all_indices(config: dict) -> list[QuoteData]:
    """根据配置聚合获取所有指数（A股、全球）及黄金行情数据。

    Args:
        config: 配置字典，包含 indices（指数列表，按 source 分类）、
                global_sina_map（全球指数代码映射）和 gold 配置。

    Returns:
        所有行情数据的列表，每个元素为包含 code、name、price、change、change_pct 的字典。
    """
    all_data: list[QuoteData] = []
    em_codes: list[str] = []
    global_codes: list[str] = []

    for item in config.get("indices", []):
        if item["source"] == "akshare_em":
            em_codes.append(item["code"])
        elif item["source"] == "akshare_global":
            global_codes.append(item["code"])

    if em_codes:
        all_data.extend(fetch_em_indices(em_codes).values())

    if global_codes:
        sina_map = config.get("global_sina_map", {})
        # 同步调用异步函数
        global_data = asyncio.run(fetch_global_indices(sina_map, global_codes))
        all_data.extend(global_data.values())

    gold_cfg = config.get("gold", {})
    if gold_cfg.get("enabled"):
        gold_type = gold_cfg.get("type", "domestic")
        if gold_type == "london":
            gold = fetch_london_gold_price_sync()
        else:
            gold = fetch_gold_price_sync()
        if gold:
            all_data.append(gold)

    return all_data


# ──────────────────────────────────────────────
# 异步聚合函数（推荐使用）
# ──────────────────────────────────────────────

async def fetch_all_indices_async(config: dict) -> list[QuoteData]:
    """异步版本：根据配置聚合获取所有指数（A股、全球）及黄金行情数据。

    Args:
        config: 配置字典，包含 indices（指数列表，按 source 分类）、
                global_sina_map（全球指数代码映射）和 gold 配置。

    Returns:
        所有行情数据的列表，每个元素为包含 code、name、price、change、change_pct 的字典。
    """
    all_data: list[QuoteData] = []
    em_codes: list[str] = []
    global_codes: list[str] = []

    for item in config.get("indices", []):
        if item["source"] == "akshare_em":
            em_codes.append(item["code"])
        elif item["source"] == "akshare_global":
            global_codes.append(item["code"])

    tasks = []
    if em_codes:
        # A股指数是同步函数，在线程池中运行
        loop = asyncio.get_event_loop()
        tasks.append(loop.run_in_executor(None, fetch_em_indices, em_codes))

    if global_codes:
        sina_map = config.get("global_sina_map", {})
        tasks.append(fetch_global_indices(sina_map, global_codes))

    if tasks:
        results = await asyncio.gather(*tasks)
        for r in results:
            if isinstance(r, dict):
                all_data.extend(r.values())

    gold_cfg = config.get("gold", {})
    if gold_cfg.get("enabled"):
        gold_type = gold_cfg.get("type", "domestic")
        if gold_type == "london":
            gold = await fetch_london_gold_price()
        else:
            gold = await fetch_gold_price()
        if gold:
            all_data.append(gold)

    return all_data


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
    print("🚀 自动测试所有功能")
    print("=" * 60)

    # 测试A股指数
    em_data = fetch_em_indices(["000001", "399001"])
    _print_quotes("A股指数", em_data)

    # 测试全球指数
    # 新浪代码: gb_$dji=道琼斯, gb_ixic=纳斯达克, gb_%5Espx=标普500(^SPX)
    # 注意: 标普500在非交易时段可能返回空数据
    sina_map = {
        "DJIA": "gb_$dji",
        "IXIC": "gb_ixic",
        "SPX": "gb_%5Espx",
    }
    global_data = asyncio.run(fetch_global_indices(sina_map, ["DJIA", "IXIC", "SPX"]))
    _print_quotes("全球指数", global_data)

    # 测试汇率
    usd = fetch_usd_cny_rate_sync()
    _print_quote("美元汇率", usd)

    # 测试黄金
    gold = fetch_gold_price_sync()
    _print_quote("国内黄金", gold)
    london = fetch_london_gold_price_sync()
    _print_quote("伦敦金", london)

    # 测试个股
    print("\n📈 个股测试:")
    for test_code in ["600519", "000858", "300750"]:
        q = fetch_stock_quote(test_code)
        _print_quote(test_code, q)

    print("\n" + "=" * 60)
    print("✅ 自动测试完成")
    print("=" * 60)


def run_interactive_mode():
    """交互模式：用户输入股票代码查询。"""
    print("=" * 60)
    print("🔍 个股行情查询工具")
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


if __name__ == "__main__":
    import sys

    # 如果命令行参数包含 "interactive" 或 "i"，进入交互模式
    if len(sys.argv) > 1 and sys.argv[1] in ("interactive", "i", "-i"):
        run_interactive_mode()
    else:
        run_auto_tests()
