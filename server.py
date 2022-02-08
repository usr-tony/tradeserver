import asyncio
import websockets
import json
from _binance import create_client, create_order, close_all, get_exchange_info
import math
import ssl
from binance import BinanceSocketManager
import autotrader
from threading import Thread, Event

active_cons = []

async def app(sock, *args):
    active_cons.append(sock)
    print('added active connection', len(active_cons))
    client =  await create_client()
    exinfo = await get_exchange_info(client)
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
    live = True if len(active_cons) == 1 else False
    if live:
        await live_trading(stats, wallet, exinfo, sock, client)
    else:
        await simulated_trading(stats, wallet, exinfo, sock, client)
    
# starts live trading if there is only 1 client
async def live_trading(stats, wallet, exinfo, sock, client):
    #create socket to binance servers
    bm = BinanceSocketManager(client)
    binance_socket = bm.futures_user_socket()
    await binance_socket.__aenter__()
    #assuming trading is live
    await send(client, sock, 'live')
    auto_trading = False
    while True:
        try:
            msg = await recv(client, sock)
        except:
            if auto_trading:
                stop_autotrader(*args)

            break
        # process message
        if not msg:
            pass
        elif msg in ['auto', 'stop auto']:
            if not auto_trading and msg == 'auto':
                await send(client, sock, 'auto trading started')
                args = start_autotrader(client, exinfo)
                auto_trading = True
            elif auto_trading and msg == 'stop auto':
                stop_autotrader(*args)
                auto_trading = False
                await send(client, sock, 'auto trading stopped')
            else:
                continue

        elif not auto_trading:
            try:
                order = json.loads(msg)
            except:
                continue

            sym = order['symbol'].upper()
            minqty = float(exinfo[sym]['minQty'])
            tick_size = float(exinfo[sym]['tickSize'])
            prec = int(exinfo[sym]['qtyprecision'])
            side = order['side'].upper()
            # makes sure last price is not undefined
            if order.get('lastprice') == None:
                await send(client, sock, 'not yet')
                continue
            lastprice = float(order['lastprice'])
            #define qty to be minqty if notional value is greater than 5
            if minqty * lastprice > 5:
                qty = minqty
            else:
                value = minqty * lastprice
                qty = math.ceil(5 / value) * minqty
                qty = round(qty, prec)
            # send order
            await create_order(client, sym=sym, side=side, qty=qty)
        
        # above receives message from client and takes some action 
        ##################################################################################
        # below gets message from binance servers and parses it then sends to client
        userdata = None
        while True:
            #receive response from binance server
            try:
                userdata = await asyncio.wait_for(binance_socket.recv(), timeout=0.001)
            except asyncio.TimeoutError:
                break
            # parse message and calculate p&l if appropriate
            if userdata:
                wallet, stats = parse_userdata(userdata, wallet, stats)
        
        if userdata:
            message = {'wallet': wallet, 'stats': stats}
            #send message to client
            await send(client, sock, json.dumps(message))


    await binance_socket.__aexit__(None, None, None)

def start_autotrader(client, exinfo):
    e = Event()
    e.clear()
    t = Thread(target=asyncio.run, args=[autotrader.start(exinfo, e)])
    t.start()    
    return t, e

def stop_autotrader(t, e):
    e.set()
    t.join()
    print('auto trader stopped')
    return

async def send(client=None, sock=None, msg=None):
    try:
        return await sock.send(msg)
    except Exception as e:
         await handle_dc(client, sock, e)


async def recv(client=None, sock=None):
    try:
        return await asyncio.wait_for(sock.recv(), timeout=0.1)
    except asyncio.TimeoutError:
        return None
    except Exception as e:
        await handle_dc(client, sock, e)


async def handle_dc(client, sock, e):
    if client != None:
        res = await close_all(client)

    active_cons.remove(sock)
    print('connection terminated', len(active_cons))
    await sock.close()
    raise e


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

    return wallet, stats

def manage_positions(wallet, symbol, quantity, side, average_price):
    symbol = symbol.lower()
    trade_quantity = quantity if side == 'BUY' else -quantity
    if not wallet['positions'].get(symbol):
        wallet['positions'][symbol] = {'qty': trade_quantity, 'avgprice': average_price}

    else:
        qty = wallet['positions'][symbol]['qty']
        wallet['positions'][symbol]['qty'] += trade_quantity
        if abs(qty + trade_quantity) > abs(qty): # if position not reducing
            wallet['positions'][symbol]['avgprice'] = average_price
            
        if wallet['positions'][symbol]['qty'] == 0:
            del wallet['positions'][symbol]

### simulated trading section ###

async def recv_simulated(client=None, sock=None):
    try:
        return await sock.recv()
    except Exception as e:
        await handle_dc(client, sock, e)


async def simulated_trading(stats, wallet, exinfo, sock, client):
    # send to client that trades will be simulated
    try:
        await client.close_connection()
    except:
        pass
    
    await send(sock=sock, msg='simulated')
    # load wallet with initial cash
    wallet['cash'] = 100000
    trade_size = 10000
    while True:
        msg = await recv_simulated(sock=sock)
        order = json.loads(msg)
        sym = order['symbol'].upper()
        side = order['side'].upper()
        if order.get('lastprice') == None:
            await send(sock=sock, msg='not yet')
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
        message = error if error else json.dumps({'wallet': wallet, 'stats': stats})
        await send(sock=sock, msg=message)


def sim_trade(wallet, stats, symbol, side, qty, lastprice, client, trade_size, minqty):
    if side == 'BUY':
        trade_quantity = qty
    else:
        trade_quantity = -qty

    fee_mod = 0.0004
    # check if position is reducing
    # checks if current position is of opposing side as trade quantity
    try:
        curr_qty = wallet['positions'][symbol]['qty']
        reducing = abs(curr_qty + trade_quantity) < abs(curr_qty)
    except:
        reducing = False

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

        # delete position is qty is 0
        if wallet['positions'][symbol]['qty'] == 0:
            del wallet['positions'][symbol]

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

    return 0
    
# below starts the websocket server
def get_ssl_context():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain('./certificate.crt', './private.key')
    return context

async def start_server():
    async with websockets.serve(app, '0.0.0.0', 8050, ssl=get_ssl_context()) as server:
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(start_server())