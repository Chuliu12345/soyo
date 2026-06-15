import logging
import asyncio
import aiohttp
import requests

logger = logging.getLogger(__name__)

_SINA_HEADERS = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}


def fetch_akshare_em_indices(codes: list[str]) -> dict[str, dict]:
    """通过新浪财经接口获取A股指数行情数据。

    Args:
        codes: A股指数代码列表，如 ["000001", "399001"]。

    Returns:
        以指数代码为键的字典，每个值包含 name、price、change、change_pct 等字段。
        获取失败时返回空字典。
    """
    sina_codes = []
    code_map = {}
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

    result = {}
    for line in resp.text.strip().split("\n"):
        if "=" not in line:
            continue
        var_part, val_part = line.split("=", 1)
        var_name = var_part.replace("var hq_str_", "").strip()
        raw_code = code_map.get(var_name, var_name)
        values = val_part.strip('";').split(",")
        if len(values) < 4:
            continue
        result[raw_code] = {
            "code": raw_code,
            "name": values[0],
            "price": float(values[1]),
            "change": float(values[2]),
            "change_pct": float(values[3]),
        }
    return result


async def fetch_global_indices(sina_map:dict, codes: list[str]) -> dict[str, dict]:
    """通过新浪财经接口异步获取全球主要指数行情数据。

    Args:
        codes: 全球指数代码列表，支持 SPX、DJIA、N225、HSI 等。

    Returns:
        以指数代码为键的字典，每个值包含 name、price、change、change_pct 等字段。
        获取失败时返回空字典。
    """
    sina_codes = []
    code_lookup = {}
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

    result = {}
    for line in text.strip().split("\n"):
        if "=" not in line:
            continue
        var_part, val_part = line.split("=", 1)
        var_name = var_part.split("_", 2)[-1]
        raw_code = code_lookup.get(var_name, var_name)
        values = val_part.strip('";').split(",")
        try:
            if raw_code == "HSI":
                price = float(values[6])
                change = float(values[7])
                change_pct = float(values[8])
                name = "恒生指数"
            else:
                name = values[0]
                price = float(values[1])
                change = float(values[2]) if len(values) > 2 else 0
                change_pct = float(values[3]) if len(values) > 3 else 0
            result[raw_code] = {
                "code": raw_code,
                "name": name,
                "price": price,
                "change": change,
                "change_pct": change_pct,
            }
        except (ValueError, IndexError) as e:
            logger.warning("解析 %s 数据失败: %s", raw_code, e)
    return result


async def fetch_usd_cny_rate() -> dict | None:
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

    try:
        line = text.strip()
        if "=" not in line:
            return None
        values = line.split("=", 1)[1].strip('";').split(",")
        current = float(values[7])
        open_price = float(values[1]) if values[1] else current
        change = current - open_price
        change_pct = (change / open_price * 100) if open_price else 0
        return {
            "code": "USDCNY",
            "name": "美元兑人民币(USD/CNY)",
            "price": current,
            "change": change,
            "change_pct": change_pct,
        }
    except (ValueError, IndexError) as e:
        logger.warning("解析美元兑人民币汇率失败: %s", e)
        return None


def fetch_usd_cny_rate_sync() -> dict | None:
    """通过新浪财经接口获取美元兑人民币汇率（同步版本）。"""
    try:
        resp = requests.get(
            "https://hq.sinajs.cn/list=fx_susdcny",
            headers=_SINA_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        line = resp.text.strip()
        if "=" not in line:
            return None
        values = line.split("=", 1)[1].strip('";').split(",")
        current = float(values[7])
        open_price = float(values[1]) if values[1] else current
        change = current - open_price
        change_pct = (change / open_price * 100) if open_price else 0
        return {
            "code": "USDCNY",
            "name": "美元兑人民币(USD/CNY)",
            "price": current,
            "change": change,
            "change_pct": change_pct,
        }
    except Exception as e:
        logger.warning("获取美元兑人民币汇率失败: %s", e)
        return None


async def fetch_gold_price() -> dict | None:
    """通过新浪财经接口异步获取国内黄金（Au99.99）实时价格。"""
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://hq.sinajs.cn/list=hf_AU"
            async with session.get(url, headers=_SINA_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                text = await resp.text(encoding='gbk')
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.warning("获取国内黄金价格失败: %s", e)
        return None

    try:
        line = text.strip()
        if "=" not in line:
            return None
        values = line.split("=", 1)[1].strip('";').split(",")
        if not values[0].strip():
            logger.warning("国内黄金数据为空，可能处于非交易时段")
            return None
        current = float(values[0])
        open_price = float(values[7].strip()) if values[7].strip() else current
        change = current - open_price
        change_pct = (change / open_price * 100) if open_price else 0
        return {
            "code": "AU9999",
            "name": "国内黄金(Au99.99)",
            "price": current,
            "change": change,
            "change_pct": change_pct,
        }
    except (ValueError, IndexError) as e:
        logger.warning("解析国内黄金价格失败: %s", e)
        return None


def fetch_gold_price_sync() -> dict | None:
    """通过新浪财经接口获取国内黄金（Au99.99）实时价格（同步版本）。"""
    try:
        resp = requests.get(
            "https://hq.sinajs.cn/list=hf_AU",
            headers=_SINA_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        line = resp.text.strip()
        if "=" not in line:
            return None
        values = line.split("=", 1)[1].strip('";').split(",")
        current = float(values[0])
        open_price = float(values[7]) if values[7] else current
        change = current - open_price
        change_pct = (change / open_price * 100) if open_price else 0
        return {
            "code": "AU9999",
            "name": "国内黄金(Au99.99)",
            "price": current,
            "change": change,
            "change_pct": change_pct,
        }
    except Exception as e:
        logger.warning("获取国内黄金价格失败: %s", e)
        return None


async def fetch_london_gold_price() -> dict | None:
    """通过新浪财经接口异步获取伦敦金（XAU/USD）实时价格。"""
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://hq.sinajs.cn/list=hf_XAU"
            async with session.get(url, headers=_SINA_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                text = await resp.text(encoding='gbk')
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.warning("获取伦敦金价格失败: %s", e)
        return None

    try:
        line = text.strip()
        if "=" not in line:
            return None
        values = line.split("=", 1)[1].strip('";').split(",")
        if not values[0].strip():
            logger.warning("伦敦金数据为空，可能处于非交易时段")
            return None
        current = float(values[0])
        open_price = float(values[7].strip()) if values[7].strip() else current
        change = current - open_price
        change_pct = (change / open_price * 100) if open_price else 0
        return {
            "code": "XAU",
            "name": "伦敦金(XAU/USD)",
            "price": current,
            "change": change,
            "change_pct": change_pct,
        }
    except (ValueError, IndexError) as e:
        logger.warning("解析伦敦金价格失败: %s", e)
        return None


def fetch_london_gold_price_sync() -> dict | None:
    """通过新浪财经接口获取伦敦金（XAU/USD）实时价格（同步版本）。"""
    try:
        resp = requests.get(
            "https://hq.sinajs.cn/list=hf_XAU",
            headers=_SINA_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        line = resp.text.strip()
        if "=" not in line:
            return None
        values = line.split("=", 1)[1].strip('";').split(",")
        current = float(values[0])
        open_price = float(values[7]) if values[7] else current
        change = current - open_price
        change_pct = (change / open_price * 100) if open_price else 0
        return {
            "code": "XAU",
            "name": "伦敦金(XAU/USD)",
            "price": current,
            "change": change,
            "change_pct": change_pct,
        }
    except Exception as e:
        logger.warning("获取伦敦金价格失败: %s", e)
        return None


def fetch_all_indices(config: dict) -> list[dict]:
    """根据配置聚合获取所有指数（A股、全球）及黄金行情数据。

    Args:
        config: 配置字典，包含 indices（指数列表，按 source 分类）和 gold 配置。

    Returns:
        所有行情数据的列表，每个元素为包含 code、name、price、change、change_pct 的字典。
    """
    all_data = []
    em_codes = []
    global_codes = []

    for item in config.get("indices", []):
        if item["source"] == "akshare_em":
            em_codes.append(item["code"])
        elif item["source"] == "akshare_global":
            global_codes.append(item["code"])

    if em_codes:
        all_data.extend(fetch_akshare_em_indices(em_codes).values())
    if global_codes:
        all_data.extend(fetch_global_indices(global_codes).values())

    gold_cfg = config.get("gold", {})
    if gold_cfg.get("enabled"):
        gold_type = gold_cfg.get("type", "domestic")
        if gold_type == "london":
            gold = fetch_london_gold_price()
        else:
            gold = fetch_gold_price()
        if gold:
            all_data.append(gold)

    return all_data

if __name__ == "__main__":
    # res = asyncio.run(fetch_usd_cny_rate())
    res = asyncio.run(fetch_gold_price())
    price = res.get("price") if res else None
    
    
