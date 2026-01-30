import time
import json
import requests
import os
import yfinance as yf
import xml.etree.ElementTree as ET
import re # 用來清理 HTML 標籤
from datetime import datetime

# ================= CONFIGURATION =================
WATCHLIST = ['HIMS', 'ZETA', 'ODD', 'NVDA', 'TSLA', 'AMD', 'OSCR']
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
HISTORY_FILE = 'news_history.json'

# ✅ 改回 1.5-flash，速度快且額度高 (15 RPM)，不用擔心額度用完
GEMINI_MODEL = "gemini-1.5-flash"

# ================= FUNCTIONS =================

def load_history():
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

def clean_html(raw_html):
    """清除 RSS description 中的 HTML 標籤"""
    if not raw_html: return ""
    cleanr = re.compile('<.*?>')
    text = re.sub(cleanr, '', raw_html)
    return text.replace('&nbsp;', ' ').strip()

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
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

def get_google_rss_news(ticker):
    """Google RSS (含摘要提取)"""
    print(f"   📡 Fetching Google RSS for {ticker}...")
    try:
        url = f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        
        if resp.status_code != 200: return []
            
        root = ET.fromstring(resp.content)
        items = []
        # 限制前 3 條
        for item in root.findall('.//item')[:3]: 
            title = item.find('title').text
            link = item.find('link').text
            # ✅ 新增：嘗試抓取 description (摘要)
            description = item.find('description').text if item.find('description') is not None else ""
            
            if title and link:
                items.append({
                    'title': title, 
                    'link': link, 
                    'snippet': clean_html(description), # 清理 HTML
                    'source': 'GoogleRSS'
                })
        return items
    except Exception as e:
        print(f"   ❌ RSS Failed: {e}")
        return []

def get_yfinance_news(ticker):
    """YFinance (備用)"""
    print(f"   ⚠️ RSS Empty, trying yfinance for {ticker}...")
    try:
        stock = yf.Ticker(ticker)
        news = stock.news
        formatted_news = []
        for item in news[:3]: 
            formatted_news.append({
                'title': item.get('title'),
                'link': item.get('link') or item.get('url'),
                'snippet': "", # YFinance 通常不給 snippet
                'source': 'Yahoo'
            })
        return formatted_news
    except:
        return []

def get_stock_news(ticker):
    news = get_google_rss_news(ticker)
    if news: return news
    return get_yfinance_news(ticker)

def call_gemini_rest_api(ticker, title, link, snippet):
    if not GEMINI_API_KEY: return "No Key"
    
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    
    # ✅ 優化提示詞：要求條列式重點
    prompt = f"""
    Role: Senior Stock Analyst.
    Ticker: {ticker}
    News Title: "{title}"
    Snippet: "{snippet}"
    Link: {link}
    
    Task: 
    1. Determine sentiment (Bullish 🟢 / Bearish 🔴 / Neutral ⚪).
    2. Provide 2-3 short bullet points summarizing the KEY facts/reasons from the snippet.
    
    Output Format:
    [Sentiment Icon] Sentiment
    • Point 1
    • Point 2
    """
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    for attempt in range(3):
        try:
            response = requests.post(api_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=15)
            if response.status_code == 200:
                try:
                    return response.json()['candidates'][0]['content']['parts'][0]['text'].strip()
                except: return "SKIP"
            elif response.status_code == 429:
                time.sleep(30) # 遇到限制休息久一點
                continue
            else:
                return "SKIP"
        except:
            return "SKIP"
    return "SKIP"

def main():
    print(f"[{datetime.now()}] Starting Watchdog v7.0 (Details & Efficiency)...")
    
    history = load_history()
    print(f"Loaded {len(history)} history items.")
    
    new_alerts = 0
    
    for ticker in WATCHLIST:
        print(f"--------------------------------------------------")
        print(f"Checking {ticker}...", end=" ")
        
        news_items = get_stock_news(ticker)
        print(f"Found {len(news_items)} items.")
        
        for item in news_items:
            title = item.get('title')
            url = item.get('link')
            snippet = item.get('snippet', '')
            
            if not title or not url: continue
            clean_url = url.split('?')[0]
            
            if clean_url in history:
                print(f"   -> Skipping (Old): {str(title)[:20]}...")
                continue
            
            print(f"   -> Analyzing: {str(title)[:30]}...")
            
            # 呼叫 AI，傳入 snippet
            analysis = call_gemini_rest_api(ticker, title, url, snippet)
            
            if analysis and analysis != "SKIP":
                print(f"      [AI]: Sent Alert")
                
                source_label = item.get('source', 'Web')
                # 組合訊息
                msg = f"**#{ticker} ({source_label})**\n{analysis}\n\n[Read Source]({url})"
                
                send_telegram_message(msg)
                new_alerts += 1
                history.add(clean_url)
                
                # ✅ 1.5-flash 額度較高，休息 5 秒即可
                time.sleep(5)
            else:
                print("      ❌ AI Failed")

    save_history(history)
    print(f"--------------------------------------------------")
    print(f"Done. Sent {new_alerts} alerts.")

if __name__ == "__main__":
    main()
