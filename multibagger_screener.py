import os
import sys
import time
import requests
from bs4 import BeautifulSoup

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SCREENER_URL = os.getenv("SCREENER_URL")

# Comprehensive headers to mimic an authentic browser session
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.screener.in/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}

def clean_float(val: str) -> float:
    if not val:
        return 0.0
    try:
        return float(val.replace(",", "").replace("%", "").strip())
    except (ValueError, AttributeError):
        return 0.0

def send_telegram_alert(message: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code != 200:
            print(f"Telegram API error {resp.status_code}: {resp.text}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"Failed to deliver Telegram notification: {e}", file=sys.stderr)
        return False

def fetch_screener_stocks(url: str) -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)
    page = 1
    stocks = []
    
    while True:
        page_url = f"{url}?page={page}" if "?" not in url else f"{url}&page={page}"
        print(f"Fetching: {page_url}")
        
        try:
            resp = session.get(page_url, timeout=20, allow_redirects=True)
        except Exception as e:
            print(f"Network error on page {page}: {e}", file=sys.stderr)
            break
            
        print(f"Status Code: {resp.status_code} | Final URL: {resp.url}")
        
        # Check if redirected to login
        if "/login/" in resp.url:
            print(
                "\n❌ ERROR: Screener.in redirected to the login page!\n"
                "Your screen is private. Please make the screen public or run it locally.",
                file=sys.stderr
            )
            break
            
        if resp.status_code != 200:
            print(f"Request failed with HTTP {resp.status_code}", file=sys.stderr)
            break
            
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", class_="data-table")
        
        if not table:
            print("No table with class 'data-table' found in the response.")
            break
            
        tbody = table.find("tbody")
        if not tbody:
            break
            
        rows = tbody.find_all("tr")
        if not rows:
            break
            
        for row in rows:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cols) >= 6:
                # Extracts values based on visible columns
                stocks.append({
                    "name": cols[1],
                    "cmp": cols[2],
                    "pe": cols[3],
                    "mcap": cols[4],
                    "profit_growth": cols[5],
                    "cfo": cols[6] if len(cols) > 6 else "0",
                    "pat": cols[7] if len(cols) > 7 else "0"
                })
        
        # Check for pagination
        next_button = soup.find("a", string=lambda t: t and "Next" in t)
        if not next_button:
            break
            
        page += 1
        time.sleep(1.5)
        
    return stocks

def evaluate_cash_flow_health(stock: dict) -> tuple[str, str]:
    cfo = clean_float(stock.get("cfo", "0"))
    pat = clean_float(stock.get("pat", "0"))
    
    if cfo <= 0:
        return "⚠️", "Negative Cash Flow (CFO ≤ 0)"
    if pat > 0 and (cfo / pat) < 0.6:
        conversion = round((cfo / pat) * 100, 1)
        return "⚠️", f"Weak Conversion ({conversion}% PAT to CFO)"
    return "✅", "Strong Cash Conversion"

def send_chunked_alerts(stocks: list, chunk_size: int = 5):
    if not stocks:
        print("No matches to alert.")
        return

    total = len(stocks)
    total_parts = (total + chunk_size - 1) // chunk_size
    
    for idx in range(0, total, chunk_size):
        batch = stocks[idx:idx + chunk_size]
        part_num = (idx // chunk_size) + 1
        
        msg = f"📡 *Multibagger Discovery Alert* (Part {part_num}/{total_parts})\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        for s in batch:
            icon, status = evaluate_cash_flow_health(s)
            msg += f"🏢 *{s['name']}*\n"
            msg += f"• *Price:* ₹{s['cmp']} | *P/E:* {s['pe']}x\n"
            msg += f"• *MCap:* ₹{s['mcap']} Cr | *PAT Growth:* {s['profit_growth']}%\n"
            msg += f"• *Cash Health:* {icon} {status}\n\n"
            
        success = send_telegram_alert(msg)
        if success:
            print(f"Sent batch {part_num}/{total_parts} to Telegram.")
        time.sleep(1.5)

def main():
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SCREENER_URL]):
        print("Error: Missing environment variables.", file=sys.stderr)
        sys.exit(1)
        
    stocks = fetch_screener_stocks(SCREENER_URL)
    print(f"Total stocks extracted: {len(stocks)}")
    send_chunked_alerts(stocks, chunk_size=5)

if __name__ == "__main__":
    main()
