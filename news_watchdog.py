import time
import json
import requests
import os
import yfinance as yf
import google.generativeai as genai
from datetime import datetime

# ================= CONFIGURATION =================
WATCHLIST = ['HIMS', 'ZETA', 'ODD', 'NVDA', 'TSLA', 'AMD', 'OSCR']

# 建議先用 1.5-flash 確保跑通，如果你確定你有 2.0 或更高權限，再改這裡
# 常見有效值: 'gemini-1.5-flash', 'gemini-2.0-flash-exp'
MODEL_NAME = 'gemini-1.5-flash' 

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
HISTORY_FILE = 'news_history.json'

# ================= FUNCTIONS =================

def load_history():
    # 這裡暫時維持"空集合"，讓你每次測試都有結果
    # 正式上線時把下面這行改成 return set() 即可
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_history(history_set):
    clean_history = list(history_set)[-300:]
    with open(HISTORY_FILE, 'w') as f:
        json.dump(clean_history, f, indent=2)

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram Token or Chat ID missing!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        resp = requests.post(url, json=payload)
        if resp.status_code != 200:
            print(f"Telegram Send Failed: {resp.text}")
    except Exception as e:
        print(f"Telegram Connection Error: {e}")

def get_yfinance_news(ticker):
    try:
        stock = yf.Ticker(ticker)
        # yfinance 的 news 有時會返回 None
        return stock.news if stock.news else []
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return []

def analyze_with_gemini(ticker, title, link):
    if not GEMINI_API_KEY:
        return f"📰 News: {title} (No AI Key)"
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(MODEL_NAME)
        
        prompt = f"""
        You are a stock market analyst.
        Ticker: ${ticker}
        Headline: "{title}"
        Link: {link}
        
        Task: Provide a very brief summary (1 sentence) and a sentiment label (Bullish/Bearish/Neutral).
        Format: [Sentiment] Summary
        """
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Gemini Error ({MODEL_NAME}): {e}")
        return "SKIP" # 如果 AI 壞了，回傳 SKIP 以便跳過或做錯誤處理

def main():
    print(f"[{datetime.now()}] Starting Watchdog (DEBUG MODE)...")
    
    # !!! 測試模式：強制重置歷史，確保每次都分析 !!!
    history = set() 
    print("!!! FORCE HISTORY RESET ACTIVE !!!")
    
    new_alerts = 0
    
    for ticker in WATCHLIST:
        print(f"--------------------------------------------------")
        print(f"Checking {ticker}...", end=" ")
        news_items = get_yfinance_news(ticker)
        print(f"Found {len(news_items)} items.")
        
        if not news_items:
            continue

        # ================== DEBUG 關鍵點 ==================
        # 這裡會印出第一條新聞的所有 Key，如果跑失敗，看 Log 這裡最重要
        first_item = news_items[0]
        print(f"🔍 [DEBUG] First Item Keys: {list(first_item.keys())}")
        # =================================================

        for item in news_items:
            # 嘗試抓取 Title
            title = item.get('title')
            
            # 嘗試抓取 URL，yfinance 不同版本 key 不一樣
            url = item.get('link') or item.get('url') or item.get('longURL')
            
            # 如果還是空的，且有 clickThroughUrl (有時 Yahoo 結構會變)
            if not url and 'clickThroughUrl' in item:
                url = item['clickThroughUrl'].get('url')

            # Debug: 如果缺少關鍵資料，印出來為什麼
            if not title or not url:
                print(f"      ❌ SKIPPING ITEM: Missing Data. Title: {bool(title)}, URL: {bool(url)}")
                # 這裡可以把 item 印出來看看結構
                # p
