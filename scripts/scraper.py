import os
import re
import json
import hashlib
import smtplib
import requests
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ─────────────────────────────────────────
# ✏️  설정값 (GitHub Secrets로 관리)
# ─────────────────────────────────────────
TARGET_URL = os.environ.get("TARGET_URL", "https://www.nhsavingsbank.co.kr/notice/list.do")
BASE_URL   = os.environ.get("BASE_URL",   "https://www.nhsavingsbank.co.kr")

# 키워드 필터 (빈 문자열이면 모든 새 게시물 알림)
# 예시: "채용,공고,모집"  → 쉼표로 구분
KEYWORDS = os.environ.get("KEYWORDS", "")
# ─────────────────────────────────────────

STATE_FILE = "state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"seen_ids": []}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def make_id(text):
    return hashlib.md5(text.strip().encode()).hexdigest()

def fetch_posts():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": BASE_URL,
    }
    resp = requests.get(TARGET_URL, headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    posts = []
    # NH저축은행 공지사항 구조:
    #   div.tb_type_bbs > table > tbody > tr > td.tal > a.bbs_title
    #   onclick="funBrdRead('160730')" 에서 brd_sno 추출 후 URL 조합
    for row in soup.select("div.tb_type_bbs table tbody tr"):
        title_el = row.select_one("td.tal a.bbs_title")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title:
            continue

        # onclick에서 brd_sno 추출: funBrdRead('160730')
        onclick = title_el.get("onclick", "")
        match = re.search(r"funBrdRead\('(\d+)'\)", onclick)
        if match:
            brd_sno = match.group(1)
            url = f"{BASE_URL}/notice/view.do?brd_sno={brd_sno}"
        else:
            url = TARGET_URL  # fallback

        # 날짜도 함께 수집 (알림 이메일에 표시)
        tds = row.find_all("td")
        date = tds[2].get_text(strip=True) if len(tds) > 2 else ""

        posts.append({
            "id":    make_id(title),
            "title": title,
            "url":   url,
            "date":  date,
        })
    return posts

def filter_by_keywords(posts):
    if not KEYWORDS.strip():
        return posts
    kws = [k.strip() for k in KEYWORDS.split(",") if k.strip()]
    return [p for p in posts if any(kw in p["title"] for kw in kws)]

def send_email(new_posts):
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]
    to_addr   = os.environ["NOTIFY_EMAIL"]

    subject = f"[웹 모니터] 새 게시물 {len(new_posts)}건 감지 ({datetime.now().strftime('%Y-%m-%d %H:%M')})"

    rows = "".join(
        f'<tr>'
        f'<td style="padding:8px;border-bottom:1px solid #eee;">'
        f'<a href="{p["url"]}" style="color:#2563eb;text-decoration:none;">{p["title"]}</a>'
        f'</td>'
        f'<td style="padding:8px;border-bottom:1px solid #eee;color:#94a3b8;white-space:nowrap;font-size:13px;">{p.get("date","")}</td>'
        f'</tr>'
        for p in new_posts
    )
    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:auto;">
      <h2 style="color:#1e293b;">🔔 새 게시물 알림</h2>
      <p style="color:#475569;">모니터링 중인 페이지에서 새 게시물이 감지되었습니다.</p>
      <p style="color:#94a3b8;font-size:12px;">📌 {TARGET_URL}</p>
      <table style="width:100%;border-collapse:collapse;margin-top:12px;">
        {rows}
      </table>
      <p style="color:#94a3b8;font-size:11px;margin-top:16px;">
        GitHub Actions Web Monitor · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
      </p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = smtp_user
    msg["To"]      = to_addr
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_addr, msg.as_string())

    print(f"✅ 이메일 전송 완료 → {to_addr} ({len(new_posts)}건)")

def main():
    print(f"🔍 스크래핑 시작: {TARGET_URL}")
    state = load_state()
    seen  = set(state["seen_ids"])

    try:
        posts = fetch_posts()
    except Exception as e:
        print(f"❌ 스크래핑 실패: {e}")
        raise

    print(f"📄 총 {len(posts)}개 게시물 발견")

    new_posts = [p for p in posts if p["id"] not in seen]
    new_posts = filter_by_keywords(new_posts)

    if new_posts:
        print(f"🆕 새 게시물 {len(new_posts)}건:")
        for p in new_posts:
            print(f"   - {p['title']}")
        send_email(new_posts)
        state["seen_ids"] = list(seen | {p["id"] for p in posts})
        save_state(state)
    else:
        print("✨ 새 게시물 없음")
        # 첫 실행 시 현재 상태 저장 (이후부터 새 글만 감지)
        if not seen:
            state["seen_ids"] = [p["id"] for p in posts]
            save_state(state)
            print(f"💾 초기 상태 저장 완료 ({len(posts)}건)")

if __name__ == "__main__":
    main()

