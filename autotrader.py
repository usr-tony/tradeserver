import asyncio
import threading
from binance import BinanceSocketManager, AsyncClient
import _binance
import os
import time
from bisect import bisect_left
from math import floor
from statistics import mean


symbols = [
    'ETHUSDT',
    'BCHUSDT',
    'LTCUSDT',
    'AXSUSDT',
    'DOGEUSDT',
]

position = {'status': 0, 'symbol': '', 'qty': 0} # keeps track of current position; status 1 = long, -1 = short, 0 = no position;
tables = dict()  # table containing parsed websocket trade data
sym_index = dict() # moving averages of individual tickers

for s in symbols:
    tables[s] = {
        'T': [],
        'b': [],
        'a': []
    }
    sym_index[s] = []

async def main():
    client = await AsyncClient.create(api_key=os.environ.get('apikey'), api_secret=os.environ.get('secretkey'))
    exinfo = await _binance.get_exchange_info(client)
    t = threading.Thread(target=calc_indices, args=(None,))
    t.start()
    await start_soc(exinfo, None)


async def start_soc(ex_info, e):
    client = await AsyncClient.create(api_key=os.environ.get('apikey'), api_secret=os.environ.get('secretkey'))
    bsm = BinanceSocketManager(client)
    ts = bsm.futures_multiplex_socket([s.lower() + '@bookTicker' for s in symbols]) # starts a socket with all symbols in symbols file
    async with ts: # starts receiving messages and appends them to table
        print('auto started')
        while True:
            if e:
                if e.is_set():
                    break
            d = await ts.recv()
            sym = d['stream'].split('@')[0].upper()     # retrieves symbol from websocket message
            table = tables[sym]    
            table['T'].append(int(d['data']['T']))     # appends the following to tables[symbol]: timestamp
            table['b'].append(float(d['data']['b']))     # closest bid
            table['a'].append(float(d['data']['a']))     # closest ask
            await signal(sym, client, ex_info)

    await client.close_connection()
    return

async def signal(sym, client, ex_info):
    if sym_index[sym] == []:
        return
    rel_prices = []
    agg_index = 0
    for s in symbols:
        index_mean = mean(sym_index[s])
        rel_bid = tables[s]['b'][-1] / index_mean
        rel_ask = tables[s]['a'][-1] / index_mean
        rel_mid = (rel_bid + rel_ask) / 2
        rel_prices.append([s, rel_mid, rel_bid, rel_ask])
        # for relative prices:
        # 0 : symbol
        # 1 : mid price
        # 2 : bid
        # 3 : ask
        agg_index += rel_mid

    print('autotrader works:', agg_index)
    print('\033[F', end='')
    agg_index /= len(symbols)   # aggregate index is the average calculated index of all symbols considered
    if abs(agg_index - 1) > 0.0004 and position['status'] == 0:
        if_reverse = True if agg_index > 0 else False
        rel_prices.sort(key=lambda x:x[1], reverse=if_reverse)

        if abs(rel_prices[0][1] - 1) > 0.0008 and abs(rel_prices[1][1] - 1) > 0.0005:
            position['symbol'] = rel_prices[-1][0]    # asset of interest is the one that is slowest to move
            
            if position['symbol'] != 'BTCUSDT':
                side = 'BUY' if agg_index > 1 else 'SELL'
                price = tables[position['symbol']]['a'][-1] if side == 'BUY' else tables[position['symbol']]['b'][-1]
                min_qty = float(ex_info[position['symbol']]['minQty'])   
                # dictionary of symbol : {minQty: <minimum trade quantity>, tickSize: <contract tick size>}
                qty = floor(5.0 // (min_qty * price) + 1) * min_qty
                await create_order(client, position['symbol'], side, price, 'MARKET', qty)
                position['qty'] = qty
                if agg_index > 1: 
                    position['status'] = 1
                elif agg_index < 1: 
                    position['status'] = -1
                
                print(price, position, 'minqty:', min_qty, 'precision:', ex_info[position['symbol']]['tickSize'])


    elif position['status'] != 0 and abs(agg_index - 1) < 0.0002:
        side = 'BUY' if position['status'] == -1 else 'SELL'
        qty = position['qty']
        await create_order(client, position['symbol'], side, qty=qty)
        price = tables[position['symbol']]['a'][-1] if side == 'BUY' else tables[position['symbol']]['b'][-1]
        position['status'] = 0
        position['symbol'] = ''
        position['qty'] = 0

def calc_indices(e):
    time.sleep(5) # waits for websockets to initialize and collect data
    while True:
        for s in symbols:
            update_index(s)
    
        time.sleep(0.67)
        if e:
            if e.is_set():
                return

def update_index(sym): # generates index and relative index values from table containing raw trade data
    time_stamp, bid, ask = [tables[sym][c] for c in tables[sym]] # extracts columns from table as variables
    index_values = []
    for dt in [20000, 10000, 5000]: #  generate index values for to determine asset price (x)ms ago
        t1 = time_stamp[-1] - dt
        ii = bisect_left(time_stamp, t1)
        index_values.append(ii)

    mid_prices = []
    rel_mid_prices = []
    relative_price = ((bid[index_values[0]] + ask[index_values[0]]) / 2)
    for ii in index_values:
        mid = (bid[ii] + ask[ii]) / 2
        mid_prices.append(mid)
        rel_mid_prices.append(mid / relative_price)
        
    sym_index[sym] = mid_prices


async def create_order(client, sym, side, price=None, type='MARKET', qty=0.002):
    task = asyncio.create_task(order(client, sym, side, price, type, qty))


async def order(client, sym, side, price, type, qty):
    trade_params = {
        'symbol': sym,
        'side': side,
        'type': type,
        'quantity': qty,
        'price': price,
        'reduce_only': 'False'
    }
    if trade_params['type'] == 'LIMIT': 
        trade_params['timeInForce'] = 'GTC'

    if trade_params['type'] == 'MARKET':
        del trade_params['price']

    res = await client.futures_create_order(**trade_params)
    return

def indices():
    global tables
    time.sleep(22) # waits for websockets to initialize and collect data
    while True:
        for s in symbols:
            update_index(s)
    
        time.sleep(0.67)


def update_index(sym): # generates index and relative index values from table containing raw trade data
    global tables
    global sym_index
    time_stamp, bid, ask = [tables[sym][c] for c in tables[sym]] # extracts columns from table as variables
    index_values = []
    for dt in [20000, 10000, 5000]: #  generate index values for to determine asset price (x)ms ago
        t1 = time_stamp[-1] - dt
        ii = bisect_left(time_stamp, t1)
        index_values.append(ii)

    mid_prices = []
    rel_mid_prices = []
    relative_price = ((bid[index_values[0]] + ask[index_values[0]]) / 2)
    for ii in index_values:
        mid = (bid[ii] + ask[ii]) / 2
        mid_prices.append(mid)
        rel_mid_prices.append(mid / relative_price)
        
    sym_index[sym] = mid_prices


if __name__ == '__main__':
    asyncio.run(main())