import os
from binance import AsyncClient, BinanceSocketManager
import asyncio
from time import sleep

async def create_client():
    client = await AsyncClient.create(api_key=os.environ.get('apikey'), api_secret=os.environ.get('secretkey'))
    exinfo = await get_exchange_info(client)
    print('new client')
    return client, exinfo

async def main():
    client, _ = await create_client
    task = asyncio.create_task(create_order(client, 'ETHUSDT', 'BUY', tradetype='LIMIT', price='2500'))
    res = await task
    await client.close_connection()
    print(res)
    return res

async def create_order(client, sym, side, price=None, tradetype='MARKET', qty=0.002, reduce_only='False'):
    sym = sym.upper()
    res = await order(client, sym, side, price, tradetype, qty, reduce_only)
    return res

async def order(client, sym, side, price, tradetype, qty, reduce_only='False'):
    trade_params = {
        'symbol': sym,
        'side': side,
        'type': tradetype,
        'quantity': qty,
        'price': price,
        'reduce_only': reduce_only
    }
    if trade_params['type'] == 'LIMIT': trade_params['timeInForce'] = 'GTC'
    if trade_params['type'] == 'MARKET': del trade_params['price']
    return await client.futures_create_order(**trade_params)

async def close_all(client):
    res = await client.futures_account()
    for position in res['positions']:
        if float(position['positionAmt']) != 0:
            if round(float(position['notional']) / 5) != 0:
                side = 'BUY' if float(position['positionAmt'] > 0) else 'SELL'
                res = await create_order(client, position['symbol'], side, qty=float(position['positionAmt']), reduce_only='True')
            
    return 0


async def get_exchange_info(client):
    ex_info = {}
    r = await client.futures_exchange_info()
    for row in r['symbols']:
        k = row['filters']
        d = ex_info[row['symbol']] = {}
        d['minQty'] = k[1]['minQty']
        d['tickSize'] = k[0]['tickSize']
    
    return ex_info


if __name__ == '__main__':
    asyncio.run(main())