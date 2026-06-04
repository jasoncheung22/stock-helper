import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta_classic as ta
import json
import requests
from datetime import datetime

def get_nasdaq100_tickers():
    return ["AAPL", "ABNB", "ADBE", "ADI", "ADP", "ADSK", "AEP", "ALGN", "ALNY", "AMAT", "AMD", "AMGN", "AMZN", "ASML", "AVGO", "AZN", "BKNG", "BKR", "CCEP", "CDNS", "CEG", "CHTR", "CMCSA", "COST", "CPRT", "CRWD", "CSCO", "CSGP", "CSX", "CTAS", "CTSH", "DASH", "DDOG", "DLTR", "DXCM", "EA", "EBAY", "ENPH", "EXC", "FANG", "FAST", "FER", "FTNT", "GEHC", "GILD", "GOOG", "GOOGL", "HON", "IDXX", "ILMN", "INSM", "INTC", "INTU", "ISRG", "KDP", "KHC", "KLAC", "LRCX", "MAR", "MCHP", "MDLZ", "MELI", "META", "MNST", "MPWR", "MRNA", "MRVL", "MSFT", "MU", "NFLX", "NTES", "NVDA", "NXPI", "ODFL", "ORLY", "PANW", "PAYX", "PCAR", "PDD", "PEP", "PYPL", "QCOM", "REGN", "ROP", "ROST", "SBUX", "SIRI", "SNPS", "STX", "TEAM", "TMUS", "TSLA", "TTWO", "TXN", "VRSK", "VRTX", "WBD", "WDC", "WDAY", "XEL", "ZS"]

def get_dow30_tickers():
    return ["AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS", "DOW", "GS", "HD", "HON", "IBM", "INTC", "JNJ", "JPM", "KO", "MCD", "MMM", "MRK", "MSFT", "NKE", "PG", "TRV", "UNH", "V", "VZ", "WMT"]

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
            "Avg_5m_Volume": int(avg_vol),
            "Surge_Multiplier": round(surge_multiplier, 1),
            "Direction": direction,
            "Surge_Price_Change": f"{round((max_vol_row['Close'] - max_vol_row['Open']) / max_vol_row['Open'] * 100, 2)}%"
        }
    except Exception as e:
        return {"Error": f"Error fetching {ticker_symbol}: {e}"}

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
    else:
        user_prompt = f"""
        【模式：3️⃣ 收市前大額買賣異動分析】
        請根據下方由 Python 篩選並提供的前一日（或最近交易日）收市前發生大額買賣異動的股票數據，生成一份重點解析報告。
        請指出這些大額買賣可能代表的機構意圖（例如：主力建倉、出貨、或是對沖），並針對這幾檔股票給出短線操作建議。
        
        【尾盤異動數據清單】：
        {json.dumps(data_payload, indent=2, ensure_ascii=False)}
        """
        
    return system_prompt.strip() + "\n\n" + user_prompt.strip()


# ==========================================
# Streamlit 網頁介面
# ==========================================

st.set_page_config(page_title="AI 股票量化分析 Prompt 產生器", page_icon="📈", layout="wide")

st.title("📈 AI 股票量化分析 Prompt 產生器")
st.markdown("這個工具可以幫你自動抓取最新的美股數據、計算技術指標 (RSI, MACD, 均線)，並產生可直接丟給 ChatGPT / Gemini 的精確 Prompt！")

tab1, tab2, tab3 = st.tabs(["1️⃣ 單股深度分析", "2️⃣ Top 5 雷達掃描", "3️⃣ 收市前大額買賣掃描"])

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

# --- Mode 3: 收市前大額買賣掃描 ---
with tab3:
    st.header("收市前大額買賣 (尾盤異動) 掃描")
    st.markdown("掃描最近一個交易日 **15:30 - 16:00 (美東時間)** 之間的 5 分鐘 K 線，找出尾盤成交量暴增的股票（機構主力進出訊號）。")
    
    scan_scope = st.radio("請選擇掃描範圍 (掃描全市場需要約 1~2 分鐘，請耐心等候)：", 
                          options=["🔥 NASDAQ 100 + Dow 30 (綜合掃描)", "✍️ 自訂觀察清單"],
                          index=0, horizontal=True)
                          
    if scan_scope == "✍️ 自訂觀察清單":
        default_watchlist_3 = "AAPL, NVDA, TSLA, AMD, AVGO, MSFT, AMZN, PLTR, SNOW, META, GME, AMC"
        watchlist_input_3 = st.text_area("請輸入觀察清單 (用逗號分隔)", value=default_watchlist_3, height=100, key="wl3")
    else:
        watchlist_input_3 = ""
        
    btn_mode3 = st.button("🚀 開始全範圍掃描並產生 Prompt", type="primary", key="btn3")
    
    if btn_mode3:
        if scan_scope == "🔥 NASDAQ 100 + Dow 30 (綜合掃描)":
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
                status_text_3.text(f"正在擷取 {ticker} 的分時數據 ({i+1}/{len(watch_list_3)})...")
                facts = fetch_late_day_surge(ticker)
                if facts and "Error" not in facts:
                    # 篩選條件：尾盤最大成交量至少是全日 5 分鐘平均的 2.5 倍
                    if facts.get("Surge_Multiplier", 0) >= 2.5:
                        all_surge_stocks.append(facts)
                progress_bar_3.progress((i + 1) / len(watch_list_3))
                
            status_text_3.text("分析完成！")
            
            # 按爆發倍數排序，選出最強的 10 檔
            top_surge_stocks = sorted(all_surge_stocks, key=lambda x: x.get("Surge_Multiplier", 0), reverse=True)[:10]
            
            status_text_3.empty()
            progress_bar_3.empty()
            
            if top_surge_stocks:
                prompt = generate_ai_prompt(3, top_surge_stocks)
                st.success(f"掃描完成！從 {len(watch_list_3)} 檔中篩選出 {len(top_surge_stocks)} 檔出現尾盤大額異動的股票。請點擊複製並貼給 AI。")
                st.code(prompt, language="markdown")
                st.dataframe(top_surge_stocks)
            else:
                st.warning("當前掃描範圍中沒有股票在尾盤出現明顯的大額異動 (單根5分鐘K線成交量 > 全日平均 2.5 倍)！")
