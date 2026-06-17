import os
import botpy
from botpy.ext.cog_yaml import read
from botpy.message import C2CMessage
from src.data_fetcher import (
    fetch_global_indices, fetch_gold_price, fetch_london_gold_price, fetch_usd_cny_rate,
    fetch_em_indices, fetch_hk_indices, fetch_global_indices_sync,
    get_watchlist, add_to_watchlist, remove_from_watchlist,
    QuoteData,
)

from botpy import logging

sina_map = {
    "SPX": "int_sp500",
    "标普": "int_sp500",
    "标普500": "int_sp500",
    "恒科": "rt_hkHSI",
    "DJIA": "int_dji",
    "N225": "int_nikkei",
    "HSI": "rt_hkHSI",
}
test_config = read(os.path.join(os.path.dirname(__file__), "config.yaml"))
_log = logging.get_logger()


async def fetch_watchlist_quotes() -> list[dict]:
    """获取关注列表中所有指数的实时行情。

    Returns:
        行情数据列表，每个元素包含 code、name、price、change、change_pct。
    """
    watchlist = get_watchlist()
    if not watchlist:
        return []

    # 按来源分组
    em_codes = [item["code"] for item in watchlist if item["source"] == "akshare_em"]
    hk_codes = [item["code"] for item in watchlist if item["source"] == "akshare_hk"]
    global_codes = [item["code"] for item in watchlist if item["source"] == "akshare_global"]

    all_data = []

    # 并行获取各来源数据
    import asyncio
    tasks = []
    if em_codes:
        # akshare_em 来源：先尝试用个股接口获取，获取不到的再走指数接口
        tasks.append(asyncio.to_thread(_fetch_em_mixed, em_codes))
    if hk_codes:
        tasks.append(asyncio.to_thread(fetch_hk_indices, hk_codes))
    if global_codes:
        tasks.append(asyncio.to_thread(fetch_global_indices_sync, global_codes))

    if tasks:
        results = await asyncio.gather(*tasks)
        for result in results:
            if isinstance(result, dict):
                all_data.extend(result.values())
            else:
                all_data.extend(result)

    return all_data



def _fetch_em_mixed(codes: list[str]) -> list[QuoteData]:
    """获取 A 股来源数据，先尝试个股接口，获取不到的再走指数接口，
    最后尝试开放式基金接口。

    Args:
        codes: 代码列表，如 ["000001", "600519", "161725", "017730"]

    Returns:
        行情数据列表。
    """
    from src.data_fetcher import fetch_stock_quote, fetch_em_indices, fetch_open_fund_quote

    result = []
    stock_failed = []

    # 先尝试个股接口
    for code in codes:
        quote = fetch_stock_quote(code)
        if quote is not None:
            result.append(quote)
        else:
            stock_failed.append(code)

    # 个股接口获取不到的，走指数接口
    if stock_failed:
        indices_data = fetch_em_indices(stock_failed)
        # 记录指数接口获取到的代码
        found_in_indices = set(indices_data.keys())
        result.extend(indices_data.values())

        # 指数接口也获取不到的，尝试开放式基金接口
        fund_failed = [c for c in stock_failed if c not in found_in_indices]
        for code in fund_failed:
            quote = fetch_open_fund_quote(code)
            if quote is not None:
                result.append(quote)

    return result




async def message_handler(content: str) -> str:
    content = content.strip()
    if not content.startswith("/"):
        return ""

    parts = content.split(maxsplit=1)
    command = parts[0]
    args = parts[1] if len(parts) > 1 else ""
    print(args.split())

    match command:
        case "/指数":
            if args:
                # 带参数：查询指定指数
                res = await fetch_global_indices(sina_map, args.split())
                print(res)
                if not res:
                    return "获取指数数据失败，请检查代码是否正确"
                return "\n".join([f"{v['name']}: {v['price']:.2f}， 涨跌幅:{v['change_pct']:.2f}%" for k, v in res.items()])
            else:
                # 不带参数：查询关注列表中所有指数
                quotes = await fetch_watchlist_quotes()
                if not quotes:
                    return "关注列表为空，请使用 /add 添加指数"
                lines = []
                for q in quotes:
                    change_arrow = "📈" if q["change"] >= 0 else "📉"
                    lines.append(f"{q['name']}: {q['price']:.2f}  {change_arrow} {q['change_pct']:+.2f}%")
                return "\n".join(lines)

        case "/黄金":
            gold = await fetch_gold_price()
            if gold:
                return f"{gold['name']}: {gold['price']:.2f}，涨跌幅:{gold['change_pct']:.2f}%"
            
            gold = await fetch_london_gold_price()
            if not gold:
                return "获取黄金价格失败"
            rate = await fetch_usd_cny_rate()
            if not rate:
                return "获取汇率失败，无法转换价格"
            price_rmb_per_gram = gold['price'] * rate['price'] / 31.1035
            change_rmb = gold['change'] * rate['price'] / 31.1035
            open_price_rmb = price_rmb_per_gram - change_rmb
            change_pct = (change_rmb / open_price_rmb * 100) if open_price_rmb else 0
            return f"非交易时段，伦敦金(折合): {price_rmb_per_gram:.2f}元/克，涨跌幅:{change_pct:.2f}%"

        case "/add":
            if not args:
                return "请指定要添加的指数代码，例如：/add 000001"
            success, msg = add_to_watchlist(args)
            return msg

        case "/remove":
            if not args:
                return "请指定要移除的指数代码，例如：/remove 000001"
            success, msg = remove_from_watchlist(args)
            return msg

        case "/天气":
            return f"天气指令，参数：{args}" if args else "天气查询中..."

        case "/帮助":
            return "📋 可用指令：\n/指数 - 查看关注列表中的所有指数\n/指数 <代码> - 查询指定指数\n/add <代码> - 添加指数到关注列表\n/remove <代码> - 从关注列表移除指数\n/黄金 - 查询黄金价格\n/天气 <城市> - 查询天气\n/帮助 - 显示此帮助"

        case _:
            return f"未知指令：{command}"


class MyClient(botpy.Client):
    async def on_ready(self):
        _log.info(f"robot 「{self.robot.name}」 on_ready!")

    async def on_c2c_message_create(self, message: C2CMessage):
        reply = await message_handler(message.content)
        if not reply:
            return
        msg_seq = hash(message.id) % (2**31)
        await message._api.post_c2c_message(
            openid=message.author.user_openid,
            msg_type=0,
            msg_id=message.id,
            # msg_seq=msg_seq,
            content=reply,
        )

if __name__ == "__main__":
    intents = botpy.Intents(public_messages=True)
    client = MyClient(intents=intents)
    client.run(appid=test_config["appid"], secret=test_config["secret"])