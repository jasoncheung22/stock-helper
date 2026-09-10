import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta_classic as ta
import json
import requests
from datetime import datetime, date

def get_nasdaq100_tickers():
    return ["AAPL", "ABNB", "ADBE", "ADI", "ADP", "ADSK", "AEP", "ALGN", "ALNY", "AMAT", "AMD", "AMGN", "AMZN", "ASML", "AVGO", "AZN", "BKNG", "BKR", "CCEP", "CDNS", "CEG", "CHTR", "CMCSA", "COST", "CPRT", "CRWD", "CSCO", "CSGP", "CSX", "CTAS", "CTSH", "DASH", "DDOG", "DLTR", "DXCM", "EA", "EBAY", "ENPH", "EXC", "FANG", "FAST", "FER", "FTNT", "GEHC", "GILD", "GOOG", "GOOGL", "HON", "IDXX", "ILMN", "INSM", "INTC", "INTU", "ISRG", "KDP", "KHC", "KLAC", "LRCX", "MAR", "MCHP", "MDLZ", "MELI", "META", "MNST", "MPWR", "MRNA", "MRVL", "MSFT", "MU", "NFLX", "NTES", "NVDA", "NXPI", "ODFL", "ORLY", "PANW", "PAYX", "PCAR", "PDD", "PEP", "PYPL", "QCOM", "REGN", "ROP", "ROST", "SBUX", "SIRI", "SNPS", "STX", "TEAM", "TMUS", "TSLA", "TTWO", "TXN", "VRSK", "VRTX", "WBD", "WDC", "WDAY", "XEL", "ZS"]

def get_dow30_tickers():
    return ["AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS", "DOW", "GS", "HD", "HON", "IBM", "INTC", "JNJ", "JPM", "KO", "MCD", "MMM", "MRK", "MSFT", "NKE", "PG", "TRV", "UNH", "V", "VZ", "WMT"]

def get_curated_tickers():
    return ["AAPL", "NVDA", "TSLA", "AMD", "AVGO", "MSFT", "AMZN", "META", "GOOGL", "PLTR", "COIN", "SMCI", "ARM", "NFLX", "UBER", "CRWD", "PANW", "QCOM", "MU", "INTC"]

# ==========================================
# 核心邏輯 (從原本的 main.py 搬過來)
# ==========================================

@st.cache_data(ttl=3600)
def fetch_and_calculate_data(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        
        # 獲取最近 6 個月的股票數據
        df = ticker.history(period="6mo")
        if df.empty:
            return None
            
        # 1. 技術指標運算 (新增 ATR 真實波動幅度)
        df.ta.rsi(length=14, append=True)
        df.ta.macd(append=True)
        df.ta.ema(length=20, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.ema(length=100, append=True)
        df.ta.bbands(length=20, append=True)
        df.ta.atr(length=14, append=True) # <-- 新增 ATR 指標
        
        # 計算 20 日平均成交量
        df['Vol_MA20'] = df['Volume'].rolling(window=20).mean()
        df.dropna(inplace=True)
        
        if df.empty:
            return None
            
        latest_data = df.iloc[-1]
        
        # 提取數值工具函數
        get_val = lambda col: round(float(latest_data[col].iloc[0] if isinstance(latest_data[col], pd.Series) else latest_data[col]), 2)
        get_int = lambda col: int(latest_data[col].iloc[0] if isinstance(latest_data[col], pd.Series) else latest_data[col])
        
        close_price = get_val('Close')
        volume = get_int('Volume')
        vol_ma20 = get_val('Vol_MA20')
        atr_14 = get_val('ATRr_14') # <-- 獲取最新 ATR
        
        ema20 = get_val('EMA_20')
        ema50 = get_val('EMA_50')
        ema100 = get_val('EMA_100')
        
        is_ema_bullish = close_price > ema20 > ema50 > ema100
        is_volume_surging = volume > (vol_ma20 * 1.2)
        avg_daily_turnover_usd = vol_ma20 * close_price

        # 2. 基本面數據提取 (Fundamentals)
        try:
            info = ticker.info
            sector = info.get('sector', 'N/A')
            forward_pe = info.get('forwardPE', 'N/A')
            if isinstance(forward_pe, (int, float)):
                forward_pe = round(forward_pe, 2)
            market_cap_b = round(info.get('marketCap', 0) / 1e9, 2) # 轉換為十億美元 (Billion)
            current_price = info.get('currentPrice', close_price)
            previous_close = info.get('previousClose', round(float(df.iloc[-2]['Close']), 2) if len(df) > 1 else close_price)
        except:
            sector, forward_pe, market_cap_b = 'N/A', 'N/A', 'N/A'
            current_price = close_price
            previous_close = round(float(df.iloc[-2]['Close']), 2) if len(df) > 1 else close_price
        
        # 3. 【全新升級】本地端期權大鯨異動 (Call + Put 雙向監測)
        whale_activity = "未監測到異常大單 (Normal Flow)"
        try:
            options_dates = ticker.options
            if options_dates:
                near_date = options_dates[0] 
                opt_chain = ticker.option_chain(near_date)
                calls = opt_chain.calls
                puts = opt_chain.puts
                
                # 計算 PCR (Put/Call Volume Ratio) - 衡量市場恐慌情緒
                total_call_vol = calls['volume'].sum() if not calls.empty else 1
                total_put_vol = puts['volume'].sum() if not puts.empty else 0
                pcr = round(total_put_vol / total_call_vol, 2) if total_call_vol > 0 else "N/A"
                
                # 合併篩選大鯨魚 (Call 與 Put 一起抓)
                unusual_calls = calls[(calls['volume'] > calls['openInterest']) & (calls['volume'] > 1000)].copy()
                unusual_puts = puts[(puts['volume'] > puts['openInterest']) & (puts['volume'] > 1000)].copy()
                
                if not unusual_calls.empty or not unusual_puts.empty:
                    if not unusual_calls.empty: unusual_calls['type'] = 'Call (看漲)'
                    if not unusual_puts.empty: unusual_puts['type'] = 'Put (看跌/避險)'
                    
                    all_unusual = pd.concat([unusual_calls, unusual_puts])
                    # 找出當天成交量最誇張的那一口合約
                    top_whale = all_unusual.sort_values(by='volume', ascending=False).iloc[0]
                    whale_activity = f"🚨 發現大鯨！到期日: {near_date} | 行權價: ${top_whale['strike']} {top_whale['type']} | 今日成交: {int(top_whale['volume'])}口 > 未平倉: {int(top_whale['openInterest'])}口 (PCR比率: {pcr})"
                else:
                    whale_activity = f"期權流穩健 (當日短線 Put/Call Ratio: {pcr})"
        except Exception as opt_e:
            whale_activity = f"期權數據暫缺"

        # 4. 封裝市場數據 (增加給 AI 的決策參數)
        market_facts = {
            "Ticker": ticker_symbol.upper(),
            "Date": latest_data.name.strftime("%Y-%m-%d"),
            "Sector": sector,                      # <-- 新增板塊
            "Market_Cap_Billion": market_cap_b,    # <-- 新增市值
            "Forward_PE": forward_pe,              # <-- 新增前瞻本益比
            "Close_Price": previous_close,
            "Current_Price": current_price,
            "Volume": volume,
            "Avg_Volume_20D": int(vol_ma20),
            "Volume_Surge": "Yes" if is_volume_surging else "No",
            "Avg_Daily_Turnover_USD": f"{round(avg_daily_turnover_usd / 1000000, 2)}M",
            "ATR_14": atr_14,                      # <-- 新增 ATR，用於精確計算止損
            "RSI_14": get_val('RSI_14'),
            "MACD_Histogram": get_val('MACDh_12_26_9'),
            "MACD_Trend": "Golden Cross" if get_val('MACDh_12_26_9') > 0 else "Death Cross",
            "EMA_Alignment": "Bullish (多頭排列)" if is_ema_bullish else "Neutral/Bearish (非多頭)",
            "BB_Upper": get_val('BBU_20_2.0'),
            "BB_Lower": get_val('BBL_20_2.0'),
            "Options_Whale_Activity": whale_activity,
            "Raw_Turnover": avg_daily_turnover_usd
        }
        return market_facts
    except Exception as e:
        return {"Error": f"Error fetching data for {ticker_symbol}: {e}"}

SECTOR_ETF_MAP = {
    'Technology': 'XLK',
    'Financial Services': 'XLF',
    'Healthcare': 'XLV',
    'Consumer Cyclical': 'XLY',
    'Consumer Defensive': 'XLP',
    'Energy': 'XLE',
    'Industrials': 'XLI',
    'Communication Services': 'XLC',
    'Utilities': 'XLU',
    'Real Estate': 'XLRE',
    'Basic Materials': 'XLB'
}

@st.cache_data(ttl=1800)
def fetch_sector_etfs_data():
    etf_tickers = list(SECTOR_ETF_MAP.values()) + ['SPY']
    try:
        data = yf.download(etf_tickers, period="30d", progress=False)
        if data.empty:
            return {}
        result = {}
        for sym in etf_tickers:
            try:
                close_s = data['Close'][sym].dropna()
                vol_s = data['Volume'][sym].dropna()
                if len(close_s) >= 2:
                    today_close = float(close_s.iloc[-1])
                    prev_close = float(close_s.iloc[-2])
                    chg_pct = round((today_close - prev_close) / prev_close * 100, 2)
                    today_vol = float(vol_s.iloc[-1])
                    vol_ma20 = float(vol_s.tail(20).mean())
                    vol_ratio = round(today_vol / vol_ma20, 2) if vol_ma20 > 0 else 1.0
                    ret_20d = round((today_close - float(close_s.iloc[0])) / float(close_s.iloc[0]) * 100, 2)
                    result[sym] = {
                        "change_pct": chg_pct,
                        "vol_ratio": vol_ratio,
                        "return_20d": ret_20d,
                        "is_surging": chg_pct > 0 and vol_ratio >= 1.2
                    }
            except Exception:
                continue
        return result
    except Exception as e:
        return {}

@st.cache_data(ttl=3600)
def fetch_late_day_surge(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="5d", interval="5m")
        if df.empty:
            return None
        
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC').tz_convert('America/New_York')
        else:
            df.index = df.index.tz_convert('America/New_York')
            
        df['Date'] = df.index.date
        dates = df['Date'].unique()
        if len(dates) < 1:
            return None
            
        target_date = dates[-1]
        day_df = df[df['Date'] == target_date]
        
        # 若最後一筆不到 15:30，取前一天
        if day_df.index[-1].time() < pd.to_datetime("15:30").time() and len(dates) > 1:
            target_date = dates[-2]
            day_df = df[df['Date'] == target_date]
            
        avg_vol = day_df['Volume'].mean()
        late_day_df = day_df.between_time("15:30", "16:00")
        
        if late_day_df.empty:
            return None
            
        max_vol_row = late_day_df.loc[late_day_df['Volume'].idxmax()]
        max_vol = max_vol_row['Volume']
        surge_multiplier = max_vol / avg_vol if avg_vol > 0 else 0
        direction = "Buy (買盤)" if max_vol_row['Close'] >= max_vol_row['Open'] else "Sell (賣盤)"
        
        # 量化升級指標
        bar_range = max_vol_row['High'] - max_vol_row['Low']
        surge_clv = round((max_vol_row['Close'] - max_vol_row['Low']) / bar_range, 2) if bar_range > 0 else 0.5
        surge_turnover_m = round(float(max_vol * max_vol_row['Close'] / 1e6), 2)
        
        # 獲取日線支撐位 (EMA20)
        daily_df = ticker.history(period="2mo")
        daily_ema20 = 0.0
        is_above_ema20 = False
        if not daily_df.empty and len(daily_df) >= 20:
            daily_df.ta.ema(length=20, append=True)
            daily_ema20 = round(float(daily_df['EMA_20'].iloc[-1]), 2)
            is_above_ema20 = max_vol_row['Close'] >= daily_ema20
            
        # 實戰防錯校驗
        if direction == "Buy (買盤)":
            if surge_clv >= 0.7 and is_above_ema20:
                quality_check = "🟢 強勢真搶籌 (高位收盤+站穩EMA20)"
            elif not is_above_ema20:
                quality_check = "⚠️ 弱勢超跌反彈 (低於EMA20，防接飛刀)"
            else:
                quality_check = "🟡 衝高回落 (CLV偏低，防誘多砸盤)"
        else:
            quality_check = "🔴 機構大額拋壓 (出貨砸盤/防守失敗)"

        try:
            info = ticker.info
            sector = info.get('sector', 'N/A')
            market_cap_b = round(info.get('marketCap', 0) / 1e9, 2)
            current_price = info.get('currentPrice', round(float(day_df.iloc[-1]['Close']), 2))
        except:
            sector, market_cap_b, current_price = 'N/A', 'N/A', round(float(day_df.iloc[-1]['Close']), 2)

        return {
            "Ticker": ticker_symbol.upper(),
            "Date": str(target_date),
            "Sector": sector,
            "Market_Cap_Billion": market_cap_b,
            "Current_Price": current_price,
            "Surge_Time": max_vol_row.name.strftime("%H:%M"),
            "Surge_Volume": int(max_vol),
            "Surge_Turnover_M": f"${surge_turnover_m}M",
            "Avg_5m_Volume": int(avg_vol),
            "Surge_Multiplier": round(surge_multiplier, 1),
            "Direction": direction,
            "Surge_CLV": surge_clv,
            "EMA20_Support": f"EMA20: ${daily_ema20} ({'守穩' if is_above_ema20 else '跌破'})",
            "Is_Above_EMA20": is_above_ema20,
            "Quality_Check": quality_check,
            "Surge_Price_Change": f"{round((max_vol_row['Close'] - max_vol_row['Open']) / max_vol_row['Open'] * 100, 2)}%"
        }
    except Exception as e:
        return {"Error": f"Error fetching {ticker_symbol}: {e}"}

@st.cache_data(ttl=3600)
def fetch_pre_surge_signals(ticker_symbol, sector_cache=None):
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="6mo")
        if df.empty or len(df) < 60:
            return None
            
        # Indicators
        df.ta.ema(length=20, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.macd(append=True)
        df.ta.bbands(length=20, append=True)
        df.ta.atr(length=14, append=True)
        df['Vol_MA20'] = df['Volume'].rolling(window=20).mean()
        df.dropna(inplace=True)
        
        if df.empty:
            return None
            
        latest = df.iloc[-1]
        
        get_val = lambda col: round(float(latest[col].iloc[0] if isinstance(latest[col], pd.Series) else latest[col]), 2)
        close_p = get_val('Close')
        open_p = get_val('Open')
        high_p = get_val('High')
        low_p = get_val('Low')
        vol = int(latest['Volume'].iloc[0] if isinstance(latest['Volume'], pd.Series) else latest['Volume'])
        vol_ma20 = get_val('Vol_MA20')
        ema20 = get_val('EMA_20')
        ema50 = get_val('EMA_50')
        macd_hist = get_val('MACDh_12_26_9')
        bbu = get_val('BBU_20_2.0')
        bbl = get_val('BBL_20_2.0')
        bbm = get_val('BBM_20_2.0')
        atr14 = get_val('ATRr_14')
        
        try:
            info = ticker.info
            sector = info.get('sector', 'N/A')
            forward_pe = info.get('forwardPE', 'N/A')
            if isinstance(forward_pe, (int, float)):
                forward_pe = round(forward_pe, 2)
            market_cap_b = round(info.get('marketCap', 0) / 1e9, 2)
        except Exception:
            sector, forward_pe, market_cap_b = 'N/A', 'N/A', 'N/A'
            
        # 1. 籌碼面: 末日大鯨魚異常建倉
        dim1_triggered = False
        dim1_detail = "無短線鯨魚"
        whale_vol_oi = 0.0
        whale_contract = "N/A"
        pcr_val = "N/A"
        try:
            opts = ticker.options
            if opts:
                near_exp_str = opts[0]
                exp_date = datetime.strptime(near_exp_str, "%Y-%m-%d").date()
                days_to_exp = (exp_date - date.today()).days
                
                if days_to_exp <= 7:
                    chain = ticker.option_chain(near_exp_str)
                    calls = chain.calls
                    puts = chain.puts
                    
                    tot_call_vol = calls['volume'].sum() if not calls.empty else 1
                    tot_put_vol = puts['volume'].sum() if not puts.empty else 0
                    pcr = round(tot_put_vol / tot_call_vol, 2) if tot_call_vol > 0 else 999.0
                    pcr_val = pcr
                    
                    unusual_c = calls[(calls['volume'] >= 2.0 * calls['openInterest']) & (calls['volume'] >= 500) & (calls['openInterest'] > 0)].copy()
                    if not unusual_c.empty:
                        top_call = unusual_c.sort_values(by='volume', ascending=False).iloc[0]
                        whale_vol_oi = round(float(top_call['volume'] / top_call['openInterest']), 2)
                        whale_contract = f"${top_call['strike']} Call (Vol:{int(top_call['volume'])}, OI:{int(top_call['openInterest'])})"
                        if pcr < 0.6:
                            dim1_triggered = True
                            dim1_detail = f"🚨 末日鯨買入 {whale_contract} [Vol/OI:{whale_vol_oi}, PCR:{pcr}]"
                        else:
                            dim1_detail = f"有大單但 PCR={pcr} (未達<0.6)"
                    else:
                        dim1_detail = f"無突破合約 (PCR:{pcr})"
        except Exception as e:
            dim1_detail = f"期權獲取失敗: {e}"
            
        # 防錯：3日內財報
        earnings_warning = False
        earnings_msg = "正常"
        try:
            cal = ticker.calendar
            if cal is not None and 'Earnings Date' in cal:
                e_dates = cal['Earnings Date']
                if isinstance(e_dates, list) and len(e_dates) > 0:
                    next_e = e_dates[0]
                    if isinstance(next_e, datetime):
                        next_e = next_e.date()
                    d_to_e = (next_e - date.today()).days
                    if 0 <= d_to_e <= 3:
                        earnings_warning = True
                        earnings_msg = f"⚠️ 3日內財報({next_e}, 距{d_to_e}天)，防跨式雙買假訊號！"
        except Exception:
            pass
            
        # 2. 量價面: 賣壓枯竭與尾盤搶籌
        vol_ratio = round(vol / vol_ma20, 2) if vol_ma20 > 0 else 1.0
        range_hl = high_p - low_p
        clv = round((close_p - low_p) / range_hl, 2) if range_hl > 0 else 0.5
        
        dim2_triggered = False
        dim2_warning = ""
        if vol_ratio < 0.40 and clv >= 0.8:
            dim2_triggered = True
            if close_p < ema20 and close_p < ema50:
                dim2_warning = "⚠️ 量縮破底陰跌，非有效防守！"
            else:
                dim2_warning = "✅ 站穩關鍵支撐之上"
        dim2_detail = f"量比: {vol_ratio}x (門檻<0.4x), CLV: {clv} (門檻≥0.8)"
        
        # 3. 波動率: 布林通道極限壓縮
        bbw = round((bbu - bbl) / bbm, 4) if bbm > 0 else 1.0
        past_60_atr = df['ATRr_14'].tail(60)
        atr_pctile = round(float((past_60_atr <= atr14).mean() * 100), 1)
        
        dim3_triggered = False
        dim3_warning = ""
        if bbw <= 0.06 and atr_pctile <= 10.0:
            dim3_triggered = True
            if macd_hist > 0 or close_p >= bbm:
                dim3_warning = "✅ 右側訊號已翻正/站上中軌"
            else:
                dim3_warning = "⚠️ 波動極致收縮但方向未明(MACD綠柱)，防向下破位！"
        dim3_detail = f"BBW: {bbw} (門檻≤0.06), ATR分位: {atr_pctile}% (門檻≤10%)"
        
        # 4. 支撐面: 假跌破與主力洗盤
        lower_shadow = round(min(open_p, close_p) - low_p, 2)
        body = round(abs(close_p - open_p), 2)
        body_eff = max(body, 0.05)
        shadow_ratio = round(lower_shadow / body_eff, 1)
        
        dim4_triggered = False
        dim4_warning = ""
        if low_p < ema20 and close_p > ema20 and (lower_shadow >= body * 2 or (body < 0.1 and lower_shadow > 0.5)):
            dim4_triggered = True
            dim4_warning = "✅ 假跌破探底拉回，待隔日開盤確認不破低"
        dim4_detail = f"下影線/實體比: {shadow_ratio}x, 低點${low_p} < EMA20(${ema20}) < 收盤${close_p}"
        
        # 5. 板塊面: 資金共振與補漲
        dim5_triggered = False
        dim5_warning = ""
        sector_etf = SECTOR_ETF_MAP.get(sector, 'SPY')
        etf_info = sector_cache.get(sector_etf, {}) if sector_cache else {}
        etf_chg = etf_info.get("change_pct", 0.0)
        etf_vol_r = etf_info.get("vol_ratio", 1.0)
        
        stock_60d_ret = round((close_p - float(df['Close'].iloc[0])) / float(df['Close'].iloc[0]) * 100, 1)
        spy_info = sector_cache.get('SPY', {}) if sector_cache else {}
        spy_60d_ret = spy_info.get('return_20d', 0.0)
        rs_score = round(stock_60d_ret - spy_60d_ret, 1)
        
        if etf_chg > 0 and etf_vol_r >= 1.2:
            dim5_triggered = True
            if isinstance(forward_pe, (int, float)) and forward_pe > 80:
                dim5_warning = f"⚠️ 板塊共振但 Forward P/E={forward_pe} 過高，警惕補漲出貨！"
            else:
                dim5_warning = "✅ 板塊資金共振，估值合理"
        dim5_detail = f"板塊ETF({sector_etf}): 漲{etf_chg}%, 量{etf_vol_r}x, 60D超額RS: {rs_score}%"
        
        triggers = []
        if dim1_triggered: triggers.append("🐋末日鯨")
        if dim2_triggered: triggers.append("💤量縮搶籌")
        if dim3_triggered: triggers.append("🗜️布林壓縮")
        if dim4_triggered: triggers.append("🔨假跌破洗盤")
        if dim5_triggered: triggers.append("🚀板塊共振")
        
        score = len(triggers)
        
        all_warnings = []
        if earnings_warning: all_warnings.append(earnings_msg)
        if dim2_warning and "⚠️" in dim2_warning: all_warnings.append(dim2_warning)
        if dim3_warning and "⚠️" in dim3_warning: all_warnings.append(dim3_warning)
        if dim5_warning and "⚠️" in dim5_warning: all_warnings.append(dim5_warning)
        warning_str = " | ".join(all_warnings) if all_warnings else "🟢 無重大防錯異常"
        
        return {
            "Ticker": ticker_symbol.upper(),
            "Score": score,
            "Score_Stars": "⭐" * score if score > 0 else "－",
            "Triggers": " ".join(triggers) if triggers else "無",
            "Price": close_p,
            "Sector": sector,
            "Market_Cap_B": market_cap_b,
            "Fwd_PE": forward_pe,
            "Dim1_Options": dim1_detail,
            "Dim1_Triggered": dim1_triggered,
            "Dim2_Volume": dim2_detail,
            "Dim2_Triggered": dim2_triggered,
            "Dim3_Volatility": dim3_detail,
            "Dim3_Triggered": dim3_triggered,
            "Dim4_Support": dim4_detail,
            "Dim4_Triggered": dim4_triggered,
            "Dim5_Sector": dim5_detail,
            "Dim5_Triggered": dim5_triggered,
            "Earnings_Warning": earnings_warning,
            "Warnings": warning_str
        }
    except Exception as e:
        return {"Error": f"{ticker_symbol}: {e}"}

@st.cache_data(ttl=86400)
def backtest_late_day_surge(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="60d", interval="5m")
        if df.empty:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC').tz_convert('US/Eastern')
        else:
            df.index = df.index.tz_convert('US/Eastern')
            
        df['Date'] = df.index.date
        df['Time'] = df.index.time
        
        daily_groups = df.groupby('Date')
        dates = list(daily_groups.groups.keys())
        
        results = []
        for i in range(len(dates) - 1):
            current_date = dates[i]
            next_date = dates[i+1]
            
            current_df = daily_groups.get_group(current_date)
            next_df = daily_groups.get_group(next_date)
            
            avg_vol = current_df['Volume'].mean()
            
            late_df = current_df[(current_df.index.hour == 15) & (current_df.index.minute >= 30)]
            if late_df.empty:
                continue
                
            max_vol = late_df['Volume'].max()
            max_vol_bar = late_df[late_df['Volume'] == max_vol].iloc[0]
            surge_mult = max_vol / avg_vol if avg_vol > 0 else 0
            
            if surge_mult >= 2.5:
                window_open = late_df['Open'].iloc[0]
                window_close = late_df['Close'].iloc[-1]
                
                surge_type = "Buy (買盤)" if window_close >= window_open else "Sell (賣盤)"
                
                current_close = current_df['Close'].iloc[-1]
                next_open = next_df['Open'].iloc[0]
                next_close = next_df['Close'].iloc[-1]
                
                open_return = (next_open - current_close) / current_close * 100
                close_return = (next_close - current_close) / current_close * 100
                
                results.append({
                    "Date": current_date,
                    "Type": surge_type,
                    "Multiplier": surge_mult,
                    "Next_Open_Return": open_return,
                    "Next_Close_Return": close_return
                })
        return results
    except Exception as e:
        return {"Error": f"Error backtesting {ticker_symbol}: {e}"}

def generate_ai_prompt(mode, data_payload):
    system_prompt = """
    你是一個資深的股票經紀與量化分析師。你不允許股價有任何一絲差錯。
    請根據使用者提供的【絕對市場數據】進行嚴格的量化分析，禁止捏造、估算或竄改任何數值。
    """
    
    if mode == 1:
        user_prompt = f"""
        【模式：1️⃣ 潛力美股單股深度分析】
        請根據下方 JSON 數據，生成一份極簡的 Markdown 報告。
        必須包含：潛力爆發分數(1-100)、基本面與催化劑、技術指標狀態、期權大鯨異動解析、操作建議（買入區/目標價/止損價/風報比）。
        
        【絕對市場數據】：
        {json.dumps(data_payload, indent=2, ensure_ascii=False)}
        """
    elif mode == 2:
        user_prompt = f"""
        【模式：2️⃣ Top 5 潛力美股雷達全市場掃描】
        請根據下方由 Python 篩選並提供的前 5 名潛力股 JSON 數據，生成匯總排名的 Markdown 表格。
        必須包含欄位：排名、股票代號、潛力分數、技術指標與觸發信號、期權大鯨異動、基本面與催化劑、操作建議。
        
        【Top 5 絕對市場數據清單】：
        {json.dumps(data_payload, indent=2, ensure_ascii=False)}
        """
    elif mode == 3:
        user_prompt = f"""
        【模式：3️⃣ 收市前大額買賣異動分析 (量化加強版)】
        請根據下方由 Python 篩選並提供的前一日（或最近交易日）收市前發生大額買賣異動的股票數據（包含 5分鐘爆發倍數、Close Location Value 收盤位置、成交金額 $M、EMA20 支撐狀態與質量審查結果），生成一份重點解析報告。
        請深入指出這些大額買賣可能代表的機構意圖（例如：尾盤頂部收盤真搶籌、逢高出貨砸盤、或是無支撐超跌抽頭），並針對這幾檔股票給出精準的隔日操作策略與止損位置。
        
        【尾盤量化異動數據清單】：
        {json.dumps(data_payload, indent=2, ensure_ascii=False)}
        """
    elif mode == 5:
        user_prompt = f"""
        【模式：5️⃣ 暴漲先期訊號多維量化深度診斷與主力意圖審查】
        請根據下方由 Python 嚴格篩選出的潛力股票數據（涵蓋 籌碼面/量價面/波動率/支撐面/板塊面 5 大維度指標與防錯機制檢核結果），
        生成一份專業機構級別的 Markdown 操盤診斷報告。
        
        報告必須包含：
        1. 【綜合爆發潛力排名與評級】：依據觸發訊號維度數與防錯安全度給出評級 (S/A/B/C)。
        2. 【主力操盤意圖拆解】：剖析大鯨魚末日期權、極致量縮尾盤搶籌、假跌破洗盤等動作背後的莊家籌碼動態。
        3. 【防錯機制覆核 (False Signal Check)】：逐一審核 3日內財報陷阱、破底陰跌風險、波動率無方向收斂及高估值補漲誘多風險。
        4. 【具體右側進場點位與風控指引】：精確給出右側確認條件、買入區間、停損點（如跌破下影線低點或EMA20）、第一目標價與風險報酬比 (R:R)。

        【暴漲先期量化市場數據清單】：
        {json.dumps(data_payload, indent=2, ensure_ascii=False)}
        """
    else:
        user_prompt = f"""
        【通用市場數據分析報告】：
        {json.dumps(data_payload, indent=2, ensure_ascii=False)}
        """
        
    return system_prompt.strip() + "\n\n" + user_prompt.strip()


# ==========================================
# Streamlit 網頁介面
# ==========================================

st.set_page_config(page_title="AI 股票量化分析 Prompt 產生器", page_icon="📈", layout="wide")

st.title("📈 AI 股票量化分析 Prompt 產生器")
st.markdown("這個工具可以幫你自動抓取最新的美股數據、計算技術指標 (RSI, MACD, 均線)，並產生可直接丟給 ChatGPT / Gemini 的精確 Prompt！")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["1️⃣ 單股深度分析", "2️⃣ Top 5 雷達掃描", "3️⃣ 收市前大額買賣 (量化加強版)", "4️⃣ 尾盤異動歷史回測", "5️⃣ 🚀 暴漲先期訊號多維量化掃描"])

# --- Mode 1: 單股深度分析 ---
with tab1:
    st.header("單一股票深度分析")
    col1, col2 = st.columns([1, 3])
    with col1:
        single_ticker = st.text_input("請輸入單一股票代號", value="AAPL", max_chars=10).upper()
        btn_mode1 = st.button("產生 Prompt", type="primary", key="btn1")
        
    if btn_mode1:
        with st.spinner(f"正在擷取 {single_ticker} 最新收盤數據與期權鏈..."):
            facts = fetch_and_calculate_data(single_ticker)
            
            if facts and "Error" not in facts:
                # 移除內部運算參數
                facts.pop("Raw_Turnover", None)
                
                prompt = generate_ai_prompt(1, facts)
                st.success("數據準備完畢！請點擊下方代碼框右上角的「拷貝」按鈕，並貼給 AI。")
                st.code(prompt, language="markdown")
            elif facts and "Error" in facts:
                st.error(facts["Error"])
            else:
                st.error(f"獲取 {single_ticker} 數據失敗，請檢查網路或股票代號是否有誤。")

# --- Mode 2: 雷達掃描 ---
with tab2:
    st.header("Top 5 潛力股雷達掃描")
    st.markdown("程式會自動計算所有列表中的股票，並過濾出 **日均成交額 > 4億** 且 **MACD金叉** 且 **均線多頭排列** 的股票，列出最強的前五名。")
    
    scan_scope_2 = st.radio("請選擇掃描範圍 (掃描全市場需要約 1~2 分鐘，請耐心等候)：", 
                          options=["🔥 NASDAQ 100 + Dow 30 (綜合掃描)", "✍️ 自訂觀察清單"],
                          index=0, horizontal=True, key="scope_2")
                          
    if scan_scope_2 == "✍️ 自訂觀察清單":
        default_watchlist_2 = "AAPL, NVDA, TSLA, AMD, AVGO, MSFT, AMZN, PLTR, SNOW, META"
        watchlist_input_2 = st.text_area("請輸入觀察清單 (用逗號分隔)", value=default_watchlist_2, height=100, key="wl2")
    else:
        watchlist_input_2 = ""
        
    btn_mode2 = st.button("🚀 開始全範圍掃描並產生 Prompt", type="primary", key="btn2")
    
    if btn_mode2:
        if scan_scope_2 == "🔥 NASDAQ 100 + Dow 30 (綜合掃描)":
            watch_list = list(set(get_nasdaq100_tickers() + get_dow30_tickers()))
        else:
            watch_list = [x.strip().upper() for x in watchlist_input_2.split(",") if x.strip()]
        
        if not watch_list:
            st.warning("請至少輸入一檔股票代號！")
        else:
            all_calculated_stocks = []
            
            # 使用進度條
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for i, ticker in enumerate(watch_list):
                status_text.text(f"正在擷取 {ticker} ({i+1}/{len(watch_list)})...")
                facts = fetch_and_calculate_data(ticker)
                if facts and "Error" not in facts:
                    all_calculated_stocks.append(facts)
                progress_bar.progress((i + 1) / len(watch_list))
                
            status_text.text("篩選與排序中...")
            
            filtered_stocks = [
                s for s in all_calculated_stocks 
                if s.get("Raw_Turnover", 0) >= 400000000 
                and s.get("MACD_Trend") == "Golden Cross" 
                and "Bullish" in s.get("EMA_Alignment", "")
            ]
            
            top_5_stocks = sorted(filtered_stocks, key=lambda x: x.get("MACD_Histogram", 0), reverse=True)[:5]
            
            # 清除不需要顯示給 AI 的原始成交額數據
            for s in top_5_stocks: 
                s.pop("Raw_Turnover", None)
                
            status_text.empty()
            progress_bar.empty()
            
            if top_5_stocks:
                prompt = generate_ai_prompt(2, top_5_stocks)
                st.success(f"掃描完成！從 {len(watch_list)} 檔中篩選出 {len(top_5_stocks)} 檔符合條件的潛力股。請點擊複製並貼給 AI。")
                st.code(prompt, language="markdown")
            else:
                st.warning("當前觀察清單中沒有股票完全符合「日均成交額>4億 + MACD金叉 + 均線多頭排列」的硬性篩選條件！")

# --- Mode 3: 收市前大額買賣掃描 (量化加強版) ---
with tab3:
    st.header("收市前大額買賣 (尾盤異動) 量化加強掃描")
    st.markdown("掃描最近一個交易日 **15:30 - 16:00 (美東時間)** 之間的 5 分鐘 K 線，結合 **成交量倍數、收盤位置 (CLV)、EMA20 關鍵支撐狀態與質量審查**，精準過濾機構主力真搶籌與假誘多。")
    
    col_scope, col_filter = st.columns([1, 1])
    with col_scope:
        scan_scope = st.radio("請選擇掃描範圍：", 
                              options=["⭐ 精選熱門潛力股 (快速)", "🔥 NASDAQ 100 + Dow 30 (綜合掃描)", "✍️ 自訂觀察清單"],
                              index=0, horizontal=True)
                              
        if scan_scope == "✍️ 自訂觀察清單":
            default_watchlist_3 = "AAPL, NVDA, TSLA, AMD, AVGO, MSFT, AMZN, PLTR, SNOW, META, GME, AMC"
            watchlist_input_3 = st.text_area("請輸入觀察清單 (用逗號分隔)", value=default_watchlist_3, height=80, key="wl3")
        else:
            watchlist_input_3 = ""
            
    with col_filter:
        st.markdown("**量化防錯與質量過濾條件：**")
        min_multiplier = st.slider("最低尾盤爆發倍數 (Surge Multiplier)", min_value=1.5, max_value=5.0, value=2.0, step=0.5, key="surge_mult_slider")
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            only_high_clv = st.checkbox("僅看高位收盤 (CLV ≥ 0.7，真搶籌拒絕拉高砸盤)", value=False, key="cb_clv")
            only_bullish_support = st.checkbox("僅看守穩 EMA20 支撐之上", value=False, key="cb_ema20")
        with col_c2:
            only_buy_surges = st.checkbox("僅看買盤 (Buy 綠棒)", value=True, key="cb_buy")
            min_turnover_m = st.number_input("最低 5 分鐘成交金額 ($M)", min_value=0.0, value=5.0, step=5.0, key="min_turnover")
        
    btn_mode3 = st.button("🚀 開始量化掃描並產生 Prompt", type="primary", key="btn3")
    
    if btn_mode3:
        if scan_scope == "⭐ 精選熱門潛力股 (快速)":
            watch_list_3 = get_curated_tickers()
        elif scan_scope == "🔥 NASDAQ 100 + Dow 30 (綜合掃描)":
            watch_list_3 = list(set(get_nasdaq100_tickers() + get_dow30_tickers()))
        else:
            watch_list_3 = [x.strip().upper() for x in watchlist_input_3.split(",") if x.strip()]
        
        if not watch_list_3:
            st.warning("股票清單為空！")
        else:
            all_surge_stocks = []
            progress_bar_3 = st.progress(0)
            status_text_3 = st.empty()
            
            for i, ticker in enumerate(watch_list_3):
                status_text_3.text(f"正在擷取 {ticker} 的分時數據與關鍵支撐 ({i+1}/{len(watch_list_3)})...")
                facts = fetch_late_day_surge(ticker)
                if facts and "Error" not in facts:
                    mult_ok = facts.get("Surge_Multiplier", 0) >= min_multiplier
                    clv_ok = (not only_high_clv) or (facts.get("Surge_CLV", 0) >= 0.7)
                    ema_ok = (not only_bullish_support) or facts.get("Is_Above_EMA20", False)
                    dir_ok = (not only_buy_surges) or ("Buy" in facts.get("Direction", ""))
                    turnover_val = float(facts.get("Surge_Turnover_M", "$0M").replace("$", "").replace("M", "")) if "Surge_Turnover_M" in facts else 0
                    turnover_ok = turnover_val >= min_turnover_m
                    
                    if mult_ok and clv_ok and ema_ok and dir_ok and turnover_ok:
                        all_surge_stocks.append(facts)
                progress_bar_3.progress((i + 1) / len(watch_list_3))
                
            status_text_3.text("分析完成！")
            
            top_surge_stocks = sorted(all_surge_stocks, key=lambda x: (x.get("Surge_Multiplier", 0), x.get("Surge_CLV", 0)), reverse=True)[:15]
            
            status_text_3.empty()
            progress_bar_3.empty()
            
            if top_surge_stocks:
                prompt = generate_ai_prompt(3, top_surge_stocks)
                st.success(f"掃描完成！從 {len(watch_list_3)} 檔中篩選出 {len(top_surge_stocks)} 檔通過嚴格量化條件的尾盤異動股票。請點擊複製並貼給 AI。")
                display_cols = ["Ticker", "Direction", "Quality_Check", "Surge_Multiplier", "Surge_CLV", "Surge_Turnover_M", "EMA20_Support", "Surge_Time", "Surge_Price_Change", "Current_Price"]
                df_display = pd.DataFrame(top_surge_stocks)
                rename_cols = {
                    "Ticker": "股票代號",
                    "Direction": "盤別方向",
                    "Quality_Check": "量化質量審核",
                    "Surge_Multiplier": "爆發倍數",
                    "Surge_CLV": "收盤位置(CLV)",
                    "Surge_Turnover_M": "尾盤成交額",
                    "EMA20_Support": "日線EMA20支撐",
                    "Surge_Time": "異動時間",
                    "Surge_Price_Change": "K線漲幅",
                    "Current_Price": "最新股價"
                }
                st.dataframe(df_display[[c for c in display_cols if c in df_display.columns]].rename(columns=rename_cols), use_container_width=True)
                st.subheader("📋 複製至 ChatGPT / Gemini 進行機構意圖拆解")
                st.code(prompt, language="markdown")
            else:
                st.warning(f"當前掃描範圍中沒有股票完全滿足所設定的量化過濾條件（爆發倍數 ≥ {min_multiplier}x 等）！請嘗試放寬篩選設定。")

# --- Mode 4: 尾盤異動回測分析 ---
with tab4:
    st.header("尾盤異動 (大量買/賣盤) 歷史回測分析")
    st.markdown("針對所選清單，自動抓取過去 60 天的 5 分鐘 K 線，統計尾盤大量買盤/賣盤後，隔日開盤與收盤的平均報酬率與上漲/下跌機率。")
    
    scan_scope_4 = st.radio("請選擇回測範圍 (計算時間較長，全市場約需 1~2 分鐘)：", 
                          options=["🔥 NASDAQ 100 + Dow 30 (綜合掃描)", "✍️ 自訂觀察清單"],
                          index=1, horizontal=True, key="scope_4")
                          
    if scan_scope_4 == "✍️ 自訂觀察清單":
        default_watchlist_4 = "AAPL, NVDA, TSLA, AMD, AVGO"
        watchlist_input_4 = st.text_area("請輸入觀察清單 (用逗號分隔)", value=default_watchlist_4, height=100, key="wl4")
    else:
        watchlist_input_4 = ""
        
    btn_mode4 = st.button("📊 開始歷史回測", type="primary", key="btn4")
    
    if btn_mode4:
        if scan_scope_4 == "🔥 NASDAQ 100 + Dow 30 (綜合掃描)":
            watch_list_4 = list(set(get_nasdaq100_tickers() + get_dow30_tickers()))
        else:
            watch_list_4 = [x.strip().upper() for x in watchlist_input_4.split(",") if x.strip()]
            
        if not watch_list_4:
            st.warning("股票清單為空！")
        else:
            all_results = []
            progress_bar_4 = st.progress(0)
            status_text_4 = st.empty()
            
            for i, ticker in enumerate(watch_list_4):
                status_text_4.text(f"正在回測 {ticker} ({i+1}/{len(watch_list_4)})...")
                res = backtest_late_day_surge(ticker)
                if isinstance(res, list):
                    for r in res:
                        r['Ticker'] = ticker
                        all_results.append(r)
                progress_bar_4.progress((i + 1) / len(watch_list_4))
                
            status_text_4.text("回測計算完成！")
            progress_bar_4.empty()
            
            if all_results:
                df_res = pd.DataFrame(all_results)
                
                buy_df = df_res[df_res['Type'] == 'Buy (買盤)']
                sell_df = df_res[df_res['Type'] == 'Sell (賣盤)']
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.subheader("🟢 尾盤大量買盤回測結果")
                    if not buy_df.empty:
                        total_buy = len(buy_df)
                        up_open = len(buy_df[buy_df['Next_Open_Return'] > 0])
                        up_close = len(buy_df[buy_df['Next_Close_Return'] > 0])
                        avg_open_ret = buy_df['Next_Open_Return'].mean()
                        avg_close_ret = buy_df['Next_Close_Return'].mean()
                        
                        st.metric("發生總次數", f"{total_buy} 次")
                        st.metric("隔日開盤平均報酬率", f"{avg_open_ret:.2f}%")
                        st.metric("隔日開盤上漲機率 (勝率)", f"{(up_open/total_buy)*100:.1f}%")
                        st.metric("隔日收盤平均報酬率", f"{avg_close_ret:.2f}%")
                        st.metric("隔日收盤上漲機率 (勝率)", f"{(up_close/total_buy)*100:.1f}%")
                    else:
                        st.info("過去 60 天無尾盤大量買盤紀錄。")
                        
                with col2:
                    st.subheader("🔴 尾盤大量賣盤回測結果")
                    if not sell_df.empty:
                        total_sell = len(sell_df)
                        down_open = len(sell_df[sell_df['Next_Open_Return'] < 0])
                        down_close = len(sell_df[sell_df['Next_Close_Return'] < 0])
                        avg_open_ret_s = sell_df['Next_Open_Return'].mean()
                        avg_close_ret_s = sell_df['Next_Close_Return'].mean()
                        
                        st.metric("發生總次數", f"{total_sell} 次")
                        st.metric("隔日開盤平均報酬率", f"{avg_open_ret_s:.2f}%")
                        st.metric("隔日開盤下跌機率 (勝率)", f"{(down_open/total_sell)*100:.1f}%")
                        st.metric("隔日收盤平均報酬率", f"{avg_close_ret_s:.2f}%")
                        st.metric("隔日收盤下跌機率 (勝率)", f"{(down_close/total_sell)*100:.1f}%")
                    else:
                        st.info("過去 60 天無尾盤大量賣盤紀錄。")
                        
                st.markdown("---")
                st.write("詳細異動列表：")
                st.dataframe(df_res.sort_values(by="Date", ascending=False))
            else:
                st.warning("清單中所有的股票在過去 60 天均無明顯的尾盤異動。")

# --- Mode 5: 捕捉暴漲先期訊號量化篩選總表與全市場掃描 ---
with tab5:
    st.header("🚀 捕捉暴漲先期訊號：多維量化掃描 (Screener)")
    st.markdown("依據 **籌碼面、量價面、波動率、支撐面、板塊面** 5 大訊號維度與嚴格防錯機制，掃描全市場具備爆發潛力的飆股。")

    # 1. 總表說明卡片 (可展開)
    with st.expander("📖 查看【捕捉暴漲先期訊號：量化參數篩選總表】核心量化邏輯與防錯機制", expanded=True):
        st.markdown("""
| 訊號維度 | 目標捕捉現象 | 核心量化指標 (Indicators) | 嚴格篩選參數設定 (Screener 條件) | 實戰意義與防錯機制 (False Signal Check) |
| :--- | :--- | :--- | :--- | :--- |
| **1. 籌碼面** | 末日大鯨魚異常建倉 | Vol/OI (成交/未平倉比)<br>PCR (Put/Call Ratio) | • 單一行權價 Call 成交量 > 未平倉量 (**Vol/OI ≥ 2.0**)<br>• 合約距到期日 **≤ 7 天** (0DTE - 7DTE)<br>• 當日個股總 **PCR < 0.6** | ⚠️ **防錯**：必須排除「3日內即將發布財報」的標的。財報前的異常期權通常是 Straddle (跨式) 雙買博弈，而非單向的內線逼空。 |
| **2. 量價面** | 賣壓枯竭與尾盤搶籌 | Volume Ratio (量比)<br>Close Location Value (CLV) | • 當日成交量 < 20日均量之 **40%** (Volume_Ratio < 0.4)<br>• 收盤價位置 **CLV = (收盤 - 最低) / (最高 - 最低) ≥ 0.8** | ⚠️ **防錯**：極致量縮必須伴隨「價格守在關鍵支撐 (EMA20/50) 之上」。若量縮且破底，屬於市場完全棄守的「無量陰跌」，極度危險。 |
| **3. 波動率** | 布林通道極限壓縮 | BBW (布林帶寬)<br>ATR Percentile | • **BBW = (上軌 - 下軌) / 中軌 ≤ 0.06**<br>• ATR_14 處於過去 60 個交易日的最低 **10% 分位數** | ⚠️ **防錯**：波動率收斂不帶方向性。必須等待「MACD 柱狀體翻正 (金叉)」或「突破上軌」的右側確認訊號，嚴禁在收斂期盲目重倉猜方向。 |
| **4. 支撐面** | 假跌破與主力洗盤 | Lower Shadow Ratio (下影線比)<br>EMA_20 乖離測試 | • 盤中最低價 < EMA_20，但收盤價 > EMA_20<br>• **下影線長度 ≥ (實體 K 線長度 × 2)** | ⚠️ **防錯**：隔日開盤價必須「平開或高開」。若隔日直接跳空開低並跌破該下影線的低點，代表防守徹底失敗，應即刻止損。 |
| **5. 板塊面** | 資金共振與補漲 | Relative Strength (RS)<br>Sector Beta | • 個股相較大盤 60 日具備強勁動能 (RS 領先)<br>• 該股所屬之板塊 ETF 當日上漲且 **Volume > 1.2~1.5 倍** | ⚠️ **防錯**：檢視基本面估值。若板塊暴漲但該股 Fwd P/E 已達歷史百倍天價 (>80~100)，這通常是落後補漲的「拉高出貨」，而非主升段起點。 |
        """)

    # 2. 控制面板
    c_s1, c_s2 = st.columns([1, 1])
    with c_s1:
        scan_scope_5 = st.radio("請選擇掃描範圍：", 
                                options=["⭐ 精選熱門潛力股清單 (20 檔，極速 ~10秒)", 
                                         "🔥 NASDAQ 100 + Dow 30 (綜合掃描，約 1~2 分鐘)", 
                                         "✍️ 自訂觀察清單"],
                                index=0, key="scope_5")
                                
        if scan_scope_5 == "✍️ 自訂觀察清單":
            default_watchlist_5 = "AAPL, NVDA, TSLA, AMD, AVGO, MSFT, AMZN, META, GOOGL, PLTR, COIN, SMCI, ARM, NFLX, UBER"
            watchlist_input_5 = st.text_area("請輸入觀察清單 (逗號分隔)", value=default_watchlist_5, height=80, key="wl5")
        else:
            watchlist_input_5 = ""

    with c_s2:
        st.markdown("**過濾與防錯偏好：**")
        min_score_filter = st.selectbox("最低觸發維度數量過濾：", 
                                        options=[0, 1, 2, 3], 
                                        index=0, 
                                        format_func=lambda x: "顯示全部並按潛力評分排序" if x == 0 else f"至少觸發 {x} 個訊號維度",
                                        key="min_score_5")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            filter_earnings_risk = st.checkbox("排除 3 日內即將發布財報標的 (避開財報雙買陷阱)", value=False, key="filter_earn")
        with col_f2:
            filter_downtrend = st.checkbox("排除量縮破底無量陰跌標的", value=False, key="filter_down")

    btn_mode5 = st.button("🚀 開始暴漲先期訊號量化掃描並產生 Prompt", type="primary", key="btn5")
    
    if btn_mode5:
        if scan_scope_5 == "⭐ 精選熱門潛力股清單 (20 檔，極速 ~10秒)":
            watch_list_5 = get_curated_tickers()
        elif scan_scope_5 == "🔥 NASDAQ 100 + Dow 30 (綜合掃描，約 1~2 分鐘)":
            watch_list_5 = list(set(get_nasdaq100_tickers() + get_dow30_tickers()))
        else:
            watch_list_5 = [x.strip().upper() for x in watchlist_input_5.split(",") if x.strip()]
            
        if not watch_list_5:
            st.warning("股票清單為空！")
        else:
            # 預載板塊 ETF 快照
            with st.spinner("正在預載標普 11 大板塊 ETF 與大盤 SPY 即時量價矩陣..."):
                sector_cache = fetch_sector_etfs_data()
                
            all_screener_results = []
            progress_bar_5 = st.progress(0)
            status_text_5 = st.empty()
            
            for i, ticker in enumerate(watch_list_5):
                status_text_5.text(f"正在掃描 {ticker} (籌碼/量價/波動率/支撐/板塊 5維度計算) ({i+1}/{len(watch_list_5)})...")
                res = fetch_pre_surge_signals(ticker, sector_cache)
                if res and "Error" not in res:
                    # 防錯過濾
                    if filter_earnings_risk and res.get("Earnings_Warning", False):
                        continue
                    if filter_downtrend and "無量陰跌" in res.get("Warnings", ""):
                        continue
                    if res.get("Score", 0) >= min_score_filter:
                        all_screener_results.append(res)
                progress_bar_5.progress((i + 1) / len(watch_list_5))
                
            status_text_5.text("掃描與綜合潛力排序完成！")
            progress_bar_5.empty()
            status_text_5.empty()
            
            if all_screener_results:
                # 依分數排序 (Score 高到低)
                sorted_results = sorted(all_screener_results, key=lambda x: (x.get("Score", 0), x.get("Price", 0)), reverse=True)
                
                # 統計數據卡片
                st.subheader("📊 掃描成果摘要")
                kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
                whale_count = sum(1 for r in sorted_results if r.get("Dim1_Triggered"))
                dryup_count = sum(1 for r in sorted_results if r.get("Dim2_Triggered"))
                squeeze_count = sum(1 for r in sorted_results if r.get("Dim3_Triggered"))
                washout_count = sum(1 for r in sorted_results if r.get("Dim4_Triggered"))
                sector_count = sum(1 for r in sorted_results if r.get("Dim5_Triggered"))
                
                kpi1.metric("🐋 末日鯨異常", f"{whale_count} 檔")
                kpi2.metric("💤 賣壓枯竭搶籌", f"{dryup_count} 檔")
                kpi3.metric("🗜️ 布林極限壓縮", f"{squeeze_count} 檔")
                kpi4.metric("🔨 假跌破洗盤", f"{washout_count} 檔")
                kpi5.metric("🚀 板塊資金共振", f"{sector_count} 檔")
                
                st.markdown("---")
                st.subheader(f"🎯 暴漲先期訊號篩選結果總表 (共 {len(sorted_results)} 檔)")
                
                # 表格顯示
                table_cols = [
                    "Ticker", "Score_Stars", "Triggers", "Price", "Sector", "Fwd_PE",
                    "Dim1_Options", "Dim2_Volume", "Dim3_Volatility", "Dim4_Support", "Dim5_Sector",
                    "Warnings"
                ]
                df_table = pd.DataFrame(sorted_results)
                
                # 重新命名欄位呈現更友好
                rename_map = {
                    "Ticker": "股票代號",
                    "Score_Stars": "綜合潛力",
                    "Triggers": "觸發訊號維度",
                    "Price": "最新收盤價",
                    "Sector": "所屬板塊",
                    "Fwd_PE": "前瞻本益比",
                    "Dim1_Options": "1.籌碼面 (期權鯨/PCR)",
                    "Dim2_Volume": "2.量價面 (量比/CLV)",
                    "Dim3_Volatility": "3.波動率 (BBW/ATR分位)",
                    "Dim4_Support": "4.支撐面 (EMA20洗盤/下影線)",
                    "Dim5_Sector": "5.板塊面 (板塊ETF/RS超額)",
                    "Warnings": "⚠️ 防錯機制檢核結果"
                }
                
                st.dataframe(df_table[[c for c in table_cols if c in df_table.columns]].rename(columns=rename_map), use_container_width=True)
                
                # Prompt 產出
                ai_candidates = [r for r in sorted_results if r.get("Score", 0) > 0][:8]
                if not ai_candidates:
                    ai_candidates = sorted_results[:5]
                    
                prompt_5 = generate_ai_prompt(5, ai_candidates)
                st.success(f"已生成【模式 5：暴漲先期訊號深度診斷 Prompt】！共納入 {len(ai_candidates)} 檔具備訊號之重點標的。")
                st.subheader("📋 複製至 ChatGPT / Gemini 進行主力操盤意圖審查")
                st.code(prompt_5, language="markdown")
            else:
                st.warning("所選範圍中沒有標的符合篩選條件！請嘗試放寬篩選設定。")
