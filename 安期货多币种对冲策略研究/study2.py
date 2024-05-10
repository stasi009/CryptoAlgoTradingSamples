# %% [markdown]
# ## 币安做空超涨做多超跌策略的优化
# 
# 原有研究报告地址：https://www.fmz.com/digest-topic/5294 可以先看一遍，这篇文章不会有重复的内容。重点介绍了第二个策略的优化过程。经过优化策略改进明显，建议根据这篇文章进行策略的升级。回测引擎加入了手续费的统计。

# %%
# 需要导入的库
import pandas as pd
import requests
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
%matplotlib inline

# %%
symbols = ['ETH', 'BCH', 'XRP', 'EOS', 'LTC', 'TRX', 'ETC', 'LINK', 'XLM', 'ADA', 'XMR', 'DASH', 'ZEC', 'XTZ', 'BNB', 'ATOM', 'ONT', 'IOTA', 'BAT', 'VET', 'NEO', 'QTUM', 'IOST']

# %%
price_usdt = pd.read_csv('https://www.fmz.com/upload/asset/20227de6c1d10cb9dd1.csv ', index_col = 0)
price_usdt.index = pd.to_datetime(price_usdt.index)

# %%
price_usdt_norm = price_usdt/price_usdt.fillna(method='bfill').iloc[0,]

# %%
price_usdt_btc = price_usdt.divide(price_usdt['BTC'],axis=0)
price_usdt_btc_norm = price_usdt_btc/price_usdt_btc.fillna(method='bfill').iloc[0,]

# %%
class Exchange:
    
    def __init__(self, trade_symbols, leverage=20, commission=0.00005,  initial_balance=10000, log=False):
        self.initial_balance = initial_balance #初始的资产
        self.commission = commission
        self.leverage = leverage
        self.trade_symbols = trade_symbols
        self.date = ''
        self.log = log
        self.df = pd.DataFrame(columns=['margin','total','leverage','realised_profit','unrealised_profit'])
        self.account = {'USDT':{'realised_profit':0, 'margin':0, 'unrealised_profit':0, 'total':initial_balance, 'leverage':0, 'fee':0}}
        for symbol in trade_symbols:
            self.account[symbol] = {'amount':0, 'hold_price':0, 'value':0, 'price':0, 'realised_profit':0, 'margin':0, 'unrealised_profit':0,'fee':0}
            
    def Trade(self, symbol, direction, price, amount, msg=''):
        if self.date and self.log:
            print('%-20s%-5s%-5s%-10.8s%-8.6s %s'%(str(self.date), symbol, 'buy' if direction == 1 else 'sell', price, amount, msg))
            
        cover_amount = 0 if direction*self.account[symbol]['amount'] >=0 else min(abs(self.account[symbol]['amount']), amount)
        open_amount = amount - cover_amount
        
        self.account['USDT']['realised_profit'] -= price*amount*self.commission #扣除手续费
        self.account['USDT']['fee'] += price*amount*self.commission
        self.account[symbol]['fee'] += price*amount*self.commission
        
        if cover_amount > 0: #先平仓
            self.account['USDT']['realised_profit'] += -direction*(price - self.account[symbol]['hold_price'])*cover_amount  #利润
            self.account['USDT']['margin'] -= cover_amount*self.account[symbol]['hold_price']/self.leverage #释放保证金
            
            self.account[symbol]['realised_profit'] += -direction*(price - self.account[symbol]['hold_price'])*cover_amount
            self.account[symbol]['amount'] -= -direction*cover_amount
            self.account[symbol]['margin'] -=  cover_amount*self.account[symbol]['hold_price']/self.leverage
            self.account[symbol]['hold_price'] = 0 if self.account[symbol]['amount'] == 0 else self.account[symbol]['hold_price']
            
        if open_amount > 0:
            total_cost = self.account[symbol]['hold_price']*direction*self.account[symbol]['amount'] + price*open_amount
            total_amount = direction*self.account[symbol]['amount']+open_amount
            
            self.account['USDT']['margin'] +=  open_amount*price/self.leverage            
            self.account[symbol]['hold_price'] = total_cost/total_amount
            self.account[symbol]['amount'] += direction*open_amount
            self.account[symbol]['margin'] +=  open_amount*price/self.leverage
            
        self.account[symbol]['unrealised_profit'] = (price - self.account[symbol]['hold_price'])*self.account[symbol]['amount']
        self.account[symbol]['price'] = price
        self.account[symbol]['value'] = abs(self.account[symbol]['amount'])*price
        
        return True
    
    def Buy(self, symbol, price, amount, msg=''):
        self.Trade(symbol, 1, price, amount, msg)
        
    def Sell(self, symbol, price, amount, msg=''):
        self.Trade(symbol, -1, price, amount, msg)
        
    def Update(self, date, close_price): #对资产进行更新
        self.date = date
        self.close = close_price
        self.account['USDT']['unrealised_profit'] = 0
        for symbol in self.trade_symbols:
            if np.isnan(close_price[symbol]):
                continue
            self.account[symbol]['unrealised_profit'] = (close_price[symbol] - self.account[symbol]['hold_price'])*self.account[symbol]['amount']
            self.account[symbol]['price'] = close_price[symbol]
            self.account[symbol]['value'] = abs(self.account[symbol]['amount'])*close_price[symbol]
            self.account['USDT']['unrealised_profit'] += self.account[symbol]['unrealised_profit']
            if self.date.hour in [0,8,16]:
                pass
                self.account['USDT']['realised_profit'] += -self.account[symbol]['amount']*close_price[symbol]*0.01/100
        
        self.account['USDT']['total'] = round(self.account['USDT']['realised_profit'] + self.initial_balance + self.account['USDT']['unrealised_profit'],6)
        self.account['USDT']['leverage'] = round(self.account['USDT']['margin']/self.account['USDT']['total'],4)*self.leverage
        self.df.loc[self.date] = [self.account['USDT']['margin'],self.account['USDT']['total'],self.account['USDT']['leverage'],self.account['USDT']['realised_profit'],self.account['USDT']['unrealised_profit']]

# %% [markdown]
# **原来策略的表现，经过币种的筛选，表现的还不错，但是持仓依然很多,普遍在4倍左右**
# 
# 原理：
# - 1.更新行情和账户持仓，第一次运行会记录初始价格（新加入的币种按照加入时间计算）
# - 2.更新指数，指数是山寨币-比特币价格指数 = mean(sum((山寨币价格/比特币价格)/(山寨币初始价格/比特币初始价格)))
# - 3.根据偏离指数判断做多做空,根据偏离大小判断仓位
# - 4.下单，下单量由冰山委托决定，按照对手价成交（买入用卖一价）。
# - 5.再次循环

# %%
trade_symbols = list(set(symbols)-set(['LINK','XTZ','BCH', 'ETH']))#剩余的币种
price_usdt_btc_norm_mean = price_usdt_btc_norm[trade_symbols].mean(axis=1)
e = Exchange(trade_symbols,initial_balance=10000,commission=0.0005,log=False)
trade_value = 300
for row in price_usdt.iloc[:].iterrows():
    e.Update(row[0], row[1])
    empty_value = 0
    for symbol in trade_symbols:
        price = row[1][symbol]
        if np.isnan(price):
            continue
        diff = price_usdt_btc_norm.loc[row[0],symbol] - price_usdt_btc_norm_mean[row[0]]
        aim_value = -trade_value*round(diff/0.01,1)
        now_value = e.account[symbol]['value']*np.sign(e.account[symbol]['amount'])
        empty_value += now_value
        if aim_value - now_value > 20:
            e.Buy(symbol, price, round((aim_value - now_value)/price, 6),round(e.account[symbol]['realised_profit']+e.account[symbol]['unrealised_profit'],2))
        if aim_value - now_value < -20:
            e.Sell(symbol, price, -round((aim_value - now_value)/price, 6),round(e.account[symbol]['realised_profit']+e.account[symbol]['unrealised_profit'],2))
stragey_2b = e
(stragey_2b.df['total']/stragey_2b.initial_balance).plot(figsize=(17,6),grid = True);

# %%
stragey_2b.df['leverage'].plot(figsize=(18,6),grid = True); #杠杆

# %%
pd.DataFrame(e.account).T.apply(lambda x:round(x,3)) #持仓

# %% [markdown]
# ## 为什么要改进
# 
# 原有最大的问题是最新价格和策略启动的初始价格对比，随着时间的增长，会越来越偏离，我们将会在这些币种上累计非常多的仓位。过滤币种最大的问题是我们根据以往的经验而未来仍然可能出现特特立独行的币种。下面就是不过滤的表现，实际上在trade_value=300时，策略中期已经爆仓，即使不爆仓，LINK、XTZ也分别持有了10000USDT以上的仓位，实在过于大了。因此必须在回测中解决这个问题，通过全币种的考验。

# %%
trade_symbols = list(set(symbols))#剩余的币种
price_usdt_btc_norm_mean = price_usdt_btc_norm[trade_symbols].mean(axis=1)
e = Exchange(trade_symbols,initial_balance=10000,commission=0.0005,log=False)
trade_value = 300
for row in price_usdt.iloc[:].iterrows():
    e.Update(row[0], row[1])
    empty_value = 0
    for symbol in trade_symbols:
        price = row[1][symbol]
        if np.isnan(price):
            continue
        diff = price_usdt_btc_norm.loc[row[0],symbol] - price_usdt_btc_norm_mean[row[0]]
        aim_value = -trade_value*round(diff/0.01,1)
        now_value = e.account[symbol]['value']*np.sign(e.account[symbol]['amount'])
        empty_value += now_value
        if aim_value - now_value > 20:
            e.Buy(symbol, price, round((aim_value - now_value)/price, 6),round(e.account[symbol]['realised_profit']+e.account[symbol]['unrealised_profit'],2))
        if aim_value - now_value < -20:
            e.Sell(symbol, price, -round((aim_value - now_value)/price, 6),round(e.account[symbol]['realised_profit']+e.account[symbol]['unrealised_profit'],2))
stragey_2c = e
(stragey_2c.df['total']/stragey_2c.initial_balance).plot(figsize=(17,6),grid = True);

# %%
pd.DataFrame(stragey_2c.account).T.apply(lambda x:round(x,3)) #最后持仓

# %%
((price_usdt_btc_norm.iloc[-1:] - price_usdt_btc_norm_mean[-1]).T) #各个币种偏离初始的情况

# %% [markdown]
# 既然问题的原因是和开始的价格进行比较，可能越偏越多。我们可以和过去一段时间的均线对比，回测全币种以下看看结果。

# %%
Alpha = 0.05
#price_usdt_btc_norm2 = price_usdt_btc/price_usdt_btc.rolling(20).mean() #普通均线
price_usdt_btc_norm2 = price_usdt_btc/price_usdt_btc.ewm(alpha=Alpha).mean() #这里和策略一致，用了EMA
trade_symbols = list(set(symbols))#全币种
price_usdt_btc_norm_mean = price_usdt_btc_norm2[trade_symbols].mean(axis=1)
e = Exchange(trade_symbols,initial_balance=10000,commission=0.0005,log=False)
trade_value = 300
for row in price_usdt.iloc[:].iterrows():
    e.Update(row[0], row[1])
    empty_value = 0
    for symbol in trade_symbols:
        price = row[1][symbol]
        if np.isnan(price):
            continue
        diff = price_usdt_btc_norm2.loc[row[0],symbol] - price_usdt_btc_norm_mean[row[0]]
        aim_value = -trade_value*round(diff/0.01,1)
        now_value = e.account[symbol]['value']*np.sign(e.account[symbol]['amount'])
        empty_value += now_value
        if aim_value - now_value > 20:
            e.Buy(symbol, price, round((aim_value - now_value)/price, 6),round(e.account[symbol]['realised_profit']+e.account[symbol]['unrealised_profit'],2))
        if aim_value - now_value < -20:
            e.Sell(symbol, price, -round((aim_value - now_value)/price, 6),round(e.account[symbol]['realised_profit']+e.account[symbol]['unrealised_profit'],2))
stragey_2d = e
#print(N,stragey_2d.df['total'][-1],pd.DataFrame(stragey_2d.account).T.apply(lambda x:round(x,3))['value'].sum())

# %% [markdown]
# 策略表现完全达到了我们的预期，收益相差无几，在全币种原策略爆仓的局面也平滑过渡了，几乎没回撤，同样的开仓大小，杠杆几乎都在1倍以下，3.12暴跌的极端情况下也没超过4倍，这意味着我们可以加大trade_value，在同样的杠杆下，将收益再提高一倍。最终的持仓只有BCH超过1000USDT，十分良好。
# 
# 为什么会降低了持仓，想象以下加入山寨币指数不变，一个币涨了100%，而且长期维持，原策略会长期持有300\*100 = 30000USDT的空单，而新策略会最终将基准价格追踪到最新价，最后会不持仓，

# %%
(stragey_2d.df['total']/stragey_2d.initial_balance).plot(figsize=(17,6),grid = True);
#(stragey_2c.df['total']/stragey_2c.initial_balance).plot(figsize=(17,6),grid = True);

# %%
stragey_2d.df['leverage'].plot(figsize=(18,6),grid = True);
stragey_2b.df['leverage'].plot(figsize=(18,6),grid = True); #筛选币种策略杠杆

# %%
pd.DataFrame(stragey_2d.account).T.apply(lambda x:round(x,3))

# %% [markdown]
# 有筛选币的情况会怎样，还是同样的参数，前期的收益表现更好，回撤更小，但收益稍低。因此还是推荐筛选的。

# %%
#price_usdt_btc_norm2 = price_usdt_btc/price_usdt_btc.rolling(50).mean()
price_usdt_btc_norm2 = price_usdt_btc/price_usdt_btc.ewm(alpha=0.05).mean()
trade_symbols = list(set(symbols)-set(['LINK','XTZ','BCH', 'ETH']))#剩余的币种
price_usdt_btc_norm_mean = price_usdt_btc_norm2[trade_symbols].mean(axis=1)
e = Exchange(trade_symbols,initial_balance=10000,commission=0.0005,log=False)
trade_value = 300
for row in price_usdt.iloc[:].iterrows():
    e.Update(row[0], row[1])
    empty_value = 0
    for symbol in trade_symbols:
        price = row[1][symbol]
        if np.isnan(price):
            continue
        diff = price_usdt_btc_norm2.loc[row[0],symbol] - price_usdt_btc_norm_mean[row[0]]
        aim_value = -trade_value*round(diff/0.01,1)
        now_value = e.account[symbol]['value']*np.sign(e.account[symbol]['amount'])
        empty_value += now_value
        if aim_value - now_value > 20:
            e.Buy(symbol, price, round((aim_value - now_value)/price, 6),round(e.account[symbol]['realised_profit']+e.account[symbol]['unrealised_profit'],2))
        if aim_value - now_value < -20:
            e.Sell(symbol, price, -round((aim_value - now_value)/price, 6),round(e.account[symbol]['realised_profit']+e.account[symbol]['unrealised_profit'],2))
stragey_2e = e

# %%
#(stragey_2d.df['total']/stragey_2d.initial_balance).plot(figsize=(17,6),grid = True);
(stragey_2e.df['total']/stragey_2e.initial_balance).plot(figsize=(17,6),grid = True);

# %%
stragey_2e.df['leverage'].plot(figsize=(18,6),grid = True);

# %%
pd.DataFrame(stragey_2e.account).T.apply(lambda x:round(x,3))

# %% [markdown]
# ## 参数的优化
# 
# 指数移动平局的Alpha参数，设置的越大，基准价格跟踪越敏感，交易的越少，最终持仓也会越低，降低了杠杆，但会降低收益，降低最大回撤，可以加大成交量，具体需要根据回测结果自己权衡。
# 
# 由于回测是1hK线，只能一小时更新一次，实盘可以更快的更新，需要综合权衡具体设置多少。
# 
# 这是优化的结果：

# %%
for Alpha in [i/100 for i in range(1,30)]:
    #price_usdt_btc_norm2 = price_usdt_btc/price_usdt_btc.rolling(20).mean() #普通均线
    price_usdt_btc_norm2 = price_usdt_btc/price_usdt_btc.ewm(alpha=Alpha).mean() #这里和策略一致，用了EMA
    trade_symbols = list(set(symbols))#全币种
    price_usdt_btc_norm_mean = price_usdt_btc_norm2[trade_symbols].mean(axis=1)
    e = Exchange(trade_symbols,initial_balance=10000,commission=0.0005,log=False)
    trade_value = 300
    for row in price_usdt.iloc[:].iterrows():
        e.Update(row[0], row[1])
        empty_value = 0
        for symbol in trade_symbols:
            price = row[1][symbol]
            if np.isnan(price):
                continue
            diff = price_usdt_btc_norm2.loc[row[0],symbol] - price_usdt_btc_norm_mean[row[0]]
            aim_value = -trade_value*round(diff/0.01,1)
            now_value = e.account[symbol]['value']*np.sign(e.account[symbol]['amount'])
            empty_value += now_value
            if aim_value - now_value > 20:
                e.Buy(symbol, price, round((aim_value - now_value)/price, 6),round(e.account[symbol]['realised_profit']+e.account[symbol]['unrealised_profit'],2))
            if aim_value - now_value < -20:
                e.Sell(symbol, price, -round((aim_value - now_value)/price, 6),round(e.account[symbol]['realised_profit']+e.account[symbol]['unrealised_profit'],2))
    stragey_2d = e
    # 分别是最终净值，初始最大回测，最终持仓大小,手续费
    print(Alpha, round(stragey_2d.account['USDT']['total'],1), round(1-stragey_2d.df['total'].min()/stragey_2d.initial_balance,2),round(pd.DataFrame(stragey_2d.account).T['value'].sum(),1),round(stragey_2d.account['USDT']['fee']))

# %%



