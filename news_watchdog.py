import time
import json
import re
import os
import random
from datetime import datetime
import requests
from bot import send_telegram_message

# ================= 設定區 =================
WATCHLIST = ['HIMS', 'ZETA', 'ODDITY', 'NVDA', 'TSLA', 'AMD', 'OSCR']

NEWS_API_KEY = os.getenv('NEWS_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# 可由 GitHub Actions secrets/env 覆蓋,毋須改 code
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')
# 'auto' = 試 Gemini,失敗就 fallback;'rules' = 完全唔用 Gemini;'gemini' = 強制只用 Gemini
ANALYSIS_MODE = os.getenv('ANALYSIS_MODE', 'auto').lower()
# 配額耗盡時是否照樣推送 fallback 結果(預設 false,只記錄唔 spam)
NOTIFY_ON_FALLBACK = os.getenv('NOTIFY_ON_FALLBACK', 'false').lower() == 'true'
# 配額耗盡時 send 一次 admin 通知
QUOTA_ADMIN_NOTIFIED_FLAG = '/tmp/.gemini_quota_notified'

SCAN_INTERVAL = 900
HISTORY_FILE = 'news_history.json'

# Gemini 重試策略:只對「真係短暫」嘅 429 (有合理 retryDelay) 重試
MAX_GEMINI_RETRIES = 2
BASE_BACKOFF_SECONDS = 4

# ================= 狀態 =================
# 一旦判定為硬性配額耗盡(daily quota / limit:0),今次 run 完全停用 Gemini
_gemini_disabled_for_run = False
_gemini_disabled_reason = ''


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return set(json.load(f))
    return set()


def save_history(history_set):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(history_set), f, ensure_ascii=False, indent=4)


def get_latest_news(ticker):
    if not NEWS_API_KEY:
        return []
    url = "https://newsapi.org/v2/everything"
    params = {
        'q': f'("{ticker}" AND "stock") OR ("{ticker}" AND "earnings") OR ("{ticker}" AND "revenue")',
        'sortBy': 'publishedAt',
        'language': 'en',
        'pageSize': 3,
        'apiKey': NEWS_API_KEY,
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if response.status_code == 200:
            return data.get('articles', [])
        print(f"❌ [News API] 抓取 {ticker} 失敗: {data.get('message', '未知錯誤')}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"❌ [網絡錯誤] 抓取 {ticker} 失敗: {e}")
        return []


# ================= Gemini 錯誤分類 =================
def _classify_gemini_error(err):
    """
    回傳 (kind, retry_after_seconds_or_None)
      kind:
        'hard_quota'   -> daily/free-tier limit:0 之類, 今次 run 應該完全停用
        'transient'    -> 短暫 RPM 限制, 可以等少少再試
        'auth'         -> key 錯/未啟用 API
        'other'        -> 其他, 唔重試
    """
    text = str(err)
    low = text.lower()

    # 嘗試由 SDK exception attribute 攞 status code
    status = getattr(err, 'code', None) or getattr(err, 'status_code', None)
    if status is None:
        m = re.search(r'\b(4\d\d|5\d\d)\b', text)
        if m:
            try:
                status = int(m.group(1))
            except ValueError:
                status = None

    is_429 = status == 429 or 'resource_exhausted' in low or '429' in text

    if is_429:
        # limit: 0 = free tier 完全冇額,唔係短暫
        if re.search(r'limit:\s*0\b', text) or 'free_tier' in low or 'perdayper' in low.replace(' ', ''):
            # 再睇 retryDelay,若 >= 30s 通常都係 daily quota
            return ('hard_quota', None)
        # 試攞 retryDelay
        m = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+)s", text)
        if m:
            delay = int(m.group(1))
            if delay >= 60:
                return ('hard_quota', None)
            return ('transient', delay)
        return ('transient', None)

    if status in (401, 403) or 'permission' in low or 'api key not valid' in low or 'unauthenticated' in low:
        return ('auth', None)

    if status and 500 <= status < 600:
        return ('transient', None)

    return ('other', None)


def _rule_based_analysis(ticker, title, description):
    """
    Gemini 唔得用嘅時候嘅備胎:用關鍵字打分,只認真重大字眼先返非 SKIP。
    保守策略: 寧可漏推, 唔好 spam。
    """
    text = f"{title or ''} {description or ''}".lower()
    if not text.strip():
        return "SKIP"

    strong_signals = {
        'earnings beat': '財報超預期',
        'beats estimates': '財報超預期',
        'beat estimates': '財報超預期',
        'tops estimates': '財報超預期',
        'misses estimates': '財報遜預期',
        'cuts guidance': '下修指引',
        'raises guidance': '上調指引',
        'guidance raised': '上調指引',
        'acquires': '重大併購',
        'acquisition of': '重大併購',
        'merger': '重大併購',
        'fda approval': 'FDA 批准',
        'fda approves': 'FDA 批准',
        'recall': '產品召回',
        'lawsuit': '重大訴訟',
        'investigation': '監管調查',
        'bankruptcy': '破產風險',
        'ceo resigns': 'CEO 辭職',
        'ceo steps down': 'CEO 辭職',
        'stock split': '股票拆分',
        'dividend': '股息變動',
    }

    for kw, label in strong_signals.items():
        if kw in text:
            return f"🚨 [核心觸發] {ticker} 偵測到「{label}」訊號(規則引擎,未經 AI 確認,請自行核實)。"

    return "SKIP"


def analyze_news_gemini(ticker, title, description):
    """
    嘗試呼叫 Gemini;按錯誤類型分類重試/降級。
    """
    global _gemini_disabled_for_run, _gemini_disabled_reason

    if ANALYSIS_MODE == 'rules':
        return _rule_based_analysis(ticker, title, description)

    if _gemini_disabled_for_run:
        if ANALYSIS_MODE == 'gemini':
            return "SKIP"
        return _rule_based_analysis(ticker, title, description)

    if not GEMINI_API_KEY or GEMINI_API_KEY == '在此填入你的新_API_KEY':
        _gemini_disabled_for_run = True
        _gemini_disabled_reason = '未設定 GEMINI_API_KEY'
        if ANALYSIS_MODE == 'gemini':
            return "SKIP"
        return _rule_based_analysis(ticker, title, description)

    # 縮短 prompt + 摘要,慳 token
    short_desc = (description or '')[:280]
    short_title = (title or '')[:160]
    prompt = (
        f"以彼得·林區 + GARP 角度分析 {ticker}:\n"
        f"標題:{short_title}\n摘要:{short_desc}\n\n"
        "若有重大基本面影響(財報超預期/重大併購/護城河改變),用 1-2 句中文摘要,前綴 \"🚨 [核心觸發]\";"
        "否則只輸出 SKIP。"
    )

    try:
        from google import genai
    except ImportError as e:
        print(f"⚠️ [Gemini SDK] 未安裝 google-genai: {e}")
        _gemini_disabled_for_run = True
        _gemini_disabled_reason = 'SDK 未安裝'
        if ANALYSIS_MODE == 'gemini':
            return "SKIP"
        return _rule_based_analysis(ticker, title, description)

    last_err = None
    for attempt in range(MAX_GEMINI_RETRIES + 1):
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            return (response.text or 'SKIP').strip()
        except Exception as e:
            last_err = e
            kind, retry_after = _classify_gemini_error(e)
            if kind == 'hard_quota':
                _gemini_disabled_for_run = True
                _gemini_disabled_reason = f'Gemini 配額耗盡 (model={GEMINI_MODEL}): {str(e)[:200]}'
                print(f"⛔ [Gemini API] 已停用本次 run:{_gemini_disabled_reason}")
                _notify_admin_once_about_quota(_gemini_disabled_reason)
                break
            if kind == 'auth':
                _gemini_disabled_for_run = True
                _gemini_disabled_reason = f'Gemini 認證失敗: {str(e)[:200]}'
                print(f"⛔ [Gemini API] 認證失敗,已停用本次 run。")
                _notify_admin_once_about_quota(_gemini_disabled_reason)
                break
            if kind == 'transient' and attempt < MAX_GEMINI_RETRIES:
                sleep_s = retry_after if retry_after else BASE_BACKOFF_SECONDS * (2 ** attempt)
                # 加少少 jitter,避免幾隻 ticker 同時撞牆
                sleep_s += random.uniform(0, 1.5)
                print(f"⏳ [Gemini API] 短暫 429/5xx,等 {sleep_s:.1f}s 後重試 ({attempt + 1}/{MAX_GEMINI_RETRIES})")
                time.sleep(sleep_s)
                continue
            print(f"⚠️ [Gemini API] 分析失敗 (kind={kind}): {str(e)[:300]}")
            break

    # 行到呢度即係失敗
    if ANALYSIS_MODE == 'gemini':
        return "SKIP"
    fallback = _rule_based_analysis(ticker, title, description)
    if fallback != "SKIP":
        print(f"🛟 [Fallback] 規則引擎為 {ticker} 產生訊號(Gemini 不可用)。")
    return fallback


def _notify_admin_once_about_quota(reason):
    """單次 run 內最多 push 一次 admin 通知,避免洗版。"""
    if os.path.exists(QUOTA_ADMIN_NOTIFIED_FLAG):
        return
    try:
        with open(QUOTA_ADMIN_NOTIFIED_FLAG, 'w') as f:
            f.write(reason)
    except OSError:
        pass
    msg = (
        "⚠️ *News Watchdog 通知*\n"
        "━━━━━━━━━━━━━━━\n"
        f"Gemini 不可用,本次掃描已切換到規則引擎 fallback。\n\n"
        f"原因:`{reason[:300]}`\n\n"
        "建議:檢查 Google AI Studio 配額/帳單,或將 `GEMINI_MODEL` env "
        "改為其他模型(例如 `gemini-1.5-flash`),或將 `ANALYSIS_MODE` 設為 `rules`。"
    )
    try:
        send_telegram_message(msg)
    except Exception as e:
        print(f"⚠️ 無法發送 admin 通知: {e}")


def format_telegram_message(ticker, analysis, url):
    if "財報" in analysis or "earnings" in analysis.lower():
        emoji = "📊"
    elif "併購" in analysis or "收購" in analysis:
        emoji = "🤝"
    else:
        emoji = "⚡"
    return (
        f"*{emoji} {ticker} 投資快訊*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{analysis}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔗 [點擊閱讀完整報導]({url})"
    )


def start_watchdog():
    print(f"👀 新聞看門狗 (GitHub Actions 版) 開始執行單次掃描... mode={ANALYSIS_MODE} model={GEMINI_MODEL}")

    seen_urls = load_history()

    for ticker in WATCHLIST:
        articles = get_latest_news(ticker)

        for article in articles:
            url = article.get('url')
            if not url or url in seen_urls:
                continue

            title = article.get('title') or ''
            desc = article.get('description', '') or ''
            analysis = analyze_news_gemini(ticker, title, desc)

            if "SKIP" in analysis:
                print(f"🗑️ 過濾雜訊: {ticker} - {title[:25]}...")
                seen_urls.add(url)
                continue

            is_fallback = "規則引擎" in analysis
            if is_fallback and not NOTIFY_ON_FALLBACK:
                print(f"🤐 [Fallback 不推送] {ticker}: {analysis}")
                seen_urls.add(url)
                continue

            msg = format_telegram_message(ticker, analysis, url)
            send_telegram_message(msg)
            print(f"✅ 已推送 {ticker} 重大新聞!")
            seen_urls.add(url)

        time.sleep(2)

    save_history(seen_urls)
    print("🏁 單次掃描完成,程式結束。")


if __name__ == "__main__":
    start_watchdog()
