import time
import json
import requests
import os
import yfinance as yf
import google.generativeai as genai
from datetime import datetime, timedelta

# ================= CONFIGURATION =================
# 注意：ODDITY 代碼是 ODD
WATCHLIST = ['HIMS', 'ZETA', 'ODD', 'NVDA', 'TSLA', 'AMD', 'OSCR', 'MARA', 'COIN']

# Environment Variables
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
HISTORY_FILE = 'news_history.json'

# ================= FUNCTIONS =================

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            try: return set(json.load(f))
            except: return set()
    return set()

def save_history(history_set):
    clean_history = list(history_set)[-300:]
    with open(HISTORY_FILE, 'w') as f:
        json.dump(clean_history, f, indent=2)

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Telegram credentials missing.")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram Error: {e}")

def get_yfinance_news(ticker):
    try:
        stock = yf.Ticker(ticker)
        # 增加 user-agent 模擬，雖然 yfinance 內建有，但有時 Yahoo 會擋請求
        return stock.news
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return []

def analyze_with_gemini(ticker, title, link):
    if not GEMINI_API_KEY:
        return f"📰 News: {title}"
    
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""
        You are a Peter Lynch style investor focusing on GARP.
        Analyze this news for stock: ${ticker}.
        Headline: "{title}"
        
        Is this "Material News" (Earnings, M&A, FDA, Contracts) OR "Noise"?
        
        1. If NOISE/OPINION -> Reply exactly "SKIP".
        2. If MATERIAL -> Reply format:
           "Emoji | One-sentence summary | Sentiment"
        """
        response = model.generate_content(prompt, generation_config={"temperature": 0.1})
        result = response.text.strip()
        
        if "SKIP" in result:
            return "SKIP"
        return result
    except Exception as e:
        print(f"Gemini Error: {e}")
        # 如果 AI 報錯，還是回傳標題，確保不錯過
        return f"⚠️ AI Error: {title}"

def main():
    print(f"[{datetime.now()}] Starting Debug Scan...")
    
    history = load_history()
    print(f"Loaded {len(history)} past articles from history.")
    
    new_alerts = 0
    
    for ticker in WATCHLIST:
        print(f"Checking {ticker}...", end=" ")
        news_items = get_yfinance_news(ticker)
        
        # DEBUG: 打印抓到了幾條新聞
        print(f"Found {len(news_items)} raw items.") 
        
        if not news_items:
            continue
            
        for item in news_items:
            url = item.get('link')
            title = item.get('title')
            # pub_time = item.get('providerPublishTime', 0) # 暫時忽略時間檢查
            
            # 1. 歷史過濾 (這是唯一的過濾器)
            if url in history:
                continue
            
            # 2. 已移除 24h 時間過濾，解決 2026 vs 2025 的時間衝突
            
            # 3. AI 分析
            print(f"   -> Analyzing: {title[:30]}...")
            analysis = analyze_with_gemini(ticker, title, url)
            
            if analysis != "SKIP":
                msg = f"**#{ticker}**\n{analysis}\n[Read Source]({url})"
                send_telegram_message(msg)
                new_alerts += 1
                time.sleep(2)
            else:
                print(f"   -> Skipped (Noise)")
                
            history.add(url)
            
        time.sleep(1)

    save_history(history)
    print(f"Job Done. Sent {new_alerts} alerts.")

if __name__ == "__main__":
    main()
