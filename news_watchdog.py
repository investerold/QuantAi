import time
import json
import requests
import os
import yfinance as yf
import xml.etree.ElementTree as ET
import re
from datetime import datetime

# ================= CONFIGURATION =================
WATCHLIST = ['HIMS', 'ZETA', 'ODD', 'NVDA', 'TSLA', 'AMD', 'OSCR']
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
HISTORY_FILE = 'news_history.json'

# ✅ 改用 1.5 Flash，每日額度 (RPD) 通常是 1500 次，遠高於 2.5 Flash 的 50 次
# 如果你堅持要用 2.5，請自行改回 "gemini-2.5-flash"，但保證會爆
GEMINI_MODEL = "gemini-2.5-flash-lite"

# 垃圾關鍵字過濾 (節省 API)
IGNORE_KEYWORDS = [
    "class action", "lawsuit", "investigation", "zacks", "motley fool", 
    "shareholder rights", "loss alert", "reminder", "dividend"
]

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
    # 只保留最後 500 條記錄，避免文件過大
    clean_history = list(history_set)[-500:] 
    with open(HISTORY_FILE, 'w') as f:
        json.dump(clean_history, f, indent=2)

def clean_html(raw_html):
    if not raw_html: return ""
    cleanr = re.compile('<.*?>')
    text = re.sub(cleanr, '', raw_html)
    return text.replace('&nbsp;', ' ').strip()

def is_spam(title):
    """檢查標題是否包含垃圾關鍵字"""
    title_lower = title.lower()
    for kw in IGNORE_KEYWORDS:
        if kw in title_lower:
            return True
    return False

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
    print(f"   📡 Fetching Google RSS for {ticker}...")
    try:
        url = f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        
        if resp.status_code != 200: return []
            
        root = ET.fromstring(resp.content)
        items = []
        for item in root.findall('.//item')[:4]:  # 取前 4 條
            title = item.find('title').text
            link = item.find('link').text
            
            if title and link and not is_spam(title):
                items.append({
                    'title': title, 
                    'link': link, 
                    'source': 'GoogleRSS'
                })
        return items
    except Exception as e:
        print(f"   ❌ RSS Failed: {e}")
        return []

def get_yfinance_news(ticker):
    print(f"   ⚠️ RSS Empty, trying yfinance for {ticker}...")
    try:
        stock = yf.Ticker(ticker)
        news = stock.news
        formatted_news = []
        for item in news[:3]: 
            title = item.get('title')
            link = item.get('link') or item.get('url')
            if title and link and not is_spam(title):
                formatted_news.append({
                    'title': title,
                    'link': link,
                    'source': 'Yahoo'
                })
        return formatted_news
    except:
        return []

def call_gemini_batch(ticker, news_items):
    """
    批次處理：將該股票的所有新新聞打包成一個 Prompt 發送。
    節省 API Call 次數 (N -> 1)。
    """
    if not GEMINI_API_KEY: return None

    # 構建 Prompt
    news_text = ""
    for idx, item in enumerate(news_items, 1):
        news_text += f"{idx}. {item['title']} (Link: {item['link']})\n"

    prompt = f"""
    Role: Senior Stock Analyst (Peter Lynch Style).
    Ticker: {ticker}
    
    Here are the latest news headlines:
    {news_text}
    
    Task:
    1. Analyze the aggregate sentiment (Bullish 🟢 / Bearish 🔴 / Neutral ⚪).
    2. Summarize the MOST critical impact in 1-2 bullet points.
    3. Ignore repetitive noise.
    
    Output Format:
    [Sentiment Icon] {ticker} Update
    • [Summary of key event]
    """
    
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    try:
        response = requests.post(api_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=20)
        
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        elif response.status_code == 429:
            print(f"      ⚠️ Quota Limit (429).")
            return "SKIP_QUOTA"
        else:
            print(f"      ❌ API Error {response.status_code}: {response.text}")
            return None
    except Exception as e:
        print(f"      ❌ Connection Error: {e}")
        return None

def main():
    print(f"[{datetime.now()}] Starting Watchdog v9.0 (Batch Mode + 1.5 Flash)...")
    
    history = load_history()
    print(f"Loaded {len(history)} history items.")
    
    new_alerts = 0
    
    for ticker in WATCHLIST:
        print(f"--------------------------------------------------")
        print(f"Checking {ticker}...", end=" ")
        
        # 1. 獲取新聞
        raw_news = get_google_rss_news(ticker)
        if not raw_news:
            raw_news = get_yfinance_news(ticker)
            
        # 2. 過濾已讀新聞
        fresh_news = []
        for item in raw_news:
            clean_url = item.get('link').split('?')[0]
            if clean_url not in history:
                fresh_news.append(item)
        
        print(f"Found {len(fresh_news)} NEW items.")
        
        if not fresh_news:
            continue

        # 3. 批次分析 (Batch Analysis)
        # 只取前 3 條最新的來分析，避免 Token 過長
        target_news = fresh_news[:3]
        
        print(f"   -> Batch analyzing {len(target_news)} items...")
        analysis = call_gemini_batch(ticker, target_news)
        
        if analysis == "SKIP_QUOTA":
            print("      ⚠️ Quota hit, stopping batch.")
            break
            
        if analysis:
            # 構建消息：AI 分析 + 來源鏈接
            links_md = "\n".join([f"[Source {i+1}]({n['link']})" for i, n in enumerate(target_news)])
            msg = f"{analysis}\n\n{links_md}"
            
            send_telegram_message(msg)
            new_alerts += 1
            
            # 更新歷史
            for item in target_news:
                history.add(item.get('link').split('?')[0])
                
            # 冷卻時間：雖然用了 Batch，還是休息 5 秒比較保險
            time.sleep(5)
        else:
            print("      ❌ AI Analysis Failed")

    save_history(history)
    print(f"--------------------------------------------------")
    print(f"Done. Sent {new_alerts} alerts.")

if __name__ == "__main__":
    main()
