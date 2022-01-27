from exchange_info import get_exchange_info
from binance import AsyncClient, BinanceSocketManager
import asyncio
import os
import websockets
import json
import orders
from threading import Thread
from random import randint
import math
import ssl

active_cons = []

async def create_client():
    client = await AsyncClient.create(api_key=os.environ.get('apikey'), api_secret=os.environ.get('secretkey'))
    exinfo = await get_exchange_info(client)
    print('new client')
    return client, exinfo

async def app(sock, *args):
    active_cons.append(sock)
    print('added active connection', len(active_cons))
    client, exinfo =  await create_client()
    #initialize stats
    stats = {
        'gp': 0,
        'fees': 0,
        'np': 0
    }
    wallet = {
        'cash': '?',
        'positions': {}
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
        async def send(msg):
            return await send_client(client, sock, msg)

        async def recv():
            return await recv_client(client, sock)

        while True:
            msg = await recv()
            # process message
            order = json.loads(msg)
            sym = order['symbol'].upper()
            minqty = float(exinfo[sym]['minQty'])
            tick_size = float(exinfo[sym]['tickSize'])
            side = order['side'].upper()
            # makes sure last price is not undefined
            if order.get('lastprice') == None:
                await send('not yet')
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
                # parse message and calculate p&l if appropriate
                wallet, stats = parse_userdata(userdata, wallet, stats)
            
            message = {'wallet': wallet, 'stats': stats}
            #send message to client
            await send(json.dumps(message))

async def send_client(client, sock, msg):
    try:
        return await sock.send(msg)
    except Exception:
        active_cons.remove(sock)
        print('connection terminated', len(active_cons))
        await sock.close()
        await client.close_connection()

async def recv_client(client, sock):
    try:
        return await sock.recv()
    except Exception:
        active_cons.remove(sock)
        print('connection terminated', len(active_cons))
        await sock.close()
        await client.close_connection()
        raise Exception('connection closed')


def parse_userdata(msg, wallet, stats):
    event = msg['e'] # ACCOUNT_UPDATE, ORDER_TRADE_UPDATE
    print()
    print(msg)
    
    if event == 'ORDER_TRADE_UPDATE':
        # puts raw data into variables
        trade_update = msg.get('o').get('X') # FILLED, NEW
        
        if trade_update == 'FILLED':
            gross_profit = float(msg['o']['rp'])

            side = msg['o']['S'] # BUY, SELL

            fee_asset = msg['o']['N']

            fee = float(msg['o']['n'])

            symbol = msg['o']['s']

            quantity = float(msg['o']['q'])

            average_price = float(msg['o']['ap'])
            # end raw data
            stats['gp'] += gross_profit
            stats['fees'] += fee
            stats['np'] = stats['gp'] - stats['fees']
            this_trade_value = quantity * average_price
            manage_positions(wallet, symbol, quantity, side)
            

    elif event == 'ACCOUNT_UPDATE':
        current_positions = msg.get('a').get('P')

        for bal in msg['a']['B']:
            if bal['a'] == 'USDT':
                wallet_balance = bal['wb']
                break
        
        # update wallet balance
        wallet['cash'] = wallet_balance

    print(wallet, stats)
    return wallet, stats

def manage_positions(wallet, symbol, quantity, side):
    symbol = symbol.lower()
    if side == 'BUY':
        trade_quantity = quantity
    elif side == 'SELL':
        trade_quantity = -quantity
    
    if symbol not in wallet['positions']:
        wallet['positions'][symbol] = trade_quantity
    else:
        wallet['positions'][symbol] += trade_quantity
        if wallet['positions'][symbol] == 0:
            del wallet['positions'][symbol]

def gen_ssl():
    os.system('openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -sha256 -days 365')
    #requires some user input here

def get_ssl_context():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain('./cert.pem', './key.pem')
    return context

async def start_server():
    async with websockets.serve(app, '0.0.0.0', 8050, ssl=get_ssl_context()) as server:
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(start_server())