import requests
import xml.etree.ElementTree as ET
import os
import time
from datetime import datetime, timedelta, timezone
from dateutil import parser
from bs4 import BeautifulSoup
import re

# --- 配置區 ---
WATCHLIST = {
    'ZETA': 'Zeta Global',
    'ODD':  'Oddity Tech',
    'HIMS': 'Hims & Hers',
    'OSCR': 'Oscar Health',
    'TSLA': 'Tesla',
}

TELEGRAM_TOKEN = os.environ.get('TG_TOKEN')
CHAT_ID = os.environ.get('TG_CHAT_ID')

# 為了防止漏抓，保持 20 分鐘的回溯窗口 (配合 Cron 15分鐘)
LOOKBACK_MINUTES = 20

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

def get_transaction_details(filing_url):
    """
    深入解析 Form 4 文件，判斷是買入還是賣出
    """
    headers = {'User-Agent': 'HKBU_Student_Project/1.0 (jeffy_trader@hkbu.edu.hk)'}
    
    try:
        r = requests.get(filing_url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.content, 'lxml')
        
        # 現代 Form 4 通常將數據嵌入在 XML 標籤中，即使在 HTML 裡也能找到
        # 我們尋找 Non-Derivative Table (Table I)
        
        # 初始化統計
        total_buy_val = 0
        total_sell_val = 0
        shares_bought = 0
        shares_sold = 0
        
        # 查找所有交易行
        # SEC XML 標籤通常是 <transactionCoding> 包含 <transactionCode>
        # 我們直接用正則表達式或 BS4 查找特定結構更穩健
        
        # 策略：遍歷所有的 <nonDerivativeTransaction> 節點 (如果存在 XML 結構)
        # 或者簡單遍歷表格行。為了兼容性，我們嘗試解析 XML 數據塊。
        
        # 嘗試尋找 XML 數據 (最準確)
        xml_data = soup.find_all('nonderivativetransaction')
        
        if not xml_data:
            # 如果找不到 XML 標籤，這可能是一份舊格式文件或圖片，無法自動解析
            return "⚠️ Manual Check Required (No XML Data)", "UNKNOWN"

        for trans in xml_data:
            try:
                # 獲取交易代碼 (P=Buy, S=Sell)
                code_tag = trans.find('transactioncode')
                if code_tag:
                    code = code_tag.text.strip().upper()
                else:
                    continue

                # 獲取股數
                shares_tag = trans.find('transactionshares')
                shares_val = float(shares_tag.find('value').text) if shares_tag else 0
                
                # 獲取價格
                price_tag = trans.find('transactionpricepershare')
                price_val = float(price_tag.find('value').text) if price_tag and price_tag.find('value') else 0
                
                # 忽略價格為 0 的交易 (通常是贈予或行權轉換)
                if price_val == 0:
                    continue

                if code == 'P':
                    shares_bought += shares_val
                    total_buy_val += (shares_val * price_val)
                elif code == 'S':
                    shares_sold += shares_val
                    total_sell_val += (shares_val * price_val)
                    
            except Exception as e:
                continue # 忽略解析錯誤的單行

        # 構建結論
        summary = ""
        signal_type = "NEUTRAL"
        
        if total_buy_val > 0:
            summary += f"🟢 **BUY**: {int(shares_bought):,} shares (~${int(total_buy_val):,})\n"
            signal_type = "BUY"
        
        if total_sell_val > 0:
            summary += f"🔴 **SELL**: {int(shares_sold):,} shares (~${int(total_sell_val):,})\n"
            if signal_type == "BUY":
                signal_type = "MIXED" # 既買又賣
            elif signal_type == "NEUTRAL":
                signal_type = "SELL"
                
        if summary == "":
            summary = "ℹ️ Non-Open Market / Grant / Option Exercise"
            
        return summary, signal_type

    except Exception as e:
        print(f"Parse Error: {e}")
        return "⚠️ Parsing Error", "ERROR"

def check_sec_filings():
    url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&CIK=&type=4&company=&dateb=&owner=include&start=0&count=100&output=atom"
    
    headers = {
        'User-Agent': 'HKBU_Student_Project/1.0 (jeffy_trader@hkbu.edu.hk)',
        'Accept-Encoding': 'gzip, deflate',
        'Host': 'www.sec.gov'
    }
    
    try:
        print(f"[{datetime.now(timezone.utc)}] Fetching SEC data...")
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            print(f"Error: SEC returned status code {response.status_code}")
            return

        root = ET.fromstring(response.content)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        
        now_utc = datetime.now(timezone.utc)
        found_count = 0
        
        for entry in root.findall('atom:entry', ns):
            title = entry.find('atom:title', ns).text
            link = entry.find('atom:link', ns).attrib['href']
            
            # 時間過濾 (20分鐘內)
            updated_str = entry.find('atom:updated', ns).text
            updated_time = parser.parse(updated_str)
            time_diff = now_utc - updated_time
            
            if time_diff > timedelta(minutes=LOOKBACK_MINUTES):
                continue

            # 關鍵字匹配
            for ticker, keyword in WATCHLIST.items():
                if keyword.lower() in title.lower():
                    print(f"🔥 Found NEW match: {ticker}")
                    
                    # --- 進階解析 ---
                    details, signal = get_transaction_details(link)
                    
                    # 設置 Emoji 標題
                    emoji = "📢"
                    if signal == "BUY": emoji = "🟢 STRONG BUY"
                    elif signal == "SELL": emoji = "🔴 SELL"
                    elif signal == "MIXED": emoji = "🟡 MIXED"
                    
                    # 誰在交易? (從標題提取，通常格式: "Insiders Name (Issuer)")
                    insider_name = title.split('(')[0].strip()
                    
                    msg = (
                        f"{emoji} **Insider Activity: {ticker}**\n\n"
                        f"**Insider:** {insider_name}\n"
                        f"**Signal:** {signal}\n"
                        f"-----------------------------\n"
                        f"{details}\n"
                        f"-----------------------------\n"
                        f"🕒 {updated_time.strftime('%H:%M UTC')}\n"
                        f"[View Filing]({link}) | [Yahoo]({f'https://finance.yahoo.com/quote/{ticker}'})"
                    )
                    
                    send_telegram_msg(msg)
                    found_count += 1
                    break 
        
        print(f"Check complete. New alerts sent: {found_count}")
                        
    except Exception as e:
        print(f"Critical Error: {e}")

if __name__ == "__main__":
    check_sec_filings()
