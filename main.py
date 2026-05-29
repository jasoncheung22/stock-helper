import yfinance as yf
import pandas as pd
import pandas_ta_classic as ta
import json
from datetime import datetime

def fetch_and_calculate_data(ticker_symbol):
    try:
        print(f"\n📡 [系統提示] 正在擷取 {ticker_symbol} 最新收盤數據與期權鏈...")
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
                # 抓取距離目前最近的期權到期日 (通常是本週五或下週五，短期爆發力最強)
                near_date = options_dates[0] 
                opt_chain = ticker.option_chain(near_date)
                calls = opt_chain.calls
                
                if not calls.empty:
                    # 大鯨魚篩選標準：今日成交量 > 未平倉量(OI)，且成交量必須大於 1,000 口（排除流動性極差的垃圾單）
                    unusual_calls = calls[(calls['volume'] > calls['openInterest']) & (calls['volume'] > 1000)]
                    
                    if not unusual_calls.empty:
                        # 找出當天被買得最瘋狂的那一口 Call
                        top_whale = unusual_calls.sort_values(by='volume', ascending=False).iloc[0]
                        whale_activity = f"發現機構大鯨！到期日: {near_date} | 行權價: ${top_whale['strike']} Call | 今日成交: {int(top_whale['volume'])}口 > 未平倉: {int(top_whale['openInterest'])}口 (多頭強力開倉)"
                    else:
                        # 備用方案：若沒有成交量大於 OI 的，則直接抓當日成交量最大的一口 Call
                        top_vol_call = calls.sort_values(by='volume', ascending=False).iloc[0]
                        whale_activity = f"焦點期權流：到期日: {near_date} | 行權價: ${top_vol_call['strike']} Call | 當日最大成交量: {int(top_vol_call['volume'])}口"
        except Exception as opt_e:
            whale_activity = f"期權數據暫缺 (原因: {str(opt_e)})"

        # 3. 封裝市場數據
        market_facts = {
            "Ticker": ticker_symbol,
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
            "Options_Whale_Activity": whale_activity, # <-- 新增參數注入
            "Raw_Turnover": avg_daily_turnover_usd
        }
        return market_facts
    except Exception as e:
        print(f"Error fetching data for {ticker_symbol}: {e}")
        return None

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

if __name__ == "__main__":
    # 配置你想掃描的股票
    watch_list = ["AAPL", "NVDA", "TSLA", "AMD", "AVGO", "MSFT", "AMZN", "PLTR", "SNOW", "META"]
    
    print("🔄 正在本地端執行量化篩選、指標運算與期權鏈掃描...")
    
    all_calculated_stocks = []
    for ticker in watch_list:
        facts = fetch_and_calculate_data(ticker)
        if facts:
            all_calculated_stocks.append(facts)
            
    filtered_stocks = [
        s for s in all_calculated_stocks 
        if s["Raw_Turnover"] >= 400000000 
        and s["MACD_Trend"] == "Golden Cross" 
        and "Bullish" in s["EMA_Alignment"]
    ]
    
    top_5_stocks = sorted(filtered_stocks, key=lambda x: x["MACD_Histogram"], reverse=True)[:5]
    
    for s in all_calculated_stocks: s.pop("Raw_Turnover", None)
    for s in top_5_stocks: s.pop("Raw_Turnover", None)

    print("\n" + "="*20 + " 複製下方文字給 Gemini " + "="*20)
    
    if all_calculated_stocks:
        print("\n👉【如果要查詢功能 1（單股分析），請複製以下內容】：\n")
        # 預設以清單中第一檔（例如 AAPL）為單股範例
        print(generate_ai_prompt(mode=1, data_payload=all_calculated_stocks[0]))
        
    print("\n" + "-"*50)
    
    if top_5_stocks:
        print("\n👉【如果要執行功能 2（Top 5 雷達），請複製以下內容】：\n")
        print(generate_ai_prompt(mode=2, data_payload=top_5_stocks))
    else:
        print("\n提示：當前 watch_list 中沒有股票完全符合「日均成交額>4億 + MACD金叉 + 均線多頭排列」的硬性篩選條件！")
        
    print("="*60)