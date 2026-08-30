import os, re, sqlite3, hashlib, html, json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GNEWS_URL = "https://gnews.io/api/v4/search"
TELEGRAM_URL = "https://api.telegram.org/bot{token}/{method}"
DB_PATH = os.getenv("MYBUZZ_DB", "mybuzz.db")

TARGETS = {"news": .40, "viral": .25, "entertainment": .15, "food": .10, "tech": .10}
QUERIES = {
    "news": ['Malaysia', 'Malaysia government', 'Malaysia economy', 'Malaysia crime'],
    "viral": ['Malaysia viral', 'Malaysia trending', 'Malaysia netizens', 'Malaysia tular'],
    "entertainment": ['Malaysia entertainment', 'Malaysia celebrity', 'Malaysia K-pop'],
    "food": ['Malaysia food', 'Malaysia restaurant', 'Malaysia cafe', 'Malaysia dessert'],
    "tech": ['Malaysia technology', 'Malaysia smartphone', 'Malaysia gadget', 'Malaysia AI'],
}
KEYWORDS = {
    "viral": ["viral", "trending", "netizen", "tular", "sensasi", "bizarre"],
    "entertainment": ["entertainment", "celebrity", "artist", "actor", "actress", "k-pop", "concert", "movie", "music"],
    "food": ["food", "restaurant", "cafe", "donut", "dessert", "chef", "dining"],
    "tech": ["technology", "tech", "gadget", "iphone", "android", "ai", "artificial intelligence", "smartphone"],
}
LABELS = {"news":"📰 NEWS", "viral":"🔥 VIRAL", "entertainment":"🎬 ENTERTAINMENT", "food":"🍜 FOOD / LIFESTYLE", "tech":"📱 TECH / GADGET"}


def load_dotenv():
    path = ".env"
    if not os.path.exists(path): return
    for line in open(path, encoding="utf-8"):
        line=line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k,v=line.split("=",1); v=v.strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)


def db():
    c=sqlite3.connect(DB_PATH)
    c.execute("CREATE TABLE IF NOT EXISTS seen(article_key TEXT PRIMARY KEY,url TEXT,title TEXT,published_at TEXT,category TEXT,created_at TEXT)")
    c.commit(); return c


def get_json(url, params=None, method="GET", data=None):
    if params: url += "?" + urlencode(params)
    body = None if data is None else json.dumps(data).encode()
    req=Request(url, data=body, headers={"User-Agent":"MYBUZZ-NewsBot/1.1","Content-Type":"application/json"})
    with urlopen(req, timeout=25) as r: return json.loads(r.read().decode("utf-8"))


def fetch_category(key, category, hours=24, max_each=10):
    since=(datetime.now(timezone.utc)-timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out=[]
    for q in QUERIES[category]:
        try:
            data=get_json(GNEWS_URL,{"q":q,"lang":"en","country":"my","max":max_each,"sortby":"publishedAt","from":since,"apikey":key})
            for a in data.get("articles",[]): a["_requested_category"]=category; out.append(a)
        except Exception as e: print(f"[WARN] {category}: {e}")
    return out


def normalize_title(s): return re.sub(r"[^a-z0-9\u00C0-\uFFFF ]","",re.sub(r"\s+"," ",(s or "").lower()).strip())
def article_key(a): return hashlib.sha256(((a.get("url") or "").strip() or normalize_title(a.get("title"))).encode()).hexdigest()


def category(a):
    text=((a.get("title") or "")+" "+(a.get("description") or "")).lower(); scores={k:0 for k in TARGETS}; scores[a.get("_requested_category","news")]+=2
    for cat,words in KEYWORDS.items(): scores[cat]+=sum(w in text for w in words)
    return max(scores,key=scores.get)


def select_balanced(articles,total):
    quotas={k:round(total*v) for k,v in TARGETS.items()}
    while sum(quotas.values())<total: quotas["news"]+=1
    while sum(quotas.values())>total: quotas["news"]-=1
    groups={k:[] for k in TARGETS}
    for a in articles: a["_category"]=category(a); groups[a["_category"]].append(a)
    for g in groups.values(): g.sort(key=lambda x:x.get("publishedAt","") or "", reverse=True)
    chosen=[]; used=set()
    for cat,q in quotas.items():
        for a in groups[cat]:
            k=article_key(a)
            if k not in used and sum(x["_category"]==cat for x in chosen)<q: chosen.append(a); used.add(k)
    rest=[a for a in articles if article_key(a) not in used]; rest.sort(key=lambda x:x.get("publishedAt","") or "",reverse=True)
    return (chosen+rest)[:total]


def simple_bilingual(a):
    # Safe fallback: keep the source description rather than inventing facts.
    title=a.get("title","").strip(); desc=(a.get("description") or "").strip(); source=(a.get("source") or {}).get("name","Source"); url=a.get("url","")
    return (f"{LABELS[a['_category']]}｜{title}\n\n🇨🇳 {desc}\n\n🇲🇾 {desc}\n\n"
            f"👉 点击阅读完整新闻\n👉 Klik untuk baca berita penuh\n\n🔗 {source}\n{url}")


def ai_bilingual(a):
    """Optional OpenAI-compatible translation/summarisation. Requires OPENAI_API_KEY and OPENAI_MODEL."""
    key=os.getenv("OPENAI_API_KEY")
    if not key: return simple_bilingual(a)
    endpoint=os.getenv("OPENAI_BASE_URL","https://api.openai.com/v1")+"/chat/completions"
    model=os.getenv("OPENAI_MODEL","gpt-4o-mini")
    title=a.get("title",""); desc=a.get("description",""); source=(a.get("source") or {}).get("name","Source"); url=a.get("url","")
    prompt=("You are MYBUZZ Malaysia news editor. Based ONLY on the supplied title and description, "
            "write a concise Chinese summary and a concise Bahasa Melayu summary. Do not add facts. "
            "Return JSON with keys zh and ms.\nTITLE: "+title+"\nDESCRIPTION: "+desc)
    try:
        data=get_json(endpoint, data={"model":model,"temperature":0.2,"messages":[{"role":"system","content":"Return valid JSON only."},{"role":"user","content":prompt}]})
        content=data["choices"][0]["message"]["content"].strip(); obj=json.loads(content)
        return (f"{LABELS[a['_category']]}｜{title}\n\n🇨🇳 {obj.get('zh',desc)}\n\n🇲🇾 {obj.get('ms',desc)}\n\n"
                f"👉 点击阅读完整新闻\n👉 Klik untuk baca berita penuh\n\n🔗 {source}\n{url}")
    except Exception as e:
        print(f"[WARN] AI failed, using fallback: {e}"); return simple_bilingual(a)


def telegram_send(token, chat_id, text, dry_run=False):
    if dry_run: print("\n[DRY RUN] Telegram message:\n"+text); return True
    try:
        r=get_json(TELEGRAM_URL.format(token=token,"method":"sendMessage"),data={"chat_id":chat_id,"text":text,"disable_web_page_preview":False})
        return bool(r.get("ok"))
    except Exception as e: print("[ERROR] Telegram:",e); return False


def mark_seen(c,a): c.execute("INSERT OR IGNORE INTO seen VALUES (?,?,?,?,?,?)",(article_key(a),a.get("url",""),a.get("title",""),a.get("publishedAt",""),a.get("_category","news"),datetime.now(timezone.utc).isoformat()))


def main():
    load_dotenv()
    key=os.getenv("GNEWS_API_KEY")
    if not key: raise SystemExit("Missing GNEWS_API_KEY in .env")
    publish_count=int(os.getenv("MYBUZZ_PUBLISH_COUNT","10")); hours=int(os.getenv("MYBUZZ_LOOKBACK_HOURS","24"))
    send=os.getenv("MYBUZZ_TELEGRAM_SEND","false").lower()=="true"
    dry=os.getenv("MYBUZZ_DRY_RUN","true").lower()=="true"
    token=os.getenv("TELEGRAM_BOT_TOKEN"); chat=os.getenv("TELEGRAM_CHAT_ID")
    all_articles=[]
    for cat in QUERIES: all_articles += fetch_category(key,cat,hours)
    unique={article_key(a):a for a in all_articles}
    c=db(); seen={r[0] for r in c.execute("SELECT article_key FROM seen")}
    fresh=[a for k,a in unique.items() if k not in seen]
    selected=select_balanced(fresh,publish_count)
    print(f"MYBUZZ V1.1 | candidates={len(unique)} fresh={len(fresh)} selected={len(selected)}")
    for a in selected:
        text=ai_bilingual(a)
        if send:
            if not token or not chat: print("[WARN] Telegram enabled but token/chat_id missing; skipping")
            elif telegram_send(token,chat,text,dry): mark_seen(c,a)
        else:
            print("="*70); print(text); mark_seen(c,a)
    c.commit(); c.close()

if __name__=="__main__": main()
