import time
import json
import requests
import os
import yfinance as yf
import google.generativeai as genai
from datetime import datetime

# ================= CONFIGURATION =================
WATCHLIST = ['HIMS', 'ZETA', 'ODD', 'NVDA', 'TSLA', 'AMD', 'OSCR', 'MARA', 'COIN']

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
        return stock.news or []
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return []

def analyze_with_gemini(ticker, title, link):
    if not GEMINI_API_KEY:
        return f"📰 News: {title}"
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # 測試用：移除 "SKIP" 邏輯，強制它說話
        prompt = f"""
        Analyze ${ticker} news for a stock investor.
        Headline: "{title}"
        Task: Summarize in 1 short sentence and provide sentiment.
        """
        response = model.generate_content(prompt, generation_config={"temperature": 0.1})
        return response.text.strip()
    except Exception as e:
        print(f"Gemini Error: {e}")
        return f"⚠️ AI Error: {title}"

def main():
    print(f"[{datetime.now()}] Starting Watchdog v5.2...")
    history = load_history()
    new_alerts = 0
    
    for ticker in WATCHLIST:
        print(f"Checking {ticker}...", end=" ")
        news_items = get_yfinance_news(ticker)
        print(f"Found {len(news_items)} items.")
        
        for item in news_items:
            url = item.get('link')
            title = item.get('title')
            
            # 1. 基礎檢查：如果標題或 URL 是空的就跳過 (解決 NoneType 報錯)
            if not url or not title:
                continue
            
            # 2. 歷史重複檢查
            if url in history:
                continue
            
            # 3. AI 分析
            # 安全地截取標題用於 Log
            safe_title = str(title)[:30]
            print(f"   -> Analyzing: {safe_title}...")
            
            analysis = analyze_with_gemini(ticker, title, url)
            
            if analysis != "SKIP":
                msg = f"**#{ticker}**\n{analysis}\n[Read Source]({url})"
                send_telegram_message(msg)
                new_alerts += 1
                time.sleep(2) # 避免 TG 頻率限制
            
            history.add(url)
        
        time.sleep(1) # 避免 Yahoo 頻率限制

    save_history(history)
    print(f"Done. Sent {new_alerts} alerts.")

if __name__ == "__main__":
    main()
