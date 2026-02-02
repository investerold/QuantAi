import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import os

# 1. 設定你的關注列表 (Watchlist)
MY_STOCKS = ['ZETA', 'ODD', 'HIMS', 'OSCR']

# 2. 設定 Telegram Bot (稍後在Telegram申請，免費的)
TELEGRAM_TOKEN = os.environ.get('TG_TOKEN') # 從GitHub Secrets讀取
CHAT_ID = os.environ.get('TG_CHAT_ID')

def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def check_sec_filings():
    # SEC Form 4 的 RSS Feed (只看 Form 4 和 4/A)
    url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&CIK=&type=4&company=&dateb=&owner=include&start=0&count=100&output=atom"
    
    # 必須加上 User-Agent，否則 SEC 會擋
    headers = {'User-Agent': 'HKBU_Student_Project/1.0 (your_email@life.hkbu.edu.hk)'}
    
    try:
        response = requests.get(url, headers=headers)
        root = ET.fromstring(response.content)
        
        # 解析每一份新文件
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        for entry in root.findall('atom:entry', ns):
            title = entry.find('atom:title', ns).text
            link = entry.find('atom:link', ns).attrib['href']
            summary = entry.find('atom:summary', ns).text
            
            # 檢查標題中是否包含你的股票代碼
            # 標題格式通常是: "4 - Zeta Global Holdings Corp. (0001855631) (Issuer)"
            for ticker in MY_STOCKS:
                # 這裡做一個簡單的匹配，實際運作可能需要獲取CIK對照表以求精確，但文字匹配對小列表足夠
                if ticker in title or ticker in summary: 
                    # 這裡可以進一步加邏輯：讀取數據庫看是否已發送過，避免重複
                    msg = f"🚨 **Insider Alert: {ticker}**\n\n發現新的 Form 4 文件！\n[點擊查看 SEC 文件]({link})"
                    print(msg)
                    if TELEGRAM_TOKEN:
                        send_telegram_msg(msg)
                        
    except Exception as e:
        print(f"Error: {e}")

# ... 上面的代碼不用動 ...

if __name__ == "__main__":
    print("Starting monitor...")
    
    # --- 這是新增的測試代碼 ---
    try:
        test_msg = "✅ **System Check**: Monitor is running! (這是測試訊息)"
        print("Attempting to send test message...")
        send_telegram_msg(test_msg)
        print("Test message sent.")
    except Exception as e:
        print(f"Failed to send test message: {e}")
    # ------------------------

    check_sec_filings()


