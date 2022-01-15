from os import environ
from binance import AsyncClient, BinanceSocketManager
import asyncio
from time import sleep


async def main():
    client = await AsyncClient.create(api_key=environ.get('apikey'), api_secret=environ.get('secretkey'))
    task = asyncio.create_task(create_order(client, 'ETHUSDT', 'BUY', tradetype='LIMIT', price='2500'))
    res = await task
    await client.close_connection()
    print(res)
    return res

async def create_order(client, sym, side, price=None, tradetype='MARKET', qty=0.002):
    res = await order(client, sym, side, price, tradetype, qty)
    return res


async def order(client, sym, side, price, tradetype, qty):
    trade_params = {
        'symbol': sym,
        'side': side,
        'type': tradetype,
        'quantity': qty,
        'price': price,
        'reduce_only': 'False'
    }
    if trade_params['type'] == 'LIMIT': trade_params['timeInForce'] = 'GTC'
    if trade_params['type'] == 'MARKET': del trade_params['price']
    return await client.futures_create_order(**trade_params)


if __name__ == '__main__':
    asyncio.run(main())