import time
import json
import requests
import os
import yfinance as yf
import google.generativeai as genai
from datetime import datetime, timedelta

# ================= CONFIGURATION =================
# 注意：Oddity Tech 代碼是 ODD，必須準確
WATCHLIST = ['HIMS', 'ZETA', 'ODD', 'NVDA', 'TSLA', 'AMD', 'OSCR']

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
    # 只保留最近 300 條，避免 JSON 文件無限膨脹
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
        "disable_web_page_preview": True # 關閉預覽讓版面更乾淨
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram Error: {e}")

def get_yfinance_news(ticker):
    """
    從 Yahoo Finance 獲取該 Ticker 的專屬新聞
    """
    try:
        # yfinance 的 .news 屬性會回傳該股票頁面的最新新聞
        stock = yf.Ticker(ticker)
        return stock.news
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return []

def analyze_with_gemini(ticker, title, link):
    """
    Gemini 作為過濾器 (Filter) 和總結者 (Summarizer)
    """
    if not GEMINI_API_KEY:
        return f"📰 News: {title}"

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = f"""
        You are a Peter Lynch style investor focusing on GARP (Growth at a Reasonable Price).
        Analyze this news for stock: ${ticker}.
        Headline: "{title}"
        
        Is this "Material News" (Earnings, M&A, FDA approval, Partnership, Contracts, Short Report) OR "Noise" (Opinion, Top 10 lists, generic market wrap)?
        
        1. If NOISE/OPINION -> Reply exactly "SKIP".
        2. If MATERIAL -> Reply with a strict format:
           "Emoji | One-sentence summary (Max 15 words) | Sentiment (Bullish/Bearish)"
           
        Examples:
        - "🟢 | Q3 Revenue grew 40% YoY beating estimates | Bullish"
        - "🔴 | CFO resigned unexpectedly amid audit probe | Bearish"
        """
        
        # 設置低 Temperature 以獲得穩定的格式
        response = model.generate_content(prompt, generation_config={"temperature": 0.1})
        result = response.text.strip()
        
        if "SKIP" in result:
            return "SKIP"
        return result

    except Exception as e:
        print(f"Gemini Error: {e}")
        return f"⚠️ AI N/A: {title}"

def main():
    print(f"[{datetime.now()}] Starting YFinance Scan...")
    
    # 1. 讀取歷史
    history = load_history()
    initial_count = len(history)
    print(f"Loaded {initial_count} past articles.")
    
    new_alerts = 0
    
    # 2. 遍歷清單
    for ticker in WATCHLIST:
        print(f"Checking {ticker}...")
        news_items = get_yfinance_news(ticker)
        
        if not news_items:
            print(f" -> No news data found for {ticker}")
            continue

        for item in news_items:
            # yfinance news 格式通常包含 link, title, providerPublishTime
            url = item.get('link')
            title = item.get('title')
            pub_time = item.get('providerPublishTime', 0)
            
            # 過濾 1: 是否已發送過
            if url in history:
                continue
                
            # 過濾 2: 時效性 (只看過去 24 小時)
            # 這是為了防止第一次運行時把一年前的新聞都發出來
            article_time = datetime.fromtimestamp(pub_time)
            if article_time < datetime.now() - timedelta(hours=24):
                continue

            # 過濾 3: AI 分析
            analysis = analyze_with_gemini(ticker, title, url)
            
            if analysis != "SKIP":
                # 構建消息
                msg = f"**#{ticker}**\n{analysis}\n[Read Source]({url})"
                send_telegram_message(msg)
                new_alerts += 1
                time.sleep(2) # Telegram Rate Limit 保護
            else:
                print(f" -> Skipped (Noise): {title}")

            # 加入歷史 (無論是 SKIP 還是發送，都記錄下來以免重複分析)
            history.add(url)
            
        time.sleep(1) # YFinance Rate Limit 保護

    # 3. 保存歷史
    if len(history) > initial_count:
        save_history(history)
        print(f"History updated. New items: {len(history) - initial_count}")
    else:
        print("No new unique articles found.")

if __name__ == "__main__":
    main()
