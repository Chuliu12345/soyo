import os
import botpy
from botpy.ext.cog_yaml import read
from botpy.message import C2CMessage
from src.data_fetcher import fetch_global_indices, fetch_gold_price, fetch_london_gold_price, fetch_usd_cny_rate
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
def add_handler(args: str) -> str:
    return f"添加成功：{args}"

def remove_handler(args: str) -> str:
    return f"移除成功：{args}"

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
            res = await fetch_global_indices(sina_map, args.split())
            print(res)
            if not res:
                return "获取指数数据失败，请检查代码是否正确"
            return "\n".join([f"{v['name']}: {v['price']:.2f}， 涨跌幅:{v['change_pct']:.2f}%" for k, v in res.items()])
        
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
            return add_handler(args)
        case "/remove":
            return remove_handler(args)
        case "/天气":
            return f"天气指令，参数：{args}" if args else "天气查询中..."
        case "/帮助":
            return "可用指令：/指数 <参数>、/天气 <城市>、/帮助"
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