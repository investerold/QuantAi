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
GEMINI_MODEL = "gemini-2.5-flash"

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
    【優先策略】Google News RSS
    這在自動化環境中最穩定，幾乎保證有標題和連結。
    """
    print(f"   📡 Fetching Google News RSS for {ticker}...")
    try:
        # 使用 Google News RSS 搜尋特定股票
        url = f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
        
        # 設置 User-Agent 避免被拒絕
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        resp = requests.get(url, headers=headers, timeout=10)
        
        if resp.status_code != 200:
            print(f"   ❌ RSS Error: Status {resp.status_code}")
            return []
            
        # 解析 XML
        root = ET.fromstring(resp.content)
        items = []
        
        # 取前 5 條
        for item in root.findall('.//item')[:5]:
            title = item.find('title').text if item.find('title') is not None else None
            link = item.find('link').text if item.find('link') is not None else None
            pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ""
            
            if title and link:
                items.append({
                    'title': title,
                    'link': link,
                    'published': pub_date,
                    'source': 'GoogleRSS'
                })
        return items
    except Exception as e:
        print(f"   ❌ Google RSS Failed: {e}")
        return []

def get_yfinance_news(ticker):
    """
    【備用策略】如果 Google RSS 失敗，才嘗試 yfinance
    """
    print(f"   ⚠️ RSS Empty, trying yfinance fallback for {ticker}...")
    try:
        stock = yf.Ticker(ticker)
        news = stock.news
        
        # 轉換 yfinance 格式以匹配 RSS 格式
        formatted_news = []
        for item in news:
            formatted_news.append({
                'title': item.get('title'),
                'link': item.get('link') or item.get('url'),
                'source': 'Yahoo'
            })
        return formatted_news
    except Exception as e:
        print(f"   yfinance error: {e}")
        return []

def get_stock_news(ticker):
    """
    主邏輯：優先 Google RSS，失敗則用 Yahoo
    """
    # 1. 優先嘗試 Google RSS
    news = get_google_rss_news(ticker)
    if news:
        return news
    
    # 2. 如果 RSS 沒東西，嘗試 yfinance
    return get_yfinance_news(ticker)

def call_gemini_rest_api(ticker, title, link):
    """
    直接調用 REST API，不依賴 SDK
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
    print(f"[{datetime.now()}] Starting Watchdog (Google RSS First Mode)...")
    print("!!! FORCE RESET MODE ACTIVE !!!")
    
    new_alerts = 0
    history = set() 

    for ticker in WATCHLIST:
        print(f"--------------------------------------------------")
        print(f"Checking {ticker}...", end=" ")
        
        # 獲取新聞
        news_items = get_stock_news(ticker)
        print(f"Found {len(news_items)} items.")
        
        if not news_items:
            print("   -> No news found from ANY source.")
            continue

        # === 強制診斷：如果找到了卻沒發送，印出第一條來看看 ===
        first = news_items[0]
        # print(f"🔍 DEBUG ITEM: {first}") 
        
        for item in news_items:
            title = item.get('title')
            url = item.get('link')
            
            # 檢查缺少的數據
            if not title or not url:
                print(f"      ❌ Skipping item with missing keys. Keys found: {list(item.keys())}")
                continue
            
            clean_url = url.split('?')[0]
            
            # 因為是 FORCE RESET 模式，忽略 history
            # if clean_url in history: continue

            print(f"   -> Analyzing: {str(title)[:30]}...")
            
            analysis = call_gemini_rest_api(ticker, title, url)
            
            if analysis and analysis != "SKIP":
                print(f"      [AI]: {analysis[:50]}...")
                
                source_label = item.get('source', 'Unknown')
                msg = f"**#{ticker} ({source_label})**\n{analysis}\n[Read Source]({url})"
                
                send_telegram_message(msg)
                new_alerts += 1
                
                history.add(clean_url)
                time.sleep(2)
            else:
                print("      ❌ AI Failed")

        time.sleep(1)

    print(f"--------------------------------------------------")
    print(f"Done. Sent {new_alerts} alerts.")

if __name__ == "__main__":
    main()
