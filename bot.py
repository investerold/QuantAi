import requests

# 你的真實數據
BOT_TOKEN = '7704840412:AAEhKpJPdbcUJI83lfLxa3HDnw8PxeVGdYM'
CHAT_ID = '1697709207'

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"發送失敗: {e}")
