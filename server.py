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
    if len(active_cons) == 1:
        live = True
    else:
        live = False
        
    if live:
        await live_trading(stats, wallet, exinfo, sock, client)
    else:
        await simulated_trading(stats, wallet, exinfo, sock, client)
    
# starts live trading if there is only 1 client
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
            try:
                msg = await recv()
            except:
                break
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

async def send_client(client=None, sock=None, msg=None):
    try:
        return await sock.send(msg)
    except Exception:
        active_cons.remove(sock)
        print('connection terminated', len(active_cons))
        await sock.close()
        if client != None:
            await client.close_connection()
        raise Exception

async def recv_client(client=None, sock=None):
    try:
        return await sock.recv()
    except Exception:
        active_cons.remove(sock)
        print('connection terminated', len(active_cons))
        await sock.close()
        if client != None:
            await client.close_connection()
        raise Exception


def parse_userdata(msg, wallet, stats):
    event = msg['e'] # ACCOUNT_UPDATE, ORDER_TRADE_UPDATE

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
            manage_positions(wallet, symbol, quantity, side, average_price)
            

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

def manage_positions(wallet, symbol, quantity, side, average_price):
    symbol = symbol.lower()
    if side == 'BUY':
        trade_quantity = quantity
    else:
        trade_quantity = -quantity
    
    if symbol not in wallet['positions']:
        wallet['positions'][symbol] = {'qty': trade_quantity}
    else:
        wallet['positions'][symbol]['qty'] += trade_quantity
        wallet['positions'][symbol]['avgprice'] = average_price
        if wallet['positions'][symbol]['qty'] == 0:
            del wallet['positions'][symbol]

### simulated trading section ###
async def simulated_trading(stats, wallet, exinfo, sock, client):
    async def send(msg):
        await send_client(client, sock, msg)

    # determine trade quantities for various assets
     
    # load wallet with initial cash
    wallet['cash'] = 100000
    trade_size = 10000
    while True:
        msg = await recv_client(client, sock)
        order = json.loads(msg)
        sym = order['symbol'].upper()
        side = order['side'].upper()
        if order.get('lastprice') == None:
            await send('not yet')
            continue
        
        lastprice = float(order['lastprice'])
        minqty = float(exinfo[sym]['minQty'])
        #makes each trade approx 10k in size
        if minqty * lastprice > trade_size:
            qty = minqty
        else:
            value = minqty * lastprice
            qty = math.ceil(trade_size / value) * minqty
        # create simulated trade
        error = sim_trade(wallet, stats, sym, side, qty, lastprice, client, trade_size, minqty)
        if error:
            message = error
        else:
            message = json.dumps({'wallet': wallet, 'stats': stats})
        
        await send(message)

def sim_trade(wallet, stats, symbol, side, qty, lastprice, client, trade_size, minqty, hx=[]):
    if side == 'BUY':
        trade_quantity = qty
    else:
        trade_quantity = -qty

    fee_mod = 0.0004
    # check if position is reducing
    # check if position already in wallet
    reducing = wallet['positions'].get(symbol) != None
    # checks if current position is of opposing side as trade quantity
    if reducing:
        cri1 = wallet['positions'][symbol]['qty'] > 0 and trade_quantity < 0
        cri2 = wallet['positions'][symbol]['qty'] < 0 and trade_quantity > 0
        reducing = cri1 or cri2

    if reducing:
        avgprice = float(wallet['positions'][symbol]['avgprice'])
        # sets trade qty to be equal to current position if they are similar to avoid small residual quantities
        if round(abs(trade_quantity / wallet['positions'][symbol]['qty'])) == 1:
            trade_quantity = -wallet['positions'][symbol]['qty']

        wallet['positions'][symbol]['qty'] += trade_quantity
        gp = (avgprice - lastprice) * trade_quantity
        fees = abs(trade_quantity) * lastprice * fee_mod
        stats['gp'] += gp
        wallet['cash'] += abs(trade_quantity * lastprice) -  fees

        if side == 'BUY': # necessary as the absolute values of trade quantity reverses the gp of a short
            wallet['cash'] += gp * 2

    elif wallet['cash'] < abs(minqty * lastprice):
        return 'insufficient margin'
    else: # position is not reducing, instead is an addition or new position
        if qty * lastprice > wallet['cash']:
            print('low on cash')
            trade_quantity = math.floor(wallet['cash'] / (lastprice * minqty)) * minqty
            if side == 'SELL':
                trade_quantity = -trade_quantity

        # execute trade
        if wallet['positions'].get(symbol) == None:
            # if this is a new position
            wallet['positions'][symbol] = {
                'qty' : trade_quantity,
                'avgprice' : lastprice
            }
        else:
            # if position already exists in the system
            # recalculate average price
            curr_avgprice = wallet['positions'][symbol]['avgprice']
            curr_qty = wallet['positions'][symbol]['qty']
            total_qty = curr_qty + trade_quantity
            new_avgprice = ((curr_qty * curr_avgprice) + (lastprice * trade_quantity)) / total_qty
            wallet['positions'][symbol]['avgprice'] = new_avgprice
            # update quantities
            wallet['positions'][symbol]['qty'] += trade_quantity

        fees = abs(trade_quantity) * lastprice * fee_mod
        wallet['cash'] -= abs(trade_quantity * lastprice) + fees

    stats['fees'] += fees
    stats['np'] = stats['gp'] - stats['fees']

    # delete positions with 0 qty
    positions = [sym for sym in wallet['positions']]
    for sym in positions:
        if wallet['positions'][sym]['qty'] == 0:
            del wallet['positions'][sym]

    return 0


    
# below is to start the websocket server
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