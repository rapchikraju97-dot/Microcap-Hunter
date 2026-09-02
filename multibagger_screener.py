import os
import sys
import time
import requests
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from bs4 import BeautifulSoup

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SCREENER_URL = os.getenv("SCREENER_URL")

BASE_URL = "https://www.screener.in"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.screener.in/",
    "Upgrade-Insecure-Requests": "1"
}

# Thematic catalyst taxonomy
CATALYST_TAXONOMY = {
    "Capital Goods & Defense": {
        "keywords": ["defense", "aerospace", "valve", "pump", "casting", "forging", "machining", "cnc", "industrial machinery", "tool"],
        "tailwinds": [
            "Localization & Import Substitution: Direct beneficiary of defense indigenization and Make in India.",
            "Capex Cycle: Operating leverage accelerating as domestic factory utilization approaches peaks."
        ]
    },
    "Power, Solar & Green Transition": {
        "keywords": ["power", "solar", "transformer", "cable", "wire", "switchgear", "grid", "renewable", "substation"],
        "tailwinds": [
            "Grid Modernization: Transmission & distribution Capex expanding to support renewable capacity.",
            "High Order Book: Multi-year revenue visibility backed by utility and private power tenders."
        ]
    },
    "Chemicals & Specialized Materials": {
        "keywords": ["chemical", "specialty chemical", "intermediate", "agrochem", "api", "pharma", "polymer"],
        "tailwinds": [
            "China+1 De-risking: Global supply chains diversifying strategic chemical intermediate sourcing.",
            "Margin Expansion: Raw material input normalization driving earnings recovery."
        ]
    },
    "Infrastructure & Specialized Civil": {
        "keywords": ["rail", "wagon", "tunnel", "bridge", "highway", "port", "logistics", "civil construction", "infrastructure"],
        "tailwinds": [
            "National Infra Pipeline: Large public allocation toward strategic transit and dedicated corridors.",
            "Niche Moat: Difficult-terrain civil engineering commands higher margin vs generic road builders."
        ]
    },
    "Auto Ancillaries & Precision Parts": {
        "keywords": ["auto ancillary", "bearing", "gear", "piston", "ev", "electric vehicle", "transmission", "sheet metal"],
        "tailwinds": [
            "Second-Order Engine: OEM production surge drives ancillary kit-value growth.",
            "Premiumization: Shift to high-precision engineering parts expanding gross margins."
        ]
    }
}

def clean_float(val: str) -> float:
    if not val:
        return 0.0
    try:
        return float(val.replace(",", "").replace("%", "").strip())
    except (ValueError, AttributeError):
        return 0.0

def build_page_url(base_url: str, page: int) -> str:
    url_parts = list(urlparse(base_url.strip()))
    query = parse_qs(url_parts[4])
    query["page"] = [str(page)]
    url_parts[4] = urlencode(query, doseq=True)
    return urlunparse(url_parts)

def send_telegram_alert(message: str) -> bool:
    token = (TELEGRAM_BOT_TOKEN or "").strip().replace('"', '').replace("'", "")
    if token.lower().startswith("bot"):
        token = token[3:]
    
    chat_id = str(TELEGRAM_CHAT_ID or "").strip().replace('"', '').replace("'", "")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code != 200:
            print(f"Telegram API Error {resp.status_code}: {resp.text}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"Failed to deliver Telegram notification: {e}", file=sys.stderr)
        return False

def get_company_profile(session: requests.Session, company_path: str) -> tuple[str, str]:
    if not company_path:
        return "Niche Manufacturing", "Supplier to core industrial sectors."
        
    full_url = BASE_URL + company_path if company_path.startswith("/") else f"{BASE_URL}/{company_path}"
    try:
        resp = session.get(full_url, timeout=10)
        if resp.status_code != 200:
            return "Niche Manufacturing", "Supplier to core industrial sectors."
            
        soup = BeautifulSoup(resp.text, "html.parser")
        
        sector = "Industrial Ancillary"
        peers_section = soup.find("section", id="peers")
        if peers_section:
            sector_tag = peers_section.find("a", href=lambda h: h and "/market/" in h)
            if sector_tag:
                sector = sector_tag.get_text(strip=True)

        about_div = soup.find("div", class_="about") or soup.find("div", class_="company-profile")
        description = "Industrial supplier"
        if about_div:
            p_tag = about_div.find("p")
            if p_tag:
                description = p_tag.get_text(strip=True)
                
        return sector, description
    except Exception:
        return "Industrial Ancillary", "Supplier to core industrial sectors."

def fetch_screener_stocks(url: str) -> tuple[list[dict], requests.Session]:
    session = requests.Session()
    session.headers.update(HEADERS)
    page = 1
    stocks = []
    
    while True:
        page_url = build_page_url(url, page)
        try:
            resp = session.get(page_url, timeout=20, allow_redirects=True)
        except Exception as e:
            print(f"Network error on page {page}: {e}", file=sys.stderr)
            break
            
        if resp.status_code != 200 or "/login/" in resp.url:
            break
            
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", class_="data-table")
        if not table:
            tables = soup.find_all("table")
            if tables:
                table = tables[0]
            else:
                break
                
        thead = table.find("thead")
        headers = [th.get_text(strip=True).lower() for th in thead.find_all("th")] if thead else []

        def locate(candidates):
            for cand in candidates:
                for idx, h in enumerate(headers):
                    if cand in h:
                        return idx
            return -1

        idx_name = locate(["name"])
        idx_cmp = locate(["cmp", "current price", "price"])
        idx_pe = locate(["p/e", "price to earning"])
        idx_mcap = locate(["mar cap", "market capitalization", "market cap"])
        idx_growth = locate(["yoy quarterly profit", "qtr profit var", "profit growth"])
        idx_cfo = locate(["cash from operations last year", "cfo last year", "cfo"])
        idx_pat = locate(["profit after tax latest quarter", "net profit latest quarter", "profit after tax", "pat"])

        tbody = table.find("tbody") or table
        rows = tbody.find_all("tr")
        data_rows = [r for r in rows if r.find_all("td")]

        if not data_rows:
            break

        for row in data_rows:
            tds = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(tds) < 3:
                continue

            link_tag = row.find("a", href=True)
            company_href = link_tag["href"] if link_tag else ""

            def get_val(col_idx, fallback_idx, default="N/A"):
                if col_idx != -1 and col_idx < len(tds):
                    return tds[col_idx]
                if fallback_idx < len(tds):
                    return tds[fallback_idx]
                return default

            stocks.append({
                "name": get_val(idx_name, 1, "Unknown"),
                "href": company_href,
                "cmp": get_val(idx_cmp, 2, "N/A"),
                "pe": get_val(idx_pe, 3, "N/A"),
                "mcap": get_val(idx_mcap, 4, "N/A"),
                "profit_growth": get_val(idx_growth, 5, "0.00"),
                "cfo": get_val(idx_cfo, 6, "0"),
                "pat": get_val(idx_pat, 7, "0")
            })
        
        if len(data_rows) < 25:
            break
            
        page += 1
        time.sleep(1.5)
        
    return stocks, session

def passes_conviction_gate(stock: dict) -> tuple[bool, float, str]:
    """
    Hard filtration logic to discard low-conviction/microcap traps:
    1. Cash from operations MUST be strictly positive.
    2. CFO must convert at least 50% of annualized earnings.
    3. Quarterly profit growth must show positive operational expansion (>20%).
    4. Market cap must be sane (> ₹25 Cr to eliminate pure penny/shell tickers).
    """
    cfo = clean_float(stock.get("cfo", "0"))
    pat = clean_float(stock.get("pat", "0"))
    growth = clean_float(stock.get("profit_growth", "0"))
    mcap = clean_float(stock.get("mcap", "0"))
    pe = clean_float(stock.get("pe", "0"))

    annualized_pat = pat * 4

    # Disqualification checks
    if mcap < 25.0:
        return False, 0.0, "Sub-scale penny ticker (MCap < ₹25 Cr)"
    if cfo <= 0:
        return False, 0.0, "Accounting Trap: Zero or negative Operating Cash Flow"
    if annualized_pat > 0 and (cfo / annualized_pat) < 0.50:
        return False, 0.0, "Weak Cash Conversion: <50% CFO to PAT"
    if growth < 20.0:
        return False, 0.0, "Insufficient earnings velocity (<20% PAT growth)"
    if pe <= 0 or pe > 30.0:
        return False, 0.0, "Valuation outside sweet spot"

    # Multibagger conviction score calculation
    score = 0.0
    # Growth factor (up to 40 pts)
    score += min(growth, 100.0) * 0.40
    # Cash conversion factor (up to 30 pts)
    conversion = min((cfo / annualized_pat), 2.0) if annualized_pat > 0 else 0.5
    score += conversion * 15.0
    # Valuation cushion (lower P/E gets up to 30 pts)
    if 5 <= pe <= 20:
        score += (25 - pe) * 1.5

    return True, score, "Qualified"

def identify_structural_catalyst(sector: str, description: str, stock: dict) -> tuple[str, list[str]]:
    text = (sector + " " + description).lower()
    matched_theme = None
    tailwinds = []
    
    for theme, config in CATALYST_TAXONOMY.items():
        if any(kw in text for kw in config["keywords"]):
            matched_theme = theme
            tailwinds.extend(config["tailwinds"])
            break
            
    pe = clean_float(stock.get("pe", "0"))
    if 0 < pe <= 15:
        tailwinds.append(f"Twin-Engine Re-rating: P/E ({pe:.1f}x) provides multiple-expansion headroom if growth persists.")
    elif 15 < pe <= 22:
        tailwinds.append("Compounder Valuation: Balanced multiple allows EPS growth compounding with institutional backing.")
        
    if not matched_theme:
        matched_theme = sector if sector not in ["Diversified", "General"] else "Specialized Ancillary"
        tailwinds.append("Second-Order Ancillary: Capturing demand expansion from Tier-1 corporate clients.")

    return matched_theme, tailwinds

def send_ranked_conviction_alerts(stocks: list, session: requests.Session):
    qualified = []
    
    for s in stocks:
        is_valid, score, reason = passes_conviction_gate(s)
        if is_valid:
            s["conviction_score"] = score
            qualified.append(s)

    # Sort descending by conviction score
    qualified.sort(key=lambda x: x["conviction_score"], reverse=True)
    
    # Restrict to top 6 conviction picks
    top_picks = qualified[:6]
    
    if not top_picks:
        msg = "⚠️ *Multibagger Discovery Scan*\n\nScanned all candidates, but *0 stocks* passed the strict cash-conversion & growth conviction gates today."
        send_telegram_alert(msg)
        return

    total = len(top_picks)
    print(f"Filtered {len(stocks)} candidates down to {total} high-conviction picks.")

    chunk_size = 3
    total_parts = (total + chunk_size - 1) // chunk_size

    for idx in range(0, total, chunk_size):
        batch = top_picks[idx:idx + chunk_size]
        part_num = (idx // chunk_size) + 1
        
        msg = f"🔥 *High-Conviction Multibagger Picks* ({part_num}/{total_parts})\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        for s in batch:
            sector, about_text = get_company_profile(session, s.get("href", ""))
            theme_name, catalyst_points = identify_structural_catalyst(sector, about_text, s)
            
            cfo = clean_float(s.get("cfo", "0"))
            pat = clean_float(s.get("pat", "0"))
            growth = clean_float(s.get("profit_growth", "0"))
            conv = round((cfo / (pat * 4)) * 100, 1) if pat > 0 else 100.0
            
            short_about = (about_text[:115] + "...") if len(about_text) > 115 else about_text
            bullets = "\n".join([f"    • {p}" for p in catalyst_points])
            
            msg += f"🏢 *{s['name']}* (Score: `{s['conviction_score']:.0f}/100`)\n"
            msg += f"├ 💰 *Valuation:* ₹{s['cmp']} | *P/E:* {s['pe']}x | *MCap:* ₹{s['mcap']} Cr\n"
            msg += f"├ 📈 *Earnings Velocity:* Qtr PAT +{growth:.1f}%\n"
            msg += f"├ 🛡️ *Cash Quality:* ✅ Strong (CFO: ₹{cfo:.1f} Cr vs PAT: ₹{pat:.1f} Cr | {conv}%)\n"
            msg += f"├ 🏭 *Theme:* {theme_name}\n"
            msg += f"│   _{short_about}_\n"
            msg += f"└ 🚀 *Catalysts & Tailwinds:*\n{bullets}\n\n"
            
            time.sleep(0.5)

        send_telegram_alert(msg)
        time.sleep(1.5)

def main():
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SCREENER_URL]):
        print("Error: Missing environment variables.", file=sys.stderr)
        sys.exit(1)
        
    stocks, session = fetch_screener_stocks(SCREENER_URL)
    print(f"Total raw matches from Screener: {len(stocks)}")
    send_ranked_conviction_alerts(stocks, session)

if __name__ == "__main__":
    main()
