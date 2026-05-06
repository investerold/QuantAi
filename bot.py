import os
import requests

def send_telegram_message(message):
    """
    發送訊息到 Telegram
    """
    # 名字必須與 YAML 檔裡的 env 設定完全一致
    token = os.getenv('TELEGRAM_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    
    if not token or not chat_id:
        print("❌ [Telegram] 缺少 TELEGRAM_TOKEN 或 TELEGRAM_CHAT_ID 環境變數！")
        return
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown" 
    }
    
    try:
        response = requests.post(url, data=data, timeout=10)
        if response.status_code != 200:
            print(f"❌ [Telegram] 訊息發送失敗: {response.text}")
    except Exception as e:
        print(f"❌ [Telegram] 發生錯誤: {e}")
