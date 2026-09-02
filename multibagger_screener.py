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

CATALYST_TAXONOMY = {
    "Capital Goods & Defense": {
        "keywords": ["defense", "aerospace", "valve", "pump", "casting", "forging", "machining", "cnc", "industrial machinery", "tool", "taps"],
        "tailwinds": [
            "Import Substitution: Beneficiary of Make in India and defense indigenization.",
            "Operating Leverage: Margin expansion as manufacturing capacity utilization peaks."
        ]
    },
    "Power & Renewable Transition": {
        "keywords": ["power", "solar", "transformer", "cable", "wire", "switchgear", "grid", "renewable", "substation"],
        "tailwinds": [
            "Grid Modernization: Transmission capex expanding to evacuate renewable power.",
            "Order Book Visibility: Multi-year backlog backed by utility tenders."
        ]
    },
    "Chemicals & Specialized Materials": {
        "keywords": ["chemical", "specialty chemical", "intermediate", "agrochem", "api", "pharma", "polymer", "gelatine", "ossein"],
        "tailwinds": [
            "China+1 Shift: Global supply chains diversifying raw material intermediate sourcing.",
            "Spread Recovery: Raw material input normalization driving EBITDA rebound."
        ]
    },
    "Infrastructure & Specialized Construction": {
        "keywords": ["rail", "wagon", "tunnel", "bridge", "highway", "port", "logistics", "civil construction", "infrastructure", "construct"],
        "tailwinds": [
            "Strategic Infra Outlays: Beneficiary of national transit corridors and highway capex.",
            "Execution Moat: Specialized civil works command protected margins vs plain road builders."
        ]
    },
    "Auto Ancillaries & Precision Parts": {
        "keywords": ["auto ancillary", "bearing", "gear", "piston", "ev", "electric vehicle", "transmission", "sheet metal", "castings"],
        "tailwinds": [
            "Second-Order Engine: OEM production surge directly drives supplier order volumes.",
            "Content Enhancement: Transition to precision-engineered components lifts unit margins."
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
        return "Industrial Ancillary", "Niche supplier serving core industry verticals."
        
    full_url = BASE_URL + company_path if company_path.startswith("/") else f"{BASE_URL}/{company_path}"
    try:
        resp = session.get(full_url, timeout=10)
        if resp.status_code != 200:
            return "Industrial Ancillary", "Niche supplier serving core industry verticals."
            
        soup = BeautifulSoup(resp.text, "html.parser")
        
        sector = "Industrial Ancillary"
        peers_section = soup.find("section", id="peers")
        if peers_section:
            sector_tag = peers_section.find("a", href=lambda h: h and "/market/" in h)
            if sector_tag:
                sector = sector_tag.get_text(strip=True)

        about_div = soup.find("div", class_="about") or soup.find("div", class_="company-profile")
        description = "Niche supplier serving core industry verticals."
        if about_div:
            p_tag = about_div.find("p")
            if p_tag:
                description = p_tag.get_text(strip=True)
                
        return sector, description
    except Exception:
        return "Industrial Ancillary", "Niche supplier serving core industry verticals."

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
        raw_headers = [th.get_text(strip=True) for th in thead.find_all("th")] if thead else []
        headers = [h.lower().replace(".", "").replace("%", "").strip() for h in raw_headers]

        # Explicit regex-style substring matching for Screener's exact table headers
        def locate_col(patterns, reject_patterns=None):
            if reject_patterns is None:
                reject_patterns = []
            for p in patterns:
                for idx, h in enumerate(headers):
                    if any(rej in h for rej in reject_patterns):
                        continue
                    if p in h:
                        return idx
            return -1

        idx_name = locate_col(["name"])
        idx_cmp = locate_col(["cmp", "price", "current price"])
        idx_pe = locate_col(["p/e", "price to earning"])
        idx_mcap = locate_col(["mar cap", "market cap"])
        
        # Growth MUST have 'var' or 'growth', and MUST NOT be dividend yield
        idx_growth = locate_col(["profit var", "qtr profit var", "profit growth"], reject_patterns=["div", "yield"])
        
        # Cash flow MUST have 'cfo' or 'cash from operations'
        idx_cfo = locate_col(["cfo", "cash from operations"])
        
        # PAT MUST NOT match 'var', 'growth', or 'sales'
        idx_pat = locate_col(["np qtr", "profit after tax", "net profit"], reject_patterns=["var", "growth", "sales", "div"])

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

def calculate_conviction_score(stock: dict) -> tuple[bool, float]:
    cfo = clean_float(stock.get("cfo", "0"))
    pat = clean_float(stock.get("pat", "0"))
    growth = clean_float(stock.get("profit_growth", "0"))
    mcap = clean_float(stock.get("mcap", "0"))
    pe = clean_float(stock.get("pe", "0"))

    # Hard guardrails: Filter out micro shell companies (<₹25 Cr) and extreme P/E
    if mcap < 25.0 or pe <= 0 or pe > 35.0:
        return False, 0.0

    score = 0.0

    # 1. Earnings Growth (Max 40 points)
    if growth >= 50.0:
        score += 40.0
    elif growth >= 25.0:
        score += 30.0
    elif growth >= 10.0:
        score += 15.0
    else:
        score += 5.0

    # 2. Valuation Expansion Runway (Max 30 points)
    if 5.0 <= pe <= 16.0:
        score += 30.0
    elif 16.0 < pe <= 24.0:
        score += 20.0
    else:
        score += 10.0

    # 3. Cash Flow Conversion (Max 30 points)
    annualized_pat = pat * 4 if pat > 0 else 1.0
    if cfo > 0:
        conversion = (cfo / annualized_pat) if annualized_pat > 0 else 0
        if conversion >= 0.5:
            score += 30.0
        elif conversion >= 0.2:
            score += 20.0
        else:
            score += 10.0
    else:
        score -= 10.0

    passes = (score >= 45.0) and (cfo > 0)
    return passes, score

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
        tailwinds.append(f"Twin-Engine Re-Rating: Low multiple ({pe:.1f}x) provides multiple expansion runway if growth holds.")
    elif 15 < pe <= 24:
        tailwinds.append("Compounder Valuation: Balanced multiple enables EPS growth with institutional accumulation.")
        
    if not matched_theme:
        matched_theme = sector if sector not in ["Diversified", "General", "Commodities"] else "Niche Engineering Ancillary"
        tailwinds.append("Second-Order Beneficiary: Positioned to capture ancillary demand from Tier-1 corporate growth.")

    return matched_theme, tailwinds

def send_ranked_conviction_alerts(stocks: list, session: requests.Session):
    if not stocks:
        print("No stocks scraped from Screener.")
        return

    scored_stocks = []
    for s in stocks:
        passes, score = calculate_conviction_score(s)
        s["conviction_score"] = score
        s["strict_pass"] = passes
        scored_stocks.append(s)

    strict_passed = [s for s in scored_stocks if s["strict_pass"]]
    if strict_passed:
        top_picks = sorted(strict_passed, key=lambda x: x["conviction_score"], reverse=True)[:5]
    else:
        print("Falling back to top relative scores among available candidates.")
        top_picks = sorted(scored_stocks, key=lambda x: x["conviction_score"], reverse=True)[:5]

    total = len(top_picks)
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
            growth_sign = "+" if growth > 0 else ""
            
            annualized_pat = pat * 4
            if cfo <= 0:
                cash_badge = "⚠️ Negative Cash Flow (CFO ≤ 0)"
            elif annualized_pat > 0 and (cfo / annualized_pat) >= 0.5:
                conv_pct = round((cfo / annualized_pat) * 100)
                cash_badge = f"✅ Strong Conversion (~{conv_pct}% CFO/PAT)"
            else:
                cash_badge = "⚠️ Moderate Cash Flow"

            short_about = (about_text[:115] + "...") if len(about_text) > 115 else about_text
            bullets = "\n".join([f"    • {p}" for p in catalyst_points])
            
            msg += f"🏢 *{s['name']}* (Score: `{s['conviction_score']:.0f}/100`)\n"
            msg += f"├ 💰 *Valuation:* ₹{s['cmp']} | *P/E:* {s['pe']}x | *MCap:* ₹{s['mcap']} Cr\n"
            msg += f"├ 📈 *Earnings Velocity:* Qtr PAT Var: {growth_sign}{s['profit_growth']}%\n"
            msg += f"├ 🛡️ *Cash Quality:* {cash_badge}\n"
            msg += f"│   `CFO: ₹{cfo:.1f} Cr | Qtr PAT: ₹{pat:.1f} Cr`\n"
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
