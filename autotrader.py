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
    'XRPUSDT',
    'DOGEUSDT',
]

async def main():
    client = await AsyncClient.create(api_key=os.environ.get('apikey'), api_secret=os.environ.get('secretkey'))
    exinfo = await _binance.get_exchange_info(client)
    await start(exinfo, None, client)


async def start(ex_info, e, client=None):
    if not client:
        client = await AsyncClient.create(api_key=os.environ.get('apikey'), api_secret=os.environ.get('secretkey'))

    bsm = BinanceSocketManager(client)
    ts = bsm.futures_multiplex_socket([s.lower() + '@bookTicker' for s in symbols]) # starts a socket with all symbols in symbols file
    dm = Data_manager()
    dm_thread = dm._start(e)
    async with ts: # starts receiving messages and appends them to table
        print('auto started')
        while True:
            if e:
                if e.is_set():
                    break
            d = await ts.recv()
            sym = d['stream'].split('@')[0].upper()     # retrieves symbol from websocket message
            table = dm.tables[sym]    
            table['T'].append(int(d['data']['T']))     # appends the following to tables[symbol]: timestamp
            table['b'].append(float(d['data']['b']))     # closest bid
            table['a'].append(float(d['data']['a']))     # closest ask
            await signal(sym, client, ex_info, dm)

    await client.close_connection()
    return

async def signal(sym, client, ex_info, dm):
    sym_index = dm.sym_index
    tables = dm.tables
    position = dm.position
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
                prec = ex_info[position['symbol']]['qtyprecision']
                qty = round(qty, prec)
                await create_order(client, position['symbol'], side, price, 'MARKET', qty)
                position['qty'] = qty
                if agg_index > 1: 
                    position['status'] = 1
                elif agg_index < 1: 
                    position['status'] = -1


    elif position['status'] != 0 and abs(agg_index - 1) < 0.0002:
        side = 'BUY' if position['status'] == -1 else 'SELL'
        qty = position['qty']
        await create_order(client, position['symbol'], side, qty=qty)
        price = tables[position['symbol']]['a'][-1] if side == 'BUY' else tables[position['symbol']]['b'][-1]
        position['status'] = 0
        position['symbol'] = ''
        position['qty'] = 0


class Data_manager:
    def __init__(s):
        s.position = {'status': 0, 'symbol': '', 'qty': 0} # keeps track of current position; status 1 = long, -1 = short, 0 = no position;
        s.tables = dict()  # table containing parsed websocket trade data
        s.sym_index = dict() # moving averages of individual tickers

        for sym in symbols:
            s.tables[sym] = {
                'T': [],
                'b': [],
                'a': []
            }
            s.sym_index[sym] = []


    def _start(s, e):
        return threading.Thread(target=s.calc_indices, args=[e]).start()


    def calc_indices(s, e):
        time.sleep(10) # waits for websockets to initialize and collect data
        while True:
            for sym in symbols:
                s.update_index(sym)
        
            time.sleep(0.67)
            if e:
                if e.is_set():
                    return

    def update_index(s, sym): # generates index and relative index values from table containing raw trade data
        time_stamp, bid, ask = [s.tables[sym][c] for c in s.tables[sym]] # extracts columns from table as variables
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
            
        s.sym_index[sym] = mid_prices


async def create_order(client, sym, side, price=None, tradetype='MARKET', qty=0.002):
    task = asyncio.create_task(_binance.order(client, sym, side, price, tradetype, qty))


if __name__ == '__main__':
    asyncio.run(main())