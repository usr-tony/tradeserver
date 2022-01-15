from binance import AsyncClient, BinanceSocketManager
from os import environ
import asyncio
import json

async def main():
    client = await create_client()
    await start_udstream(client)

async def create_client():
    apikey = environ.get('apikey')
    apisecret = environ.get('secretkey')
    client = await AsyncClient.create(api_key=apikey, api_secret=apisecret)
    return client

async def start_udstream(client):
    bm = BinanceSocketManager(client)
    sock = bm.futures_user_socket()
    async with sock:
        while True:
            msg = await sock.recv()
            print(msg)


        

if __name__ == "__main__":
    asyncio.run(main())