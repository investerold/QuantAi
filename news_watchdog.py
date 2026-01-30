import time
import json
import requests
import os
import yfinance as yf
from datetime import datetime

# ================= CONFIGURATION =================
WATCHLIST = ['HIMS', 'ZETA', 'ODD', 'NVDA', 'TSLA', 'AMD', 'OSCR']
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
HISTORY_FILE = 'news_history.json'

# 使用最穩定的模型名稱
GEMINI_MODEL = "gemini-1.5-flash"

# ================= FUNCTIONS =================

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram Config Missing!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

def get_yfinance_news(ticker):
    """
    使用偽裝 Header 獲取新聞，避免被 Yahoo 攔截
    """
    try:
        # 1. 建立偽裝的 Session
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        
        # 2. 傳入 session 獲取 Ticker
        stock = yf.Ticker(ticker, session=session)
        news = stock.news
        
        return news if news else []
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return []

def call_gemini_rest_api(ticker, title, link):
    """
    不使用 SDK，直接用 Requests 打 REST API，避免套件版本問題
    """
    if not GEMINI_API_KEY:
        return f"📰 News: {title} (No AI Key)"
    
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    
    prompt_text = f"""
    You are a stock analyst.
    Ticker: {ticker}
    Headline: "{title}"
    Link: {link}
    
    Task: Summarize in 1 sentence and give sentiment (Bullish/Bearish/Neutral).
    Output Format: [Sentiment] Summary...
    """
    
    payload = {
        "contents": [{
            "parts": [{"text": prompt_text}]
        }]
    }
    
    try:
        response = requests.post(api_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=15)
        
        if response.status_code != 200:
            print(f"Gemini API Error {response.status_code}: {response.text}")
            return "SKIP"
            
        data = response.json()
        # 解析 JSON 結構
        try:
            text = data['candidates'][0]['content']['parts'][0]['text']
            return text.strip()
        except KeyError:
            print(f"Gemini JSON Parse Error: {data}")
            return "SKIP"
            
    except Exception as e:
        print(f"Gemini Request Failed: {e}")
        return "SKIP"

def main():
    print(f"[{datetime.now()}] Starting Watchdog (REST API Version)...")
    
    # !!! 測試模式：強制清空歷史，確保每一條新聞都被分析 !!!
    history = set()
    print("!!! FORCE RESET MODE ACTIVE !!!")
    
    new_alerts = 0
    
    for ticker in WATCHLIST:
        print(f"--------------------------------------------------")
        print(f"Checking {ticker}...", end=" ")
        
        # 獲取新聞
        news_items = get_yfinance_news(ticker)
        print(f"Found {len(news_items)} items.")
        
        if not news_items:
            print("   -> No news found (Yahoo might be blocking or no data).")
            continue

        # 除錯：印出第一條的結構，讓你確認 Key 是什麼
        first_keys = list(news_items[0].keys())
        print(f"🔍 [DEBUG KEYS]: {first_keys}")

        for item in news_items:
            # 嘗試抓取各種可能的 URL Key
            url = item.get('link') or item.get('url') or item.get('longURL')
            title = item.get('title')
            
            # 如果主要 Key 沒抓到，嘗試從 clickThroughUrl 抓
            if not url and 'clickThroughUrl' in item:
                url = item['clickThroughUrl'].get('url')

            if not url or not title:
                # 只有當真的缺資料時才印這行，避免洗版
                # print(f"      ❌ Skip: Missing Data")
                continue
            
            # 去除 URL 參數，避免重複 (例如 ?query=...)
            clean_url = url.split('?')[0]
            
            # 因為是 FORCE RESET 模式，這裡暫時忽略 history 檢查
            # if clean_url in history: continue

            print(f"   -> Found: {str(title)[:30]}...")
            
            # 呼叫 AI
            analysis = call_gemini_rest_api(ticker, title, url)
            
            if analysis and analysis != "SKIP":
                print(f"      [AI]: {analysis[:50]}...")
                
                msg = f"**#{ticker}**\n{analysis}\n[Read Source]({url})"
                send_telegram_message(msg)
                new_alerts += 1
                
                history.add(clean_url)
                time.sleep(2) # 避免打太快
            else:
                print("      ❌ AI Failed or Skipped")

        time.sleep(1)

    print(f"--------------------------------------------------")
    print(f"Done. Sent {new_alerts} alerts.")

if __name__ == "__main__":
    main()
