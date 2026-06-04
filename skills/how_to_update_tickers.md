# 股市清單更新技能 (Update Stock Tickers Skill)

當使用者要求「更新成份股」、「更新納斯達克清單」、「更新 Dow 30」時，請執行以下步驟：

## 步驟 1：進行網路搜尋 (Web Search)
不要依賴固定的爬蟲腳本，因為網頁結構容易改變。請直接使用 `search_web` 工具搜尋最新的成份股調整名單。
建議的搜尋關鍵字：
- `Nasdaq 100 index additions deletions [今年年份]` (例如: 2026)
- `Dow Jones Industrial Average additions deletions [今年年份]`

## 步驟 2：整理最新的名單
- 檢視 `app.py` 中目前的 `get_nasdaq100_tickers()` 和 `get_dow30_tickers()` 陣列。
- 將搜尋結果中「被剔除 (Deletions)」的股票從陣列中刪除。
- 將搜尋結果中「新加入 (Additions)」的股票新增到陣列中。

## 步驟 3：可選驗證 (Validation)
如果你不確定某檔股票是否已經下市 (Delisted)，你可以寫一個暫時的 Python 腳本，用 `yfinance.download(ticker, period='1d')` 來快速驗證該代號是否還存在。如果回傳空的 dataframe 或是 HTTP Error，代表該股票可能已經下市或換代號，請將其移除。

## 步驟 4：更新 `app.py`
使用 `multi_replace_file_content` 工具，直接替換 `app.py` 裡面的 `get_nasdaq100_tickers()` 和 `get_dow30_tickers()` 函數回傳的陣列。

## 步驟 5：完成通知
告訴使用者已經根據最新的官方資訊更新完畢，並列出移除了哪些股票、新增了哪些股票，讓使用者清楚知道變化。
