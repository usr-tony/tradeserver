from exchange_info import get_exchange_info
from binance import AsyncClient, BinanceSocketManager
import asyncio
import os
import websockets
from functools import partial
import json
import orders
from threading import Thread
from random import randint
import math
import ssl
import OpenSSL

async def create_client():
    client = await AsyncClient.create(api_key=os.environ.get('apikey'), api_secret=os.environ.get('secretkey'))
    exinfo = await get_exchange_info(client)
    print('new client')
    return client, exinfo

async def app(sock, *args):
    client, exinfo =  await create_client()
    #initialize stats
    stats = {
        'gross-profit': 0,
        'fees': 0,
        'net-profit': 0
    }
    wallet = {
        'cash': '?',
        'positions': []
    }
    #look at connections and determine if live account should be used
    trading = 'live'
    if trading == 'live':
        await live_trading(stats, wallet, exinfo, sock, client)
    else:
        await client.close_connection()
        await sock.close()
        #todo
        #await simulated_trading()
    

async def live_trading(stats, wallet, exinfo, sock, client):
    #create socket to binance servers
    bm = BinanceSocketManager(client)
    binance_socket = bm.futures_user_socket()
    #assuming trading is live
    async with binance_socket:
        while True:
            msg = await sock.recv()
            # process message
            order = json.loads(msg)
            sym = order['symbol'].upper()
            minqty = float(exinfo[sym]['minQty'])
            tick_size = float(exinfo[sym]['tickSize'])
            side = order['side'].upper()
            # makes sure last price is not undefined
            if order.get('lastprice') == None:
                await sock.send('not yet')
                continue
            lastprice = float(order['lastprice'])
            #define qty to be minqty if notional value is greater than 5
            if minqty * lastprice > 5:
                qty = minqty
            else:
                value = minqty * lastprice
                qty = math.ceil(5 / value) * minqty
            # send order
            res = await orders.create_order(client, sym=sym, side=side, qty=qty)
            # receive a few messages if available
            status_message = 'start'
            while True:
                #receive response from binance server
                try:
                    userdata = await asyncio.wait_for(binance_socket.recv(), timeout=0.1)
                except:
                    break
                print(userdata)
                # parse message and calculate p&l if appropriate
                wallet, stats = parsebinance_userdata(userdata, wallet, stats)
            message = {'wallet': wallet, 'stats': stats}
            #send message to client
            await sock.send(json.dumps(message))



def parsebinance_userdata(msg, wallet, stats):
    event = msg['e']
    if event == 'ACCOUNT_UPDATE':
        balances = msg['a']['B']
        for b in balances:
            if b['a'] == 'USDT':
                wallet_balance = float(b['wb'])
                cross_wallet_balance = float(b['cw'])
                change_in_cash = float(b['bc'])
                wallet['cash'] = wallet_balance + cross_wallet_balance + change_in_cash
                break

        positions = []
        for p in msg['a']['P']:
            # add symbol and value to positions
            positions.append({
                'symbol': p['s'],
                'value': float(p['pa']) * float(p['ep'])
            })
        wallet['positions'] = positions
    
    elif event == 'ORDER_TRADE_UPDATE':
        order_status = msg['o']['X']
        if order_status == 'NEW':
            return wallet, stats
        realized_profit = float(msg['o']['rp'])
        print(msg)
        fee_asset = msg['o']['N']
        fee = float(msg['o']['n'])
        stats['gross-profit'] += realized_profit
        if 'USD' in fee_asset:
            stats['fees'] += fee
        
    return wallet, stats

async def client_message_handler(sock, client, exinfo):
    async for msg in sock:
        print(msg)


def get_ssl():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain('./server.cert', './server.key')
    return context

async def start_server():
    async with websockets.serve(app, '0.0.0.0', 8050, ssl=get_ssl()) as server:
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(start_server())