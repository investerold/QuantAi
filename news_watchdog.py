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
HISTORY_FILE = 'news_history.json'

# 你指定的模型 (注意：2.5 限制每分鐘只能 5 次請求)
GEMINI_MODEL = "gemini-2.5-flash"

# ================= FUNCTIONS =================

def load_history():
    """讀取已經發送過的新聞，避免重複浪費 AI 額度"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_history(history_set):
    """保存歷史紀錄"""
    clean_history = list(history_set)[-300:] # 只保留最近300條
    with open(HISTORY_FILE, 'w') as f:
        json.dump(clean_history, f, indent=2)

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
    """Google RSS (優先使用)"""
    print(f"   📡 Fetching Google RSS for {ticker}...")
    try:
        url = f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        
        if resp.status_code != 200:
            return []
            
        root = ET.fromstring(resp.content)
        items = []
        # 限制只抓前 3 條，避免一次消耗太多 AI 額度
        for item in root.findall('.//item')[:3]: 
            title = item.find('title').text
            link = item.find('link').text
            if title and link:
                items.append({'title': title, 'link': link, 'source': 'GoogleRSS'})
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
        for item in news[:3]: # 同樣限制前3條
            formatted_news.append({
                'title': item.get('title'),
                'link': item.get('link') or item.get('url'),
                'source': 'Yahoo'
            })
        return formatted_news
    except:
        return []

def get_stock_news(ticker):
    news = get_google_rss_news(ticker)
    if news: return news
    return get_yfinance_news(ticker)

def call_gemini_rest_api(ticker, title, link):
    """
    呼叫 Gemini API，包含自動重試機制 (Auto-Retry)
    """
    if not GEMINI_API_KEY:
        return f"📰 News: {title} (No AI Key)"
    
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    Role: Stock Analyst.
    Ticker: {ticker}
    Headline: "{title}"
    Link: {link}
    Task: Summarize in 1 sentence & provide sentiment (Bullish/Bearish/Neutral).
    Format: [Sentiment] Summary...
    """
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    # 最多重試 3 次
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(api_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=15)
            
            # 情況 A: 成功
            if response.status_code == 200:
                data = response.json()
                try:
                    return data['candidates'][0]['content']['parts'][0]['text'].strip()
                except KeyError:
                    return "SKIP"
            
            # 情況 B: 遇到 429 (Rate Limit) -> 休息久一點再試
            elif response.status_code == 429:
                wait_time = 65 # 休息 65 秒確保額度重置
                print(f"      ⚠️ Quota Exceeded (429). Sleeping {wait_time}s before retry {attempt+1}/{max_retries}...")
                time.sleep(wait_time)
                continue # 重新跑 loop
            
            # 情況 C: 其他錯誤
            else:
                print(f"      ❌ Gemini Error {response.status_code}: {response.text}")
                return "SKIP"
                
        except Exception as e:
            print(f"      ❌ Request Failed: {e}")
            return "SKIP"
            
    return "SKIP" # 重試多次後放棄

def main():
    print(f"[{datetime.now()}] Starting Watchdog v6.0 (Rate-Limit Safe)...")
    
    # 1. 讀取歷史紀錄 (不再是 Force Reset)
    history = load_history()
    print(f"Loaded {len(history)} past news items.")
    
    new_alerts = 0
    
    for ticker in WATCHLIST:
        print(f"--------------------------------------------------")
        print(f"Checking {ticker}...", end=" ")
        
        news_items = get_stock_news(ticker)
        print(f"Found {len(news_items)} items.")
        
        for item in news_items:
            title = item.get('title')
            url = item.get('link')
            
            if not title or not url: continue
            
            clean_url = url.split('?')[0] # 簡單清理網址
            
            # 2. 如果已經分析過，直接跳過 (最省錢的步驟)
            if clean_url in history:
                print(f"   -> Skipping (Already sent): {str(title)[:20]}...")
                continue
            
            print(f"   -> Analyzing: {str(title)[:30]}...")
            
            # 3. 呼叫 AI (內含重試機制)
            analysis = call_gemini_rest_api(ticker, title, url)
            
            if analysis and analysis != "SKIP":
                print(f"      [AI]: {analysis[:50]}...")
                
                source_label = item.get('source', 'Web')
                msg = f"**#{ticker} ({source_label})**\n{analysis}\n[Read Source]({url})"
                
                send_telegram_message(msg)
                new_alerts += 1
                
                # 加入歷史並存檔
                history.add(clean_url)
                
                # 4. 關鍵：Gemini 2.5 限制每分鐘 5 次
                # 我們每條休息 15 秒，確保一分鐘最多 4 次，絕對安全
                print("      💤 Cooling down 15s for API quota...")
                time.sleep(15)
            else:
                print("      ❌ AI Failed (Skipping Telegram)")

    # 5. 結束前保存歷史
    save_history(history)
    print(f"--------------------------------------------------")
    print(f"Done. Sent {new_alerts} alerts.")

if __name__ == "__main__":
    main()
