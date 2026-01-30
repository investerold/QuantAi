import time
import json
import requests
import os
import yfinance as yf
import xml.etree.ElementTree as ET
from datetime import datetime

# ================= CONFIGURATION =================
WATCHLIST = ['HIMS', 'ZETA', 'ODD', 'NVDA', 'TSLA', 'AMD', 'OSCR']
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# 模型設定
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

def get_google_rss_news(ticker):
    """
    備用方案：當 yfinance 失敗時，使用 Google News RSS
    這在 GitHub Actions 上非常穩定。
    """
    print(f"   ⚠️ Switching to Google News RSS for {ticker}...")
    try:
        # Google News RSS 網址
        url = f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
        resp = requests.get(url, timeout=10)
        
        if resp.status_code != 200:
            return []
            
        # 解析 XML
        root = ET.fromstring(resp.content)
        items = []
        
        # 只取前 5 條最新的
        for item in root.findall('.//item')[:5]:
            title = item.find('title').text if item.find('title') is not None else "No Title"
            link = item.find('link').text if item.find('link') is not None else ""
            pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ""
            
            items.append({
                'title': title,
                'link': link,
                'published': pub_date,
                'source': 'GoogleRSS' # 標記來源
            })
        return items
    except Exception as e:
        print(f"   ❌ Google RSS Failed: {e}")
        return []

def get_stock_news(ticker):
    """
    主要邏輯：優先嘗試 yfinance，如果失敗或為空，轉用 Google RSS
    """
    # 1. 嘗試 yfinance (移除 session 參數，讓它自己處理)
    try:
        stock = yf.Ticker(ticker)
        news = stock.news
        if news and len(news) > 0:
            return news
    except Exception as e:
        print(f"   yfinance error: {e}")
    
    # 2. 如果 yfinance 沒資料，使用備用方案
    return get_google_rss_news(ticker)

def call_gemini_rest_api(ticker, title, link):
    """
    直接打 REST API，不依賴 SDK
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
        try:
            text = data['candidates'][0]['content']['parts'][0]['text']
            return text.strip()
        except KeyError:
            return "SKIP"
            
    except Exception as e:
        print(f"Gemini Request Failed: {e}")
        return "SKIP"

def main():
    print(f"[{datetime.now()}] Starting Watchdog (Hybrid Mode)...")
    print("!!! FORCE RESET MODE ACTIVE !!!")
    
    new_alerts = 0
    # 這裡可以加入讀取歷史的邏輯，但在 Debug 模式我們先用空的
    history = set() 

    for ticker in WATCHLIST:
        print(f"--------------------------------------------------")
        print(f"Checking {ticker}...", end=" ")
        
        # 獲取新聞 (整合了 yfinance 和 Google RSS)
        news_items = get_stock_news(ticker)
        print(f"Found {len(news_items)} items.")
        
        if not news_items:
            print("   -> No news found from ANY source.")
            continue

        for item in news_items:
            # 處理不同來源的 Key 差異
            title = item.get('title')
            url = item.get('link') or item.get('url')
            
            # yfinance 特有的備用 link
            if not url and 'clickThroughUrl' in item:
                url = item['clickThroughUrl'].get('url')

            if not url or not title:
                continue
            
            # 簡單過濾掉過長的 URL 參數
            clean_url = url.split('?')[0]
            
            # 如果你要防止重複發送，可以在這裡檢查 history
            # if clean_url in history: continue

            print(f"   -> Analyzing: {str(title)[:30]}...")
            
            analysis = call_gemini_rest_api(ticker, title, url)
            
            if analysis and analysis != "SKIP":
                print(f"      [AI]: {analysis[:50]}...")
                
                # 訊息內容
                source_label = item.get('source', 'Yahoo') # 標記來源
                msg = f"**#{ticker} ({source_label})**\n{analysis}\n[Read Source]({url})"
                
                send_telegram_message(msg)
                new_alerts += 1
                
                history.add(clean_url)
                
                # 休息一下，避免被 API 限制
                time.sleep(2)
            else:
                print("      ❌ AI Failed")

        time.sleep(1)

    print(f"--------------------------------------------------")
    print(f"Done. Sent {new_alerts} alerts.")

if __name__ == "__main__":
    main()
