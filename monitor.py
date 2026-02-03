import requests
import xml.etree.ElementTree as ET
import os
from datetime import datetime, timedelta, timezone
from dateutil import parser
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# --- 配置區 ---
WATCHLIST = {
    'ZETA': 'Zeta Global',
    'ODD':  'Oddity Tech',
    'HIMS': 'Hims & Hers',
    'OSCR': 'Oscar Health',
}

TELEGRAM_TOKEN = os.environ.get('TG_TOKEN')
CHAT_ID = os.environ.get('TG_CHAT_ID')

# 配合 Cron Job 頻率 (例如每 15 分鐘跑一次，這裡設 20 分鐘作為緩衝)
LOOKBACK_MINUTES = 1440

# 必須遵守 SEC 的 User-Agent 格式: AppName/Version (Email)
HEADERS = {
    'User-Agent': 'HKBU_Student_Insider_Monitor/1.0 (jeffy_trader@hkbu.edu.hk)',
    'Accept-Encoding': 'gzip, deflate',
    'Host': 'www.sec.gov'
}

def send_telegram_msg(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ Error: TG_TOKEN or TG_CHAT_ID not set.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID, 
        "text": message, 
        "parse_mode": "Markdown", 
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Msg failed: {e}")

def get_xml_link(index_url):
    """
    從 SEC 索引頁面中找到真正的 XML 文件鏈接
    """
    try:
        r = requests.get(index_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.content, 'html.parser')
        
        # 在表格中尋找 XML 文件
        # 通常在 Document Format Files 表格中，Type 為 '4' 且 Document 結尾是 .xml
        for row in soup.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) > 3:
                doc_text = cells[2].text.strip() # Document description
                href_tag = cells[2].find('a')
                if href_tag and href_tag['href'].endswith('.xml'):
                    return urljoin('https://www.sec.gov', href_tag['href'])
        return None
    except Exception as e:
        print(f"Error finding XML link: {e}")
        return None

def get_transaction_details(filing_url):
    """
    先進入索引頁，找到 XML，再解析交易數據
    """
    # 1. 嘗試獲取 XML 鏈接
    xml_url = get_xml_link(filing_url)
    
    if not xml_url:
        return "⚠️ Could not auto-parse (XML not found). Please check link manually.", "UNKNOWN"

    try:
        # 2. 請求 XML 數據
        r = requests.get(xml_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.content, 'xml') # 使用 xml parser
        
        xml_data = soup.find_all('nonDerivativeTransaction')
        
        if not xml_data:
            return "ℹ️ No Non-Derivative Transactions (Possibly Options/Grants only)", "NEUTRAL"

        total_buy_val = 0
        total_sell_val = 0
        shares_bought = 0
        shares_sold = 0
        
        for trans in xml_data:
            try:
                # 獲取交易代碼
                code_tag = trans.find('transactionCode')
                code = code_tag.get('transactionCode') if code_tag else None
                
                # 如果屬性拿不到，嘗試拿內容
                if not code and trans.find('transactionCoding'):
                     code = trans.find('transactionCoding').find('transactionCode').text

                if not code: continue

                # 獲取股數
                shares_node = trans.find('transactionShares')
                shares_val = float(shares_node.find('value').text) if shares_node else 0
                
                # 獲取價格
                price_node = trans.find('transactionPricePerShare')
                price_val = 0
                if price_node and price_node.find('value'):
                    price_val = float(price_node.find('value').text)
                
                # 忽略價格為 0 的 (贈予/行權)
                if price_val == 0: continue

                if code == 'P': # Purchase
                    shares_bought += shares_val
                    total_buy_val += (shares_val * price_val)
                elif code == 'S': # Sale
                    shares_sold += shares_val
                    total_sell_val += (shares_val * price_val)
                    
            except Exception as e:
                continue 

        summary = ""
        signal_type = "NEUTRAL"
        
        if total_buy_val > 0:
            summary += f"🟢 **BUY**: {int(shares_bought):,} shares (~${int(total_buy_val):,})\n"
            signal_type = "BUY"
        
        if total_sell_val > 0:
            summary += f"🔴 **SELL**: {int(shares_sold):,} shares (~${int(total_sell_val):,})\n"
            if signal_type == "BUY": signal_type = "MIXED"
            elif signal_type == "NEUTRAL": signal_type = "SELL"
                
        if summary == "":
            summary = "ℹ️ Manual Check Required (Complex Transaction)"
            
        return summary, signal_type

    except Exception as e:
        print(f"Parse Error: {e}")
        return "⚠️ Parsing Error", "ERROR"

def check_sec_filings():
    # SEC Atom Feed for Form 4
    url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&CIK=&type=4&company=&dateb=&owner=include&start=0&count=100&output=atom"
    
    try:
        print(f"[{datetime.now(timezone.utc)}] Fetching SEC data...")
        response = requests.get(url, headers=HEADERS, timeout=20)
        
        if response.status_code != 200:
            print(f"Error: SEC returned status code {response.status_code}")
            return

        # 這裡需要處理 namespace，因為 SEC Atom feed 有 namespace
        # 但 ElementTree find 比較麻煩，為了簡單，我們用 BS4 解析 Atom XML 也可以
        # 或者用簡單的字符串替換去掉 namespace (最快的方法)
        xml_content = response.content.decode('utf-8')
        # 簡單粗暴移除 namespace 以方便解析
        xml_content = xml_content.replace('xmlns="http://www.w3.org/2005/Atom"', '')
        
        root = ET.fromstring(xml_content)
        
        now_utc = datetime.now(timezone.utc)
        found_count = 0
        
        for entry in root.findall('entry'):
            title = entry.find('title').text
            link = entry.find('link').attrib['href']
            updated_str = entry.find('updated').text
            
            # 解析時間
            updated_time = parser.parse(updated_str)
            # 確保時區一致
            if updated_time.tzinfo is None:
                updated_time = updated_time.replace(tzinfo=timezone.utc)
            
            time_diff = now_utc - updated_time
            
            # 時間過濾
            if time_diff > timedelta(minutes=LOOKBACK_MINUTES):
                continue

            # 關鍵字匹配
            for ticker, company_name in WATCHLIST.items():
                if company_name.lower() in title.lower():
                    print(f"🔥 Found match: {ticker} - {title}")
                    
                    details, signal = get_transaction_details(link)
                    
                    # 只有真的有交易金額才發送 (過濾掉純粹的 Grant/Option 0元交易，看個人需求)
                    if signal == "NEUTRAL" and "Manual Check" not in details:
                        print(f"Skipping {ticker} (No market value transaction)")
                        continue

                    emoji = "📢"
                    if signal == "BUY": emoji = "🟢 STRONG BUY"
                    elif signal == "SELL": emoji = "🔴 SELL"
                    elif signal == "MIXED": emoji = "🟡 MIXED"
                    
                    # 嘗試提取 Insider 名字
                    insider = title.split('(')[0].strip()
                    
                    msg = (
                        f"{emoji} **Insider Activity: {ticker}**\n\n"
                        f"**Insider:** {insider}\n"
                        f"**Signal:** {signal}\n"
                        f"-----------------------------\n"
                        f"{details}\n"
                        f"-----------------------------\n"
                        f"🕒 {updated_time.strftime('%H:%M UTC')}\n"
                        f"[View Filing]({link})"
                    )
                    
                    send_telegram_msg(msg)
                    found_count += 1
                    # 找到一個匹配就 break inner loop，避免同一個 entry 觸發多次 (雖然不太可能)
                    break 
        
        print(f"Check complete. New alerts sent: {found_count}")
                        
    except Exception as e:
        print(f"Critical Error: {e}")
        # 在 GitHub Actions 失敗時拋出錯誤，讓 Log 變紅
        exit(1)

if __name__ == "__main__":
    check_sec_filings()

