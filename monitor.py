import requests
import xml.etree.ElementTree as ET
import os

# --- 修正部分：使用「公司名稱關鍵字」而非代碼 ---
# 格式: "股票代碼": "SEC文件中的公司名稱關鍵字"
WATCHLIST = {
    'ZETA': 'Zeta Global',       # 抓 Zeta Global Holdings
    'ODD':  'Oddity Tech',       # 抓 Oddity Tech Ltd (解決找不到 ODD 的問題)
    'HIMS': 'Hims & Hers',       # 抓 Hims & Hers Health
    'OSCR': 'Oscar Health',      # 抓 Oscar Health, Inc.
    'TSLA': 'Tesla',             # 測試用
}

TELEGRAM_TOKEN = os.environ.get('TG_TOKEN')
CHAT_ID = os.environ.get('TG_CHAT_ID')

def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Msg failed: {e}")

def check_sec_filings():
    # 這是 SEC 官方的「最新 Form 4」RSS Feed
    url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&CIK=&type=4&company=&dateb=&owner=include&start=0&count=100&output=atom"
    
    # 必須偽裝成瀏覽器，否則 SEC 會擋
    headers = {
        'User-Agent': 'HKBU_Student_Project/1.0 (jeffy_trader@hkbu.edu.hk)',
        'Accept-Encoding': 'gzip, deflate',
        'Host': 'www.sec.gov'
    }
    
    try:
        print("Fetching SEC data...")
        response = requests.get(url, headers=headers, timeout=10)
        
        # 如果 SEC 伺服器拒絕 (403/404)，報錯
        if response.status_code != 200:
            print(f"Error: SEC returned status code {response.status_code}")
            return

        # 解析 XML
        root = ET.fromstring(response.content)
        ns = {'atom': 'http://www.w3.org/2005/Atom'} # 這是 XML 的命名空間
        
        found_count = 0
        
        # 遍歷每一份新文件
        for entry in root.findall('atom:entry', ns):
            title = entry.find('atom:title', ns).text
            link = entry.find('atom:link', ns).attrib['href']
            
            # --- 核心邏輯修正 ---
            # 檢查我們的 Watchlist 關鍵字是否出現在標題中
            for ticker, keyword in WATCHLIST.items():
                if keyword.lower() in title.lower():
                    print(f"Found match: {ticker} -> {title}")
                    
                    msg = (
                        f"🚨 **Insider Activity Detected!**\n\n"
                        f"**Stock:** #{ticker}\n"
                        f"**Company:** {title.split('(')[0].strip()}\n"
                        f"**Form:** SEC Form 4 (Insider Trade)\n\n"
                        f"[View Official Filing]({link})"
                    )
                    send_telegram_msg(msg)
                    found_count += 1
        
        print(f"Check complete. Found {found_count} relevant filings.")
                        
    except Exception as e:
        print(f"Critical Error: {e}")

if __name__ == "__main__":
    check_sec_filings()
