import os
import re
import json
import smtplib
import requests
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ─────────────────────────────────────────
# 설정값 (GitHub Secrets로 관리)
# ─────────────────────────────────────────
TARGET_URL = os.environ.get("TARGET_URL", "https://www.nhsavingsbank.co.kr/notice/list.do")
BASE_URL   = os.environ.get("BASE_URL",   "https://www.nhsavingsbank.co.kr")
KEYWORDS   = os.environ.get("KEYWORDS",   "")  # 빈 문자열이면 전체 알림
# ─────────────────────────────────────────

STATE_FILE = "last_seen.txt"

def load_last_sno():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            val = f.read().strip()
            return int(val) if val.isdigit() else 0
    return 0

def save_last_sno(sno):
    with open(STATE_FILE, "w") as f:
        f.write(str(sno))

def fetch_posts():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": BASE_URL,
    }
    resp = requests.get(TARGET_URL, headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    posts = []
    for row in soup.select("div.tb_type_bbs table tbody tr"):
        title_el = row.select_one("td.tal a.bbs_title")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title:
            continue

        onclick = title_el.get("onclick", "")
        match = re.search(r"funBrdRead\('(\d+)'\)", onclick)
        if not match:
            continue
        brd_sno = int(match.group(1))
        url = f"{BASE_URL}/notice/view.do?brd_sno={brd_sno}"

        tds = row.find_all("td")
        date = tds[2].get_text(strip=True) if len(tds) > 2 else ""

        posts.append({"sno": brd_sno, "title": title, "url": url, "date": date})
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

    subject = f"[NH저축은행] 새 공지사항 {len(new_posts)}건 ({datetime.now().strftime('%Y-%m-%d %H:%M')})"

    rows = "".join(
        f'<tr>'
        f'<td style="padding:10px;border-bottom:1px solid #eee;">'
        f'<a href="{p["url"]}" style="color:#2563eb;text-decoration:none;font-size:15px;">{p["title"]}</a>'
        f'</td>'
        f'<td style="padding:10px;border-bottom:1px solid #eee;color:#94a3b8;white-space:nowrap;font-size:13px;">{p["date"]}</td>'
        f'</tr>'
        for p in new_posts
    )
    html = f"""
    <div style="font-family:sans-serif;max-width:620px;margin:auto;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">
      <div style="background:#1e40af;padding:20px;">
        <h2 style="color:white;margin:0;">🔔 NH저축은행 새 공지사항</h2>
      </div>
      <div style="padding:20px;">
        <table style="width:100%;border-collapse:collapse;">{rows}</table>
        <p style="color:#94a3b8;font-size:11px;margin-top:20px;border-top:1px solid #eee;padding-top:12px;">
          GitHub Actions 자동 모니터링 · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </p>
      </div>
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

    last_sno = load_last_sno()
    print(f"📌 마지막 확인 게시물 번호: {last_sno}")

    try:
        posts = fetch_posts()
    except Exception as e:
        print(f"❌ 스크래핑 실패: {e}")
        raise

    print(f"📄 총 {len(posts)}개 게시물 발견")

    if not posts:
        print("❌ 게시물을 가져오지 못했습니다.")
        return

    max_sno = max(p["sno"] for p in posts)

    if last_sno == 0:
        save_last_sno(max_sno)
        print(f"💾 첫 실행: 최신 번호 {max_sno} 저장. 다음 실행부터 새 글 감지 시작!")
        return

    new_posts = [p for p in posts if p["sno"] > last_sno]
    new_posts = filter_by_keywords(new_posts)
    new_posts.sort(key=lambda p: p["sno"])

    if new_posts:
        print(f"🆕 새 게시물 {len(new_posts)}건:")
        for p in new_posts:
            print(f"   - [{p['sno']}] {p['title']}")
        send_email(new_posts)
        save_last_sno(max_sno)
        print(f"💾 최신 번호 {max_sno} 저장 완료")
    else:
        print(f"✨ 새 게시물 없음 (최신 번호: {max_sno})")

if __name__ == "__main__":
    main()
