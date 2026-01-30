import time
import json
import requests
import os
import yfinance as yf
import google.generativeai as genai
from datetime import datetime, timedelta

# ================= CONFIGURATION =================
# Watchlist: 混合了你的長線(GARP)與短線(期權)關注名單
WATCHLIST = ['HIMS', 'ZETA', 'ODDITY', 'NVDA', 'TSLA', 'AMD', 'OSCR']

# Keys
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

HISTORY_FILE = 'news_history.json'
SCAN_INTERVAL = 0 # GitHub Actions 是一次性執行，不需要 while True 循環 (由 cron 控制)

# ================= SYSTEM FUNCTIONS =================

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            try: return set(json.load(f))
            except: return set()
    return set()

def save_history(history_set):
    # 只保留最近 500 條記錄，防止文件過大
    clean_history = list(history_set)[-500:]
    with open(HISTORY_FILE, 'w') as f:
        json.dump(clean_history, f)

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Telegram credentials missing.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram Error: {e}")

# ================= CORE LOGIC =================

def get_yfinance_news(ticker):
    """
    使用 Yahoo Finance 獲取針對性極強的股票新聞
    """
    try:
        stock = yf.Ticker(ticker)
        news_list = stock.news  # 返回該股票的最新新聞列表
        return news_list
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return []

def analyze_with_gemini(ticker, title, link):
    """
    Peter Lynch Persona Analysis
    """
    if not GEMINI_API_KEY:
        return f"📰 *{ticker} News*\n{title}"

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # Prompt 設計：專注於區分 "噪音" (Motley Fool 意見稿) vs "信號" (財報/合作/FDA)
        prompt = f"""
        Role: You are Peter Lynch, a GARP investor.
        Target: Analyze news for stock ${ticker}.
        Headline: "{title}"
        
        Task:
        1. Is this 'Hard News' (Earnings, M&A, FDA, Contracts, Lawsuits, Guidance) or 'Fluff/Opinion' (Top 10 stocks, Why stock moved)?
        2. If Fluff/Opinion -> Reply "SKIP" only.
        3. If Hard News -> Summarize in 1 bullet point (max 20 words). Identify if Positive (Bullish) or Negative (Bearish).
        
        Output Format:
        [Sentiment Emoji] Summary
        (e.g., 🟢 Q3 Earnings beat exp. by 10%.)
        """
        
        response = model.generate_content(prompt)
        result = response.text.strip()
        
        # 如果 Gemini 認為是廢話，直接回傳 SKIP
        if "SKIP" in result:
            return "SKIP"
            
        return result
    except Exception as e:
        print(f"Gemini Error: {e}")
        # 如果 AI 失敗，為了不漏掉新聞，還是回傳標題
        return f"⚠️ AI Error: {title}"

def main():
    print(f"[{datetime.now()}] Starting Scraper Job...")
    history = load_history()
    new_links_found = 0
    
    for ticker in WATCHLIST:
        print(f"Checking {ticker}...")
        news_items = get_yfinance_news(ticker)
        
        for item in news_items:
            # YFinance 結構: {'title': '...', 'link': '...', 'providerPublishTime': ...}
            url = item.get('link')
            title = item.get('title')
            
            # 1. 檢查是否已處理過
            if url in history:
                continue
                
            # 2. 時間過濾：只看過去 24 小時內的新聞 (YF 有時會給舊的)
            pub_time = item.get('providerPublishTime', 0)
            if datetime.fromtimestamp(pub_time) < datetime.now() - timedelta(hours=24):
                continue

            # 3. AI 分析
            print(f"Analyzing: {title}")
            analysis = analyze_with_gemini(ticker, title, url)
            
            # 4. 根據結果推送
            if analysis != "SKIP":
                msg = f"**#{ticker}** {analysis}\n[Read Source]({url})"
                send_telegram_message(msg)
                new_links_found += 1
                time.sleep(2) # 避免 Telegram 刷屏過快
            
            # 5. 記錄到歷史 (即使是 SKIP 的也要記錄，以免下次重複分析)
            history.add(url)
            
        time.sleep(1) # 避免對 Yahoo 請求過快

    save_history(history)
    print(f"Job Done. Sent {new_links_found} alerts.")

if __name__ == "__main__":
    main()
