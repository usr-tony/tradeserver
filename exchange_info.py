from binance import AsyncClient
from os import environ
from time import *
from asyncio import run


async def main():
    t = time()
    client = await AsyncClient.create(api_key=environ.get('apikey'), api_secret=environ.get('secretkey'))
    res = await get_exchange_info(client)
    await client.close_connection()
    print(res['BTCUSDT']['minQty'])


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
    run(main())