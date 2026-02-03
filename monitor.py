import requests
import xml.etree.ElementTree as ET
import os
import time

# --- 配置區 ---
# 針對你的 GARP 關注名單優化
WATCHLIST = {
    'ZETA': 'Zeta Global',       
    'ODD':  'Oddity Tech',       
    'HIMS': 'Hims & Hers',       
    'OSCR': 'Oscar Health',      
    'TSLA': 'Tesla',             
}

TELEGRAM_TOKEN = os.environ.get('TG_TOKEN')
CHAT_ID = os.environ.get('TG_CHAT_ID')
HISTORY_FILE = "processed_filings.txt" # 用於存儲已處理過的鏈接

def send_telegram_msg(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Error: TG_TOKEN or TG_CHAT_ID not set.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Msg failed: {e}")

def load_processed_filings():
    """讀取歷史記錄，防止重複發送"""
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r") as f:
        return set(line.strip() for line in f)

def save_processed_filing(link):
    """將新處理的鏈接寫入文件"""
    with open(HISTORY_FILE, "a") as f:
        f.write(f"{link}\n")

def check_sec_filings():
    url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&CIK=&type=4&company=&dateb=&owner=include&start=0&count=100&output=atom"
    
    # 這是你的身份標識，保持這樣很好
    headers = {
        'User-Agent': 'HKBU_Student_Project/1.0 (jeffy_trader@hkbu.edu.hk)',
        'Accept-Encoding': 'gzip, deflate',
        'Host': 'www.sec.gov'
    }
    
    processed_links = load_processed_filings()
    
    try:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Fetching SEC data...")
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            print(f"Error: SEC returned status code {response.status_code}")
            return

        root = ET.fromstring(response.content)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        
        found_count = 0
        
        # 為了即時性，我們反向遍歷（雖然 RSS 通常是最新的在前，但在處理歷史記錄時邏輯更清晰）
        entries = root.findall('atom:entry', ns)
        
        for entry in entries:
            title = entry.find('atom:title', ns).text
            link = entry.find('atom:link', ns).attrib['href']
            
            # 1. 檢查是否已經處理過 (去重核心)
            if link in processed_links:
                continue

            # 2. 關鍵字匹配
            for ticker, keyword in WATCHLIST.items():
                if keyword.lower() in title.lower():
                    print(f"🔥 Found match: {ticker}")
                    
                    # 3. 構建更適合交易員的消息格式
                    msg = (
                        f"🚨 **Insider Activity Detected!**\n\n"
                        f"**Ticker:** #{ticker}\n"
                        f"**Entity:** {keyword}\n" # 顯示觸發的關鍵字
                        f"**Raw Title:** `{title}`\n"
                        f"-----------------------------\n"
                        f"[View Official Filing]({link})\n"
                        f"[Yahoo Finance](https://finance.yahoo.com/quote/{ticker})"
                    )
                    
                    send_telegram_msg(msg)
                    save_processed_filing(link) # 標記為已處理
                    processed_links.add(link)   # 更新內存中的集合
                    found_count += 1
                    break # 匹配到一個關鍵字就跳出內層循環，避免重複匹配
        
        print(f"Check complete. New alerts sent: {found_count}")
                        
    except Exception as e:
        print(f"Critical Error: {e}")

if __name__ == "__main__":
    check_sec_filings()
