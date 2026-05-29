import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta_classic as ta
import json
from datetime import datetime

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
            
        # 1. 技術指標運算
        df.ta.rsi(length=14, append=True)
        df.ta.macd(append=True)
        df.ta.ema(length=20, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.ema(length=100, append=True)
        df.ta.bbands(length=20, append=True)
        
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
        
        ema20 = get_val('EMA_20')
        ema50 = get_val('EMA_50')
        ema100 = get_val('EMA_100')
        
        is_ema_bullish = close_price > ema20 > ema50 > ema100
        is_volume_surging = volume > (vol_ma20 * 1.2)
        avg_daily_turnover_usd = vol_ma20 * close_price
        
        # 2. 【全新功能】本地端期權大鯨異動掃描
        whale_activity = "未監測到異常大單 (Normal Flow)"
        try:
            options_dates = ticker.options
            if options_dates:
                # 抓取距離目前最近的期權到期日
                near_date = options_dates[0] 
                opt_chain = ticker.option_chain(near_date)
                calls = opt_chain.calls
                
                if not calls.empty:
                    # 大鯨魚篩選標準
                    unusual_calls = calls[(calls['volume'] > calls['openInterest']) & (calls['volume'] > 1000)]
                    
                    if not unusual_calls.empty:
                        top_whale = unusual_calls.sort_values(by='volume', ascending=False).iloc[0]
                        whale_activity = f"發現機構大鯨！到期日: {near_date} | 行權價: ${top_whale['strike']} Call | 今日成交: {int(top_whale['volume'])}口 > 未平倉: {int(top_whale['openInterest'])}口 (多頭強力開倉)"
                    else:
                        top_vol_call = calls.sort_values(by='volume', ascending=False).iloc[0]
                        whale_activity = f"焦點期權流：到期日: {near_date} | 行權價: ${top_vol_call['strike']} Call | 當日最大成交量: {int(top_vol_call['volume'])}口"
        except Exception as opt_e:
            whale_activity = f"期權數據暫缺 (原因: {str(opt_e)})"

        # 3. 封裝市場數據
        market_facts = {
            "Ticker": ticker_symbol.upper(),
            "Date": latest_data.name.strftime("%Y-%m-%d"),
            "Close_Price": close_price,
            "Volume": volume,
            "Avg_Volume_20D": int(vol_ma20),
            "Volume_Surge": "Yes" if is_volume_surging else "No",
            "Avg_Daily_Turnover_USD": f"{round(avg_daily_turnover_usd / 1000000, 2)}M",
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
        並在表格下方附上 Investing.com, AASTOCKS, TradingView, Barchart 的驗證連結。
        
        【絕對市場數據】：
        {json.dumps(data_payload, indent=2, ensure_ascii=False)}
        """
    else:
        user_prompt = f"""
        【模式：2️⃣ Top 5 潛力美股雷達全市場掃描】
        請根據下方由 Python 篩選並提供的前 5 名潛力股 JSON 數據，生成匯總排名的 Markdown 表格。
        必須包含欄位：排名、股票代號、潛力分數、技術指標與觸發信號、期權大鯨異動、基本面與催化劑、操作建議。
        並在表格下方附上相關數據來源的驗證連結。
        
        【Top 5 絕對市場數據清單】：
        {json.dumps(data_payload, indent=2, ensure_ascii=False)}
        """
        
    return system_prompt.strip() + "\n\n" + user_prompt.strip()


# ==========================================
# Streamlit 網頁介面
# ==========================================

st.set_page_config(page_title="AI 股票量化分析 Prompt 產生器", page_icon="📈", layout="wide")

st.title("📈 AI 股票量化分析 Prompt 產生器")
st.markdown("這個工具可以幫你自動抓取最新的美股數據、計算技術指標 (RSI, MACD, 均線)，並產生可直接丟給 ChatGPT / Gemini 的精確 Prompt！")

tab1, tab2 = st.tabs(["1️⃣ 單股深度分析", "2️⃣ Top 5 雷達掃描"])

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
    
    default_watchlist = "AAPL, NVDA, TSLA, AMD, AVGO, MSFT, AMZN, PLTR, SNOW, META"
    watchlist_input = st.text_area("請輸入觀察清單 (用逗號分隔)", value=default_watchlist, height=100)
    btn_mode2 = st.button("開始掃描並產生 Prompt", type="primary", key="btn2")
    
    if btn_mode2:
        watch_list = [x.strip().upper() for x in watchlist_input.split(",") if x.strip()]
        
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
