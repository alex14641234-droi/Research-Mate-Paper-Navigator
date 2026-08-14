import streamlit as st
import requests
import xml.etree.ElementTree as ET
import re
import urllib.parse
from datetime import datetime
import hashlib
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import os
import uuid

st.set_page_config(page_title="Research Mate", page_icon="🔬", layout="wide")

@st.cache_data(show_spinner=False)
def get_available_models(api_key):
    try:
        genai.configure(api_key=api_key)
        all_models = [m.name.replace("models/", "") for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        filtered = [m for m in all_models if any(v in m for v in ["3.6", "3.7", "3.1-pro", "3.1pro", "3.1", "3.5"])]
        return filtered if filtered else ["gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.1-pro", "gemini-3.5-flash"]
    except Exception:
        return ["gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.1-pro", "gemini-3.5-flash"]

# --- ☁️ 클라우드 데이터베이스 (Firebase Firestore) 초기화 ---
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        if "firebase" in st.secrets:
            cert_dict = dict(st.secrets["firebase"])
            if "private_key" in cert_dict:
                cert_dict["private_key"] = cert_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cert_dict)
            firebase_admin.initialize_app(cred)
        elif os.path.exists("firebase_key.json"):
            cred = credentials.Certificate("firebase_key.json")
            firebase_admin.initialize_app(cred)
        else:
            return None
    try:
        return firestore.client()
    except Exception:
        return None

db = init_firebase()

# --- 💾 공유 뷰 (비로그인 접근 허용) ---
if "shared_chat" in st.query_params and "shared_user" in st.query_params:
    shared_session_id = st.query_params["shared_chat"]
    shared_username = st.query_params["shared_user"]
    
    st.title("🔗 공유된 연구 노트")
    st.caption(f"👤 **{shared_username}**님이 공유한 AI 논문 비서 대화 내역입니다.")
    
    if not db:
        st.error("데이터베이스 연결에 실패했습니다.")
    else:
        def get_shared_chat_history(user, sess_id):
            msgs_ref = db.collection('users').document(user).collection('chat_sessions').document(sess_id).collection('messages').order_by('timestamp')
            return [doc.to_dict() for doc in msgs_ref.stream()]

        session_doc = db.collection('users').document(shared_username).collection('chat_sessions').document(shared_session_id).get()
        if session_doc.exists and session_doc.to_dict().get('is_shared', False):
            title = session_doc.to_dict().get('title', '공유된 채팅')
            st.markdown(f"### 💬 {title}")
            st.markdown("---")
            
            chat_history = get_shared_chat_history(shared_username, shared_session_id)
            if not chat_history:
                st.info("대화 내역이 없습니다.")
            else:
                for msg in chat_history:
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])
        else:
            st.error("🚨 존재하지 않거나 공유가 해제된 채팅방입니다. (접근 권한 없음)")
            
    st.markdown("---")
    if st.button("🏠 Research Mate 홈으로 가기", type="primary"):
        del st.query_params["shared_chat"]
        del st.query_params["shared_user"]
        st.rerun()
    st.stop()


# --- 💾 클라우드 데이터베이스 연동 로직 ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def signup(username, password, api_key=""):
    if not db: return False
    doc_ref = db.collection('users').document(username)
    if doc_ref.get().exists: return False
    doc_ref.set({'password': hash_password(password), 'api_key': api_key.strip()})
    return True

def update_password(username, new_password):
    if not db: return False
    try:
        db.collection('users').document(username).update({'password': hash_password(new_password)})
        return True
    except Exception:
        return False

def login(username, password):
    if not db: return False
    doc_ref = db.collection('users').document(username)
    doc = doc_ref.get()
    if doc.exists and doc.to_dict().get('password') == hash_password(password):
        return True
    return False

def save_api_key(username, api_key):
    if not db: return
    db.collection('users').document(username).update({'api_key': api_key.strip()})

def get_api_key(username):
    if not db: return ""
    doc = db.collection('users').document(username).get()
    if doc.exists: return doc.to_dict().get('api_key', "")
    return ""

def save_paper_to_db(username, paper_info):
    if not db: return False
    paper_info['saved_at'] = datetime.now().strftime("%Y-%m-%d %H:%M")
    db.collection('users').document(username).collection('papers').document(paper_info['id']).set(paper_info)
    return True

def delete_paper_from_db(username, paper_id):
    if not db: return False
    db.collection('users').document(username).collection('papers').document(paper_id).delete()
    return True

def get_saved_papers(username):
    if not db: return []
    papers_ref = db.collection('users').document(username).collection('papers').order_by('saved_at', direction=firestore.Query.DESCENDING)
    return [doc.to_dict() for doc in papers_ref.stream()]

def get_user_categories(username):
    if not db: return []
    try:
        doc = db.collection('users').document(username).collection('settings').document('categories').get()
        if doc.exists and 'list' in doc.to_dict():
            cats = doc.to_dict()['list']
            unwanted = ["인공지능", "컴퓨터 비전", "자연어 처리", "로봇공학", "의학/생명", "기타", "기본", "일반"]
            cleaned = [c for c in cats if c not in unwanted]
            return cleaned
    except Exception:
        pass
    return []

def save_user_categories(username, categories_list):
    if not db: return False
    try:
        db.collection('users').document(username).collection('settings').document('categories').set({'list': categories_list})
        return True
    except Exception:
        return False

# --- 💬 다중 채팅 세션(Session) DB 로직 ---
def create_chat_session(username):
    if not db: return None
    sessions_ref = db.collection('users').document(username).collection('chat_sessions')
    _, new_ref = sessions_ref.add({
        'created_at': datetime.now().isoformat(),
        'title': '새 채팅',
        'is_shared': False
    })
    return new_ref.id

def get_chat_sessions(username):
    if not db: return []
    sessions_ref = db.collection('users').document(username).collection('chat_sessions').order_by('created_at', direction=firestore.Query.DESCENDING)
    return [{'id': doc.id, **doc.to_dict()} for doc in sessions_ref.stream()]

def delete_chat_session(username, session_id):
    if not db: return
    session_ref = db.collection('users').document(username).collection('chat_sessions').document(session_id)
    msgs = session_ref.collection('messages').stream()
    for msg in msgs:
        msg.reference.delete()
    session_ref.delete()

def save_chat_message(username, session_id, role, content):
    if not db: return
    db.collection('users').document(username).collection('chat_sessions').document(session_id).collection('messages').add({
        'role': role,
        'content': content,
        'timestamp': datetime.now().isoformat()
    })

def update_chat_session_title(username, session_id, title):
    if not db: return
    db.collection('users').document(username).collection('chat_sessions').document(session_id).update({'title': title})

def share_chat_session(username, session_id, is_shared):
    if not db: return
    db.collection('users').document(username).collection('chat_sessions').document(session_id).update({'is_shared': is_shared})

def get_chat_history(username, session_id):
    if not db: return []
    msgs_ref = db.collection('users').document(username).collection('chat_sessions').document(session_id).collection('messages').order_by('timestamp')
    return [doc.to_dict() for doc in msgs_ref.stream()]

def generate_chat_title(api_key, model_name, first_query):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        prompt = f"다음 사용자 질문을 보고 3~5단어 내외의 아주 짧고 핵심적인 대화 방 제목(제목만 출력, 이모지 포함)을 만들어주세요: '{first_query}'"
        res = model.generate_content(prompt)
        title = res.text.strip().replace('"', '').replace("'", "")
        return title[:20]
    except Exception:
        return first_query[:15]

def export_chat_as_markdown(chat_history, session_title):
    md_content = f"# 💬 {session_title}\n\n*다운로드 일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n---\n\n"
    for msg in chat_history:
        role = "👤 사용자" if msg['role'] == 'user' else "🤖 AI 비서"
        md_content += f"### {role}\n{msg['content']}\n\n---\n\n"
    return md_content

def get_citation(paper):
    authors = paper.get('authors', 'Unknown')
    year = paper.get('published', 'n.d.')[:4]
    title = paper.get('en_title', paper.get('title', 'Unknown Title'))
    url = paper.get('pdf_url', '')
    
    apa = f"{authors} ({year}). {title}. Retrieved from {url}"
    bibtex = f"@article{{{paper.get('id', 'id')},\n  author={{{authors}}},\n  title={{{title}}},\n  year={{{year}}},\n  url={{{url}}}\n}}"
    return apa, bibtex

# --- 🌐 번역 및 ArXiv 탐색 로직 ---
def translate_to_ko(text):
    if not text.strip(): return text
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "en", "tl": "ko", "dt": "t", "q": text}
        res = requests.get(url, params=params, timeout=5)
        data = res.json()
        translated_text = "".join([sentence[0] for sentence in data[0]])
        return translated_text
    except Exception:
        return text

@st.cache_data(ttl=3600, show_spinner=False)
def translate_to_en(text):
    if not text.strip(): return text
    if not re.search(r'[가-힣]', text):
        return text
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "ko", "tl": "en", "dt": "t", "q": text}
        res = requests.get(url, params=params, timeout=5)
        data = res.json()
        translated_text = "".join([sentence[0] for sentence in data[0]])
        return translated_text
    except Exception:
        return text

def parse_year_range(user_query):
    q = user_query.strip().lower()
    
    # Era expressions (e.g., 2000년대 초반 -> 2000~2004)
    if re.search(r'2000\s*년대\s*(초반|초)', q):
        return [str(y) for y in range(2000, 2005)], "200001010000", "200412312359"
    if re.search(r'2000\s*년대\s*(중반|중)', q):
        return [str(y) for y in range(2004, 2008)], "200401010000", "200712312359"
    if re.search(r'2000\s*년대\s*(후반|말)', q):
        return [str(y) for y in range(2007, 2010)], "200701010000", "200912312359"
    if re.search(r'2000\s*년대', q) or re.search(r'\b2000s\b', q):
        return [str(y) for y in range(2000, 2010)], "200001010000", "200912312359"

    if re.search(r'2010\s*년대\s*(초반|초)', q):
        return [str(y) for y in range(2010, 2015)], "201001010000", "201412312359"
    if re.search(r'2010\s*년대\s*(중반|중)', q):
        return [str(y) for y in range(2014, 2018)], "201401010000", "201712312359"
    if re.search(r'2010\s*년대', q) or re.search(r'\b2010s\b', q):
        return [str(y) for y in range(2010, 2020)], "201001010000", "201912312359"

    if re.search(r'2020\s*년대', q) or re.search(r'\b2020s\b', q):
        return [str(y) for y in range(2020, 2027)], "202001010000", "202612312359"

    if re.search(r'1990\s*년대', q) or re.search(r'\b1990s\b', q):
        return [str(y) for y in range(1990, 2000)], "199001010000", "199912312359"

    # Specific single year (e.g. 2024, 2004, 1998)
    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', q)
    if year_match:
        y_str = year_match.group(1)
        return [y_str], f"{y_str}01010000", f"{y_str}12312359"

    return None, None, None

def parse_smart_query(user_query):
    q = user_query.strip()
    q_lower = q.lower()

    # 1. Author Intent Detection ("~교수님", "~교수", "~저자", "author:", "by ~")
    author_match = re.search(r'([가-힣]{2,4}|[A-Za-z\s]+)\s*(교수님|교수|저자|박사님|박사|연구원|작가)', q)
    author_query = None
    author_ko = None
    if author_match:
        raw_author = author_match.group(1).strip()
        if re.search(r'[가-힣]', raw_author):
            author_ko = raw_author
            translated_author = translate_to_en(raw_author).strip()
            # Generate common Romanized variants for Korean authors (e.g. Homin Kim, Ho-Min Kim, Kim)
            author_query = f'au:"{translated_author}" OR all:"{translated_author}"'
        else:
            author_query = f'au:"{raw_author}" OR all:"{raw_author}"'

    # 2. Year / Era Intent Detection
    target_years, start_dt, end_dt = parse_year_range(user_query)

    # 3. Sort Order
    if any(w in q_lower for w in ["최신", "최근", "recent", "latest", "최근순", "최신순"]):
        sort_by = "submittedDate"
    else:
        sort_by = "relevance"

    # 4. ArXiv ID match
    match = re.search(r'\d{4}\.\d{4,5}', q_lower)
    if match: return f"id:{match.group(0)}", sort_by, target_years, author_ko

    # 5. Clean Topic Keyword Extraction
    clean_q = q
    if author_match:
        clean_q = clean_q.replace(author_match.group(0), "")

    clean_q = re.sub(r'\b(19\d{2}|20\d{2})\b', '', clean_q)
    stop_words = [
        "추천해줘", "추천", "찾아줘", "대해", "요즘", "핫한", "알려줘", "이슈가", "되는", 
        "최신", "최근", "논문", "쉬운", "쉬운거", "하나만", "하나", "입문", "기초", "재밌는", "좋은", "괜찮은",
        "년도", "년", "기준", "년대", "초반", "중반", "후반", "교수님", "교수", "저자", "작성자", "관련"
    ]
    for word in stop_words:
        clean_q = clean_q.replace(word, "")
    clean_q = clean_q.strip()

    search_terms = []
    if author_query:
        search_terms.append(f"({author_query})")

    keyword_map = {
        "초전도": 'all:"superconductivity" OR all:"HTS"', "트랜스포머": 'all:"transformer" AND all:"attention"',
        "생성형": 'all:"generative model"', "비전": 'all:"computer vision"', "로봇": 'all:"robotics"',
        "자율주행": 'all:"autonomous driving"'
    }
    
    for ko_word, en_query in keyword_map.items():
        if ko_word in clean_q.lower():
            search_terms.append(f"({en_query})")
            
    if any(w in clean_q.lower() for w in ["ai", "인공지능", "llm", "머신러닝", "딥러닝"]):
        search_terms.append('(all:"artificial intelligence" OR all:"large language model")')
        
    if search_terms:
        final_query = " AND ".join(search_terms)
    else:
        if not clean_q or len(clean_q) < 2:
            clean_q = "deep learning"

        if re.search(r'[가-힣]', clean_q):
            en_query = translate_to_en(clean_q)
        else:
            en_query = clean_q

        en_clean = re.sub(r'[^\w\s]', '', en_query).strip()
        if not en_clean or en_clean.lower() in ["easy", "easy one", "easy only one", "one", "simple"]:
            en_clean = "deep learning"

        final_query = f'all:{en_clean}'

    return final_query, sort_by, target_years, author_ko

def search_arxiv_papers(user_query, max_results=5):
    import time
    raw_query, sort_by, target_years, author_ko = parse_smart_query(user_query)
    encoded_query = urllib.parse.quote(raw_query)
    notice_msg = None
    try:
        # Fetch 50 candidate papers across years
        url = f"https://export.arxiv.org/api/query?search_query={encoded_query}&start=0&max_results=50&sortBy={sort_by}&sortOrder=descending"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        
        for attempt in range(3):
            try:
                res = requests.get(url, headers=headers, timeout=20)
                if res.status_code == 429:
                    if attempt == 2:
                        raise ValueError("RATE_LIMIT")
                    time.sleep(3)
                    continue
                res.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                if attempt == 2:
                    raise ValueError(f"TIMEOUT: {e}")
                time.sleep(3)
                continue
            
        root = ET.fromstring(res.text)
        papers = []
        for entry in root.findall('{http://www.w3.org/2005/Atom}entry'):
            title = entry.find('{http://www.w3.org/2005/Atom}title').text.replace('\n', ' ').strip()
            summary = entry.find('{http://www.w3.org/2005/Atom}summary').text.replace('\n', ' ').strip()
            ko_title = translate_to_ko(title)
            ko_summary = translate_to_ko(summary)
            
            raw_id = entry.find('{http://www.w3.org/2005/Atom}id').text.split('/')[-1]
            clean_id = re.sub(r'v\d+$', '', raw_id)
            
            pub_date = entry.find('{http://www.w3.org/2005/Atom}published').text[:10]
            papers.append({
                "id": clean_id,
                "title": ko_title,
                "en_title": title,
                "authors": ", ".join([a.find('{http://www.w3.org/2005/Atom}name').text for a in entry.findall('{http://www.w3.org/2005/Atom}author')][:3]),
                "published": pub_date,
                "summary": ko_summary,
                "pdf_url": f"https://arxiv.org/pdf/{clean_id}.pdf"
            })

        # 1. Author Filter / Topic Fallback
        if author_ko:
            translated_author = translate_to_en(author_ko).lower()
            author_tokens = [w for w in re.split(r'\s+', translated_author) if len(w) > 1]
            
            author_matches = []
            for p in papers:
                p_authors_lower = p['authors'].lower()
                if any(tok in p_authors_lower for tok in author_tokens):
                    author_matches.append(p)
            
            if author_matches:
                papers = author_matches
            else:
                # If author query returned 0 matches, retry fetching topic-only papers so user NEVER gets 0 results!
                topic_q = re.sub(r'\(au:[^)]+\)\s*AND\s*', '', raw_query)
                topic_q = re.sub(r'\s*AND\s*\(au:[^)]+\)', '', topic_q)
                if topic_q and topic_q != raw_query:
                    fb_url = f"https://export.arxiv.org/api/query?search_query={urllib.parse.quote(topic_q)}&start=0&max_results=30&sortBy={sort_by}&sortOrder=descending"
                    fb_res = requests.get(fb_url, headers=headers, timeout=15)
                    fb_root = ET.fromstring(fb_res.text)
                    fb_papers = []
                    for entry in fb_root.findall('{http://www.w3.org/2005/Atom}entry'):
                        t = entry.find('{http://www.w3.org/2005/Atom}title').text.replace('\n', ' ').strip()
                        s = entry.find('{http://www.w3.org/2005/Atom}summary').text.replace('\n', ' ').strip()
                        r_id = entry.find('{http://www.w3.org/2005/Atom}id').text.split('/')[-1]
                        c_id = re.sub(r'v\d+$', '', r_id)
                        fb_papers.append({
                            "id": c_id, "title": translate_to_ko(t), "en_title": t,
                            "authors": ", ".join([a.find('{http://www.w3.org/2005/Atom}name').text for a in entry.findall('{http://www.w3.org/2005/Atom}author')][:3]),
                            "published": entry.find('{http://www.w3.org/2005/Atom}published').text[:10],
                            "summary": translate_to_ko(s), "pdf_url": f"https://arxiv.org/pdf/{c_id}.pdf"
                        })
                    if fb_papers:
                        papers = fb_papers
                        notice_msg = f"💡 '{author_ko} 교수님/저자'의 ArXiv 직접 등록 논문 외에, 요청하신 주제와 가장 관련성이 높은 주요 학술 논문을 안내해 드립니다."

        # 2. Strict Python Year Filter / Sort!
        if target_years:
            strict_matches = [p for p in papers if any(p['published'].startswith(y) for y in target_years)]
            if strict_matches:
                return strict_matches[:max_results], notice_msg
            
            ref_year = int(target_years[0])
            papers.sort(key=lambda p: abs(int(p['published'][:4]) - ref_year))
            return papers[:max_results], notice_msg

        return papers[:max_results], notice_msg
    except ValueError as ve:
        raise ve
    except Exception:
        return [], None

# --- 🤖 AI 분석 및 챗봇 로직 (스트리밍) ---
def analyze_local_pdf(api_key, model_name, pdf_bytes, filename, custom_context):
    genai.configure(api_key=api_key)
    
    if custom_context and custom_context.strip():
        user_context_block = f"""
🎯 **[사용자의 특정 키워드, 연구 맥락 및 맞춤 상황 요구사항]**:
"{custom_context.strip()}"

⚠️ **[최우선 분석 지침]**:
분석 결과의 모든 섹션(초록 요약, 주요 알고리즘, 실험 결과, 한계점, 실전 응용)을 반드시 위 [사용자의 특정 키워드/연구 맥락/상황]에 100% 직접 맞추어 재해석하고 차별화된 맞춤형 시각으로 작성하십시오. 일반적이고 정형화된 요약 대신, 사용자가 제시한 특정 관심 키워드와 상황에 집중하여 차별화된 인사이트를 도출하십시오.
"""
    else:
        user_context_block = "특별히 지정된 사용자 맥락이 없으므로, 논문의 일반적 기여점, 핵심 알고리즘 수식, 주요 아키텍처 및 종합 인사이트 관점에서 정밀 정리하십시오."

    prompt = f"""
당신은 세계 최고 수준의 시각 및 텍스트 융합 논문 분석 전문가이자 수석 연구원입니다.
업로드된 로컬 PDF 논문을 바탕으로 다음 지침에 맞춰 가시성이 뛰어나고 깔끔한 마크다운 분석 리포트를 작성해 주십시오.

{user_context_block}

### 🎯 1. 사용자 맞춤 관점 (특정 키워드 & 상황) 집중 분석
- 사용자가 요구한 관심 키워드 및 질문 상황 관점에서 이 논문이 제공하는 가장 결정적인 인사이트와 시사점.

### 🔗 2. 논문 핵심 기여점 (Contribution) & 공식 코드 (GitHub)
- 논문 제안 방법론의 고유한 혁신성 및 공식 구현 링크 (PDF 내 명시 시 추출).

### 🧮 3. 주요 아키텍처, 핵심 수식 및 실험 성과
- 핵심 알고리즘 구조, 대표적 수식/변수 및 정량적 개선 결과.

### 💡 4. 사용자의 연구 상황에 맞춘 실전 적용 조언 & 한계점
- 본 논문의 연구 한계점과 사용자의 특정 연구 상황/키워드 관점에서 실제 연구 및 프로젝트에 응용할 때 고려해야 할 핵심 팁.
"""
    
    # Dynamic temperature: higher temperature when custom context is provided for creative synthesis
    temp = 0.4 if (custom_context and custom_context.strip()) else 0.2
    
    for m_name in [model_name, "gemini-3.6-flash", "gemini-3.5-flash"]:
        try:
            model = genai.GenerativeModel(m_name)
            res = model.generate_content([{"mime_type": "application/pdf", "data": pdf_bytes}, prompt], generation_config={"max_output_tokens": 8192, "temperature": temp})
            return res.text
        except Exception as e:
            if ("429" in str(e) or "quota" in str(e).lower()) and m_name != "gemini-3.5-flash":
                continue # Try fallback model
            raise ValueError(f"RATE_LIMIT: {str(e)}" if "429" in str(e) or "quota" in str(e).lower() else f"ERROR: {str(e)}")

def analyze_paper_with_gemini(api_key, model_name, pdf_url, custom_context):
    genai.configure(api_key=api_key)
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    response = requests.get(pdf_url, headers=headers, timeout=20)
    response.raise_for_status()
    
    if custom_context and custom_context.strip():
        user_context_block = f"""
🎯 **[사용자의 특정 키워드, 연구 맥락 및 맞춤 상황 요구사항]**:
"{custom_context.strip()}"

⚠️ **[최우선 분석 지침]**:
분석 결과의 모든 섹션(초록 요약, 주요 알고리즘, 실험 결과, 한계점, 실전 응용)을 반드시 위 [사용자의 특정 키워드/연구 맥락/상황]에 100% 직접 맞추어 재해석하고 차별화된 맞춤형 시각으로 작성하십시오. 일반적이고 정형화된 요약 대신, 사용자가 제시한 특정 관심 키워드와 상황에 집중하여 차별화된 인사이트를 도출하십시오.
"""
    else:
        user_context_block = "특별히 지정된 사용자 맥락이 없으므로, 논문의 일반적 기여점, 핵심 알고리즘 수식, 주요 아키텍처 및 종합 인사이트 관점에서 정밀 정리하십시오."

    prompt = f"""
당신은 세계 최고 수준의 시각 및 텍스트 융합 논문 분석 전문가이자 수석 연구원입니다.
첨부된 PDF 논문을 바탕으로 다음 지침에 맞춰 가시성이 뛰어나고 깔끔한 마크다운 분석 리포트를 작성해 주십시오.

{user_context_block}

### 🎯 1. 사용자 맞춤 관점 (특정 키워드 & 상황) 집중 분석
- 사용자가 요구한 관심 키워드 및 질문 상황 관점에서 이 논문이 제공하는 가장 결정적인 인사이트와 시사점.

### 🔗 2. 논문 핵심 기여점 (Contribution) & 공식 코드 (GitHub 주소 포함)
- 논문 제안 방법론의 고유한 혁신성 및 공식 구현 링크 (PDF 내 명시 시 추출).

### 🧮 3. 주요 아키텍처, 핵심 수식 및 실험 성과
- 핵심 알고리즘 구조, 대표적 수식/변수 및 정량적 개선 결과.

### 💡 4. 사용자의 연구 상황에 맞춘 실전 적용 조언 & 한계점
- 본 논문의 연구 한계점과 사용자의 특정 연구 상황/키워드 관점에서 실제 연구 및 프로젝트에 응용할 때 고려해야 할 핵심 팁.
"""

    temp = 0.4 if (custom_context and custom_context.strip()) else 0.2

    for m_name in [model_name, "gemini-3.6-flash", "gemini-3.5-flash"]:
        try:
            model = genai.GenerativeModel(m_name)
            res = model.generate_content([{"mime_type": "application/pdf", "data": response.content}, prompt], generation_config={"max_output_tokens": 8192, "temperature": temp})
            return res.text
        except Exception as e:
            if ("429" in str(e) or "quota" in str(e).lower()) and m_name != "gemini-3.5-flash":
                continue # Try fallback model
            raise ValueError(f"RATE_LIMIT: {str(e)}" if "429" in str(e) or "quota" in str(e).lower() else f"ERROR: {str(e)}")

def compare_papers_with_gemini(api_key, model_name, papers_list):
    genai.configure(api_key=api_key)
    papers_summary = ""
    for i, p in enumerate(papers_list, 1):
        papers_summary += f"### [논문 {i}] {p['title']}\n- 게재일/저자: {p.get('published', '')} / {p.get('authors', '')}\n- 기존 분석/초록 요약:\n{p.get('analysis_result', p.get('summary', ''))[:1000]}\n\n"

    prompt = f"""
    당신은 세계 최고 수준의 수석 연구위원입니다. 아래 선택된 {len(papers_list)}개의 논문들을 정밀 교차 비교 분석해 주십시오.

    다음 항목을 포함하여 시각성이 뛰어나고 깔끔한 마크다운 분석 리포트를 작성해 주십시오:
    1. 📊 **핵심 정밀 비교 표 (Markdown Table)**
       - 컬럼: [구분, 논문 1, 논문 2...]
       - 행: [연구 목적, 핵심 방법론 및 아키텍처, 주요 연구 성과, 한계점]
    2. 💡 **각 논문 간 차별점 및 혁신 요소 상세 비교**
    3. 🎯 **연구자 관점에서의 종합 조언 (상황별 추천 참고 논문)**

    [선택된 비교 논문 목록]
    {papers_summary}
    """

    for m_name in [model_name, "gemini-3.6-flash", "gemini-3.5-flash"]:
        try:
            model = genai.GenerativeModel(m_name)
            res = model.generate_content(prompt, generation_config={"max_output_tokens": 8192, "temperature": 0.2})
            return res.text
        except Exception as e:
            if ("429" in str(e) or "quota" in str(e).lower()) and m_name != "gemini-3.5-flash":
                continue
            raise ValueError(f"RATE_LIMIT: {str(e)}" if "429" in str(e) or "quota" in str(e).lower() else f"ERROR: {str(e)}")

def chat_with_ai_stream(api_key, model_name, user_query, selected_papers_data, chat_history):
    genai.configure(api_key=api_key)
    context_str = ""
    if not selected_papers_data:
        context_str = "현재 선택된 논문이 없습니다. 일반적인 AI 어시스턴트로서 답변하세요."
    else:
        for p in selected_papers_data:
            context_str += f"- 논문 제목: {p['title']}\n- 초록 요약: {p.get('summary', '제공 안됨')}\n- 기존 심층분석: {p.get('analysis_result', '분석 안됨')}\n\n"

    history_text = ""
    for msg in chat_history[-8:]: 
        role = '사용자' if msg['role'] == 'user' else 'AI 비서'
        history_text += f"{role}: {msg['content']}\n"
        
    prompt = f"""
당신은 세계 최고 수준의 연구 보조 AI 비서입니다.
아래 제공된 [선택된 논문 정보]와 [이전 대화 내역]을 참고하여, 사용자의 [질문]에 한국어로 친절하고 전문적으로 답해주세요.
**[⚠️ 매우 중요한 지침 - 환각 방지(Hallucination Prevention)]**
1. 반드시 제공된 [선택된 논문 정보] 내에서만 답변을 생성하십시오.
2. 정보가 없다면 절대 추측하지 말고 모른다고 명확히 밝히십시오.

[선택된 논문 정보]
{context_str}

[이전 대화 내역]
{history_text}

[질문]
{user_query}
"""
    model = genai.GenerativeModel(model_name)
    try:
        res = model.generate_content(prompt, generation_config={"temperature": 0.2}, stream=True)
        for chunk in res:
            yield chunk.text
    except Exception as e:
        if "429" in str(e) or "quota" in str(e).lower():
            yield "🚨 **API 사용량 초과 (Rate Limit / Quota Exceeded)**\n\nGoogle Gemini API의 무료 등급 요청 한도를 초과했습니다. 약 **1~2분 뒤**에 다시 질문해주세요."
        else:
            yield f"에러 발생: {str(e)}"

# --- 💻 메인 앱 & UI ---

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = ""

if not st.session_state.logged_in:
    st.title("🔐 Research Mate 로그인")
    st.caption("나만의 논문 DB와 AI 분석을 위해 로그인하거나 회원가입하세요.")
    if not db:
        st.error("🚨 서버 오류: 데이터베이스(Firebase) 연결에 실패했습니다.")
    else:
        tab_login, tab_signup = st.tabs(["🔑 로그인", "📝 회원가입"])
        with tab_login:
            with st.form(key="login_form"):
                login_id = st.text_input("아이디 (ID)")
                login_pw = st.text_input("비밀번호 (Password)", type="password")
                if st.form_submit_button("로그인", use_container_width=True):
                    if login(login_id, login_pw):
                        st.session_state.logged_in = True
                        st.session_state.username = login_id
                        st.rerun()
                    else: st.error("정보가 올바르지 않습니다.")
        with tab_signup:
            with st.form(key="signup_form"):
                signup_id = st.text_input("새 아이디 (ID)")
                signup_pw = st.text_input("새 비밀번호 (Password)", type="password")
                signup_key = st.text_input("Gemini API Key (선택)", type="password", help="Google AI Studio(aistudio.google.com)에서 발급받은 API 키를 입력하시면 내 계정에 저장됩니다.")
                if st.form_submit_button("회원가입", use_container_width=True):
                    if signup(signup_id, signup_pw, signup_key): st.success("🎉 회원가입 성공! 로그인해주세요.")
                    else: st.error("이미 존재하는 아이디입니다.")
else:
    with st.sidebar:
        st.markdown(f"### 👤 {st.session_state.username}님 환영합니다!")
        
        system_api_key = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
        saved_api_key = get_api_key(st.session_state.username) or system_api_key
        api_key = saved_api_key.strip()
        
        if api_key:
            st.success("🟢 Gemini API 연결됨")
        else:
            st.warning("⚠️ API 키가 등록되지 않았습니다.")

        selected_model = None
        if api_key:
            with st.spinner("AI 모델 불러오는 중..."):
                available_models = get_available_models(api_key)
            if available_models:
                selected_model = st.selectbox("⚙️ AI 모델 선택", options=available_models, index=0)
            else: st.error("API 키 오류")
            
        st.caption("💡 API 키 수정 및 계정 정보 관리는 [⚙️ 회원 설정] 탭에서 하실 수 있습니다.")
        st.markdown("---")
        if st.button("🚪 로그아웃", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.username = ""
            st.rerun()

    st.title("🔬 Research Mate")
    st.caption("AI 기반 맞춤형 심층 분석 및 개인 연구 아카이빙 플랫폼")
    st.markdown("---")
    
    user_categories = get_user_categories(st.session_state.username)
    tab1, tab2, tab3, tab4 = st.tabs(["🔍 논문 탐색 및 업로드", "🗄️ 내 연구 DB (My Library)", "💬 AI 논문 비서", "⚙️ 회원 설정"])

    with tab1:
        col_search, col_upload = st.columns([1, 1])
        with col_search:
            st.markdown("### 🌐 ArXiv 스마트 논문 검색")
            with st.form(key="search_form"):
                search_input = st.text_input("검색어, 연구 주제를 입력하세요 (엔터키로 검색 가능)")
                custom_context_search = st.text_input("맞춤형 분석 요구사항 (선택, 엔터키로 검색 가능)")
                submit_search = st.form_submit_button("🚀 검색", use_container_width=True)


        with col_upload:
            st.markdown("### 📤 내 PC에서 PDF 업로드")
            uploaded_file = st.file_uploader("유료/비공개 논문 PDF 업로드", type=["pdf"])
            custom_context_upload = st.text_area("분석 시 집중할 내용 (선택)", key="ctx_upload")
            
            pdf_cat_options = ["➕ 새 카테고리 직접 추가..."] + user_categories
            pdf_sel_cat = st.selectbox("📋 저장할 카테고리 선택", options=pdf_cat_options, key="upload_cat_sel")
            pdf_custom_cat = ""
            if pdf_sel_cat == "➕ 새 카테고리 직접 추가...":
                pdf_custom_cat = st.text_input("새 카테고리명 입력", key="pdf_custom_cat_input", placeholder="예: 초전도체").strip()
            
            if uploaded_file is not None:
                if st.button("🧠 업로드한 논문 분석 및 저장", type="primary", use_container_width=True):
                    final_pdf_cat = pdf_custom_cat if (pdf_sel_cat == "➕ 새 카테고리 직접 추가..." and pdf_custom_cat) else (pdf_sel_cat if pdf_sel_cat != "➕ 새 카테고리 직접 추가..." else "미분류")
                    if final_pdf_cat and final_pdf_cat not in user_categories and final_pdf_cat != "미분류":
                        user_categories.append(final_pdf_cat)
                        save_user_categories(st.session_state.username, user_categories)

                    if not api_key: st.error("API 키가 필요합니다.")
                    else:
                        with st.spinner("AI가 PDF를 직접 읽고 분석 중입니다..."):
                            try:
                                pdf_bytes = uploaded_file.getvalue()
                                result_text = analyze_local_pdf(api_key, selected_model, pdf_bytes, uploaded_file.name, custom_context_upload)
                                fake_id = str(uuid.uuid4())[:8]
                                paper_to_save = {
                                    "id": f"local_{fake_id}", "title": uploaded_file.name, "en_title": uploaded_file.name,
                                    "authors": "로컬 업로드 논문", "published": datetime.now().strftime("%Y-%m-%d"),
                                    "summary": "로컬 PDF 분석 데이터", "pdf_url": "로컬파일", "analysis_result": result_text,
                                    "category": final_pdf_cat
                                }
                                save_paper_to_db(st.session_state.username, paper_to_save)
                                st.toast(f"🎉 '{uploaded_file.name}'가 [{final_pdf_cat}] 카테고리에 저장되었습니다!", icon="💾")
                                st.success(f"✅ '{uploaded_file.name}' [{final_pdf_cat}] 카테고리 저장 완료!")
                                with st.expander("결과 미리보기", expanded=True): st.markdown(result_text)
                            except ValueError as e:
                                err_msg = str(e)
                                if err_msg.startswith("RATE_LIMIT"):
                                    st.error(f"🚨 **API 사용량 초과 (Rate Limit)**\n\n현재 무료 한도를 초과했습니다. 잠시 후 다시 시도해주세요.\n\n*(상세 원인: {err_msg})*")
                                else:
                                    st.error(f"🚨 분석 중 오류가 발생했습니다: {err_msg}")

        parts = []
        if search_input.strip(): parts.append(search_input.strip())
        if custom_context_search.strip(): parts.append(custom_context_search.strip())
        query_to_search = " ".join(parts)
        
        if submit_search and query_to_search:
            # 1. Clear old paper analysis cache in session state so fresh searches evaluate anew for the current situation!
            for k in list(st.session_state.keys()):
                if k.startswith("result_") or k.startswith("saved_msg_") or k.startswith("show_save_"):
                    del st.session_state[k]

            with st.spinner(f"'{query_to_search}' 관점으로 맞춤 논문을 탐색 중입니다..."):
                try:
                    results, notice_msg = search_arxiv_papers(query_to_search)
                    st.session_state.search_results = results
                    st.session_state.search_notice = notice_msg
                    if not results:
                        st.error("⚠️ 검색 결과가 없거나 ArXiv 서버 응답이 없습니다. 영어 키워드나 다른 검색어로 다시 시도해 보세요.")
                except ValueError as e:
                    if str(e) == "RATE_LIMIT":
                        st.error("🚨 ArXiv 서버 접근 제한(Rate Limit)에 걸렸습니다. 1~2분 정도 후에 다시 시도해주세요.")
                    else:
                        st.error(f"🚨 ArXiv 서버 응답 지연(Timeout) 또는 접속 오류가 발생했습니다. 잠시 후 다시 시도해 주세요. ({e})")
                    st.session_state.search_results = []
                    st.session_state.search_notice = None

        if st.session_state.get("search_results"):
            st.markdown("### 📊 ArXiv 검색 결과")
            if st.session_state.get("search_notice"):
                st.info(st.session_state.search_notice)
            for idx, paper in enumerate(st.session_state.search_results):
                with st.expander(f"📄 {paper['title'][:40]}...", expanded=False):
                    st.caption(f"✍️ {paper['authors']} | 📅 {paper['published']} | 🆔 {paper['id']}")
                    st.write(f"{paper['summary'][:200]}...")
                    
                    # 🔗 논문 원문 PDF & ArXiv 원문 웹페이지 바로가기 버튼
                    col_link_pdf, col_link_abs = st.columns([1, 1])
                    with col_link_pdf:
                        st.link_button("📄 논문 원문 PDF 열기", paper['pdf_url'], use_container_width=True)
                    with col_link_abs:
                        st.link_button("🌐 ArXiv 원문 웹페이지", f"https://arxiv.org/abs/{paper['id']}", use_container_width=True)
                    
                    btn_analyze = st.button("🧠 AI 심층 분석", key=f"ana_{paper['id']}", use_container_width=True)
                    
                    # DB 저장 토글 버튼 & 패널
                    is_save_open = st.session_state.get(f"show_save_{paper['id']}", False)
                    if st.button("💾 내 DB에 저장", key=f"btn_toggle_save_{paper['id']}", type="primary", use_container_width=True):
                        st.session_state[f"show_save_{paper['id']}"] = not is_save_open
                        st.rerun()

                    if st.session_state.get(f"show_save_{paper['id']}", False):
                        with st.container(border=True):
                            st.markdown("#### 📋 저장할 카테고리 지정")
                            arxiv_cat_opts = ["➕ 새 카테고리 직접 추가..."] + user_categories
                            arxiv_sel_cat = st.selectbox("📋 카테고리 선택", options=arxiv_cat_opts, key=f"pop_cat_sel_{paper['id']}")
                            
                            arxiv_custom_cat = ""
                            if arxiv_sel_cat == "➕ 새 카테고리 직접 추가...":
                                arxiv_custom_cat = st.text_input("새 카테고리명 입력", key=f"pop_custom_cat_{paper['id']}", placeholder="예: 초전도체").strip()
                            
                            cs1, cs2 = st.columns([1, 1])
                            with cs1:
                                if st.button("✅ 내 DB에 저장", key=f"btn_confirm_save_{paper['id']}", type="primary", use_container_width=True):
                                    final_arxiv_cat = arxiv_custom_cat if (arxiv_sel_cat == "➕ 새 카테고리 직접 추가..." and arxiv_custom_cat) else (arxiv_sel_cat if arxiv_sel_cat != "➕ 새 카테고리 직접 추가..." else "미분류")
                                    if final_arxiv_cat and final_arxiv_cat not in user_categories and final_arxiv_cat != "미분류":
                                        user_categories.append(final_arxiv_cat)
                                        save_user_categories(st.session_state.username, user_categories)

                                    paper_to_save = paper.copy()
                                    paper_to_save['analysis_result'] = st.session_state.get(f"result_{paper['id']}", "분석 안됨")
                                    paper_to_save['category'] = final_arxiv_cat
                                    save_paper_to_db(st.session_state.username, paper_to_save)
                                    
                                    st.session_state[f"show_save_{paper['id']}"] = False # 패널 자동 닫기!
                                    st.toast(f"🎉 [{final_arxiv_cat}] 카테고리에 저장되었습니다!", icon="💾")
                                    st.session_state[f"saved_msg_{paper['id']}"] = f"✅ [{final_arxiv_cat}] 카테고리에 성공적으로 저장되었습니다!"
                                    st.rerun()
                            with cs2:
                                if st.button("❌ 닫기", key=f"btn_close_save_{paper['id']}", use_container_width=True):
                                    st.session_state[f"show_save_{paper['id']}"] = False
                                    st.rerun()

                    if f"saved_msg_{paper['id']}" in st.session_state:
                        st.success(st.session_state[f"saved_msg_{paper['id']}"])

                    # 인용 팝오버 버튼
                    with st.popover("🔖 인용 정보 (Citation)", use_container_width=True):
                        apa, bibtex = get_citation(paper)
                        st.markdown("**APA 포맷**")
                        st.code(apa, language="text")
                        st.markdown("**BibTeX 포맷**")
                        st.code(bibtex, language="bibtex")
                    
                    if btn_analyze:
                        if not api_key: st.error("API 키가 필요합니다.")
                        else:
                            with st.spinner("정밀 분석 중..."):
                                try:
                                    res_text = analyze_paper_with_gemini(api_key, selected_model, paper['pdf_url'], custom_context_search)
                                    st.session_state[f"result_{paper['id']}"] = res_text
                                except ValueError as e:
                                    err_msg = str(e)
                                    if err_msg.startswith("RATE_LIMIT"):
                                        st.error(f"🚨 **API 사용량 초과 (Rate Limit)**\n\n현재 무료 한도를 초과했습니다. 잠시 후 다시 시도해주세요.\n\n*(상세 원인: {err_msg})*")
                                    else:
                                        st.error(f"🚨 분석 중 오류가 발생했습니다: {err_msg}")
                    if f"result_{paper['id']}" in st.session_state:
                        st.markdown(st.session_state[f"result_{paper['id']}"])

    with tab2:
        st.markdown(f"### 🗄️ {st.session_state.username}님의 연구 논문 아카이브")
        saved_papers = get_saved_papers(st.session_state.username)
        if not saved_papers: st.info("저장된 논문이 없습니다. [🔍 논문 탐색 및 업로드] 탭에서 관심 있는 논문을 저장해 보세요.")
        else:
            # 📊 라이브러리 통계 요약 및 전체 BibTeX 내보내기
            c_s1, c_s2, c_s3 = st.columns([1, 1, 2])
            analyzed_cnt = len([p for p in saved_papers if p.get('analysis_result') not in ["분석 안됨", "분석 없음", None]])
            c_s1.metric("총 아카이빙 논문", f"{len(saved_papers)}편")
            c_s2.metric("AI 심층 분석 완료", f"{analyzed_cnt}편")
            
            with c_s3:
                all_bibtex = "\n\n".join([get_citation(p)[1] for p in saved_papers])
                st.download_button(
                    "📥 라이브러리 전체 BibTeX 다운로드 (.bib)",
                    data=all_bibtex,
                    file_name=f"{st.session_state.username}_research_library.bib",
                    mime="text/plain",
                    use_container_width=True
                )
            
            st.markdown("---")
            
            # ⚖️ AI 논문 교차 비교 분석 기능
            with st.expander("⚖️ AI 논문 교차 비교 분석 (2개 이상 선택)", expanded=False):
                st.caption("아카이브에 저장된 논문 중 비교하고 싶은 논문들을 선택하면 AI가 핵심 성능, 방법론, 장단점을 한눈에 표로 교차 비교해 드립니다.")
                paper_options = {f"{p['title']} ({p.get('published', '')[:4]})": p for p in saved_papers}
                selected_titles = st.multiselect("비교할 논문을 선택하세요 (2~5개)", options=list(paper_options.keys()))
                
                if st.button("🚀 선택한 논문 교차 비교 실행", type="primary"):
                    if len(selected_titles) < 2:
                        st.warning("⚠️ 최소 2개 이상의 논문을 선택해 주십시오.")
                    elif not api_key:
                        st.error("🚨 API 키가 필요합니다.")
                    else:
                        selected_papers_list = [paper_options[t] for t in selected_titles]
                        with st.spinner("AI가 선택된 논문들의 핵심 방법론, 성과, 차별점을 교차 비교 중입니다..."):
                            try:
                                compare_res = compare_papers_with_gemini(api_key, selected_model, selected_papers_list)
                                st.session_state["paper_compare_result"] = compare_res
                            except ValueError as e:
                                st.error(f"🚨 비교 분석 중 오류가 발생했습니다: {e}")

                if "paper_compare_result" in st.session_state:
                    st.markdown("---")
                    st.markdown(st.session_state["paper_compare_result"])

            # 📋 카테고리 필터링 및 관리 Bar
            all_existing_cats = list(dict.fromkeys(user_categories + [p.get('category', '미분류') for p in saved_papers]))
            
            c_filter1, c_filter2, c_filter3 = st.columns([2, 1, 1])
            with c_filter1:
                selected_cat_filter = st.selectbox("📋 카테고리 필터", options=["전체 보기"] + all_existing_cats)
            with c_filter2:
                st.write("") # alignment spacing
                is_add_open = st.session_state.get("show_add_cat_tab2", False)
                if st.button("➕ 카테고리 추가", key="btn_toggle_add_cat_tab2", use_container_width=True):
                    st.session_state["show_add_cat_tab2"] = not is_add_open
                    st.rerun()
            with c_filter3:
                st.write("") # alignment spacing
                is_del_open = st.session_state.get("show_del_cat_tab2", False)
                if st.button("🗑️ 카테고리 삭제", key="btn_toggle_del_cat_tab2", use_container_width=True):
                    st.session_state["show_del_cat_tab2"] = not is_del_open
                    st.rerun()

            if st.session_state.get("show_add_cat_tab2", False):
                with st.container(border=True):
                    st.markdown("#### ➕ 새 카테고리 생성")
                    new_cat_tab2 = st.text_input("새 카테고리명 입력", key="tab2_new_cat_input", placeholder="예: 초전도체").strip()
                    ca1, ca2 = st.columns([1, 1])
                    with ca1:
                        if st.button("카테고리 생성", key="btn_create_cat_tab2", type="primary", use_container_width=True):
                            if new_cat_tab2 and new_cat_tab2 not in user_categories:
                                user_categories.append(new_cat_tab2)
                                save_user_categories(st.session_state.username, user_categories)
                                st.session_state["show_add_cat_tab2"] = False # 패널 자동 닫기!
                                st.toast(f"✅ '{new_cat_tab2}' 카테고리가 생성되었습니다!", icon="📋")
                                st.rerun()
                            elif not new_cat_tab2:
                                st.error("카테고리명을 입력하세요.")
                    with ca2:
                        if st.button("❌ 닫기", key="btn_close_add_cat_tab2", use_container_width=True):
                            st.session_state["show_add_cat_tab2"] = False
                            st.rerun()

            if st.session_state.get("show_del_cat_tab2", False):
                with st.container(border=True):
                    st.markdown("#### 🗑️ 카테고리 개별 삭제")
                    if not user_categories:
                        st.info("삭제할 사용자 카테고리가 없습니다.")
                    else:
                        cat_to_del = st.selectbox("삭제할 카테고리 선택", options=user_categories, key="del_cat_select")
                        papers_in_cat = [p for p in saved_papers if p.get('category') == cat_to_del]
                        
                        if not papers_in_cat:
                            st.caption("ℹ️ 해당 카테고리에 포함된 논문이 없습니다.")
                            cd1, cd2 = st.columns([1, 1])
                            with cd1:
                                if st.button("🗑️ 카테고리 삭제 실행", type="primary", key="btn_del_empty_cat", use_container_width=True):
                                    user_categories.remove(cat_to_del)
                                    save_user_categories(st.session_state.username, user_categories)
                                    st.session_state["show_del_cat_tab2"] = False # 패널 자동 닫기!
                                    st.toast(f"✅ '{cat_to_del}' 카테고리가 삭제되었습니다!", icon="🗑️")
                                    st.rerun()
                            with cd2:
                                if st.button("❌ 닫기", key="btn_close_del_empty_cat", use_container_width=True):
                                    st.session_state["show_del_cat_tab2"] = False
                                    st.rerun()
                        else:
                            st.warning(f"⚠️ **'{cat_to_del}'** 카테고리에 **{len(papers_in_cat)}편**의 논문이 들어 있습니다.")
                            del_action = st.radio("논문 처리 방식 선택", options=["🚚 다른 카테고리로 논문 이동", "🗑️ 논문도 함께 DB에서 삭제"], key="del_cat_action")
                            
                            other_cats = [c for c in user_categories if c != cat_to_del] + ["미분류"]
                            if del_action == "🚚 다른 카테고리로 논문 이동":
                                move_target_cat = st.selectbox("이동할 카테고리 선택", options=other_cats, key="move_target_cat_select")
                                cm1, cm2 = st.columns([1, 1])
                                with cm1:
                                    if st.button(f"🚚 논문 {len(papers_in_cat)}편 이동 후 삭제", type="primary", key="btn_move_del_cat", use_container_width=True):
                                        for p in papers_in_cat:
                                            p['category'] = move_target_cat
                                            save_paper_to_db(st.session_state.username, p)
                                        if cat_to_del in user_categories:
                                            user_categories.remove(cat_to_del)
                                            save_user_categories(st.session_state.username, user_categories)
                                        st.session_state["show_del_cat_tab2"] = False # 패널 자동 닫기!
                                        st.toast(f"🚚 논문 {len(papers_in_cat)}편을 '{move_target_cat}'(으)로 이동하고 '{cat_to_del}' 카테고리를 삭제했습니다!", icon="✅")
                                        st.rerun()
                                with cm2:
                                    if st.button("❌ 닫기", key="btn_close_move_del_cat", use_container_width=True):
                                        st.session_state["show_del_cat_tab2"] = False
                                        st.rerun()
                            else:
                                cp1, cp2 = st.columns([1, 1])
                                with cp1:
                                    if st.button(f"🔥 논문 {len(papers_in_cat)}편 및 카테고리 삭제", type="primary", key="btn_purge_del_cat", use_container_width=True):
                                        for p in papers_in_cat:
                                            delete_paper_from_db(st.session_state.username, p['id'])
                                        if cat_to_del in user_categories:
                                            user_categories.remove(cat_to_del)
                                            save_user_categories(st.session_state.username, user_categories)
                                        st.session_state["show_del_cat_tab2"] = False # 패널 자동 닫기!
                                        st.toast(f"💥 '{cat_to_del}' 카테고리와 논문 {len(papers_in_cat)}편이 영구 삭제되었습니다!", icon="🗑️")
                                        st.rerun()
                                with cp2:
                                    if st.button("❌ 닫기", key="btn_close_purge_del_cat", use_container_width=True):
                                        st.session_state["show_del_cat_tab2"] = False
                                        st.rerun()

            if selected_cat_filter != "전체 보기":
                display_papers = [p for p in saved_papers if p.get('category', '미분류') == selected_cat_filter]
            else:
                display_papers = saved_papers

            st.markdown("---")
            st.markdown(f"#### 📄 아카이브 논문 목록 ({selected_cat_filter}: {len(display_papers)}편)")
            if not display_papers:
                st.warning(f"'{selected_cat_filter}' 카테고리에 해당하는 논문이 없습니다.")
            for p in reversed(display_papers):
                with st.container():
                    col_p_title, col_p_cat = st.columns([3, 1])
                    with col_p_title:
                        st.markdown(f"#### 📌 {p['title']}")
                        p_cat = p.get('category', '미분류')
                        st.caption(f"📋 **카테고리**: `{p_cat}` | 🆔 {p['id']} | 💾 {p['saved_at']}")
                    with col_p_cat:
                        cur_cat = p.get('category', '미분류')
                        is_mod_open = st.session_state.get(f"show_mod_{p['id']}", False)
                        if st.button(f"📋 카테고리 변경 ({cur_cat})", key=f"btn_toggle_mod_{p['id']}", use_container_width=True):
                            st.session_state[f"show_mod_{p['id']}"] = not is_mod_open
                            st.rerun()

                        if st.session_state.get(f"show_mod_{p['id']}", False):
                            with st.container(border=True):
                                st.markdown("#### 📋 카테고리 변경")
                                mod_cat_opts = ["➕ 새 카테고리 직접 추가..."] + user_categories
                                cur_idx = mod_cat_opts.index(cur_cat) if cur_cat in mod_cat_opts else 0
                                selected_mod_cat = st.selectbox("변경할 카테고리", options=mod_cat_opts, index=cur_idx, key=f"mod_sel_{p['id']}")
                                
                                custom_mod_cat = ""
                                if selected_mod_cat == "➕ 새 카테고리 직접 추가...":
                                    custom_mod_cat = st.text_input("새 카테고리명 입력", key=f"mod_custom_{p['id']}", placeholder="예: 초전도체").strip()
                                
                                cmc1, cmc2 = st.columns([1, 1])
                                with cmc1:
                                    if st.button("변경 저장", key=f"btn_save_mod_{p['id']}", type="primary", use_container_width=True):
                                        target_mod_cat = custom_mod_cat if (selected_mod_cat == "➕ 새 카테고리 직접 추가..." and custom_mod_cat) else (selected_mod_cat if selected_mod_cat != "➕ 새 카테고리 직접 추가..." else "미분류")
                                        if target_mod_cat and target_mod_cat not in user_categories and target_mod_cat != "미분류":
                                            user_categories.append(target_mod_cat)
                                            save_user_categories(st.session_state.username, user_categories)
                                        
                                        p['category'] = target_mod_cat
                                        save_paper_to_db(st.session_state.username, p)
                                        st.session_state[f"show_mod_{p['id']}"] = False # 패널 자동 닫기!
                                        st.toast(f"✅ 카테고리가 [{target_mod_cat}](으)로 변경되었습니다!", icon="📋")
                                        st.rerun()
                                with cmc2:
                                    if st.button("❌ 닫기", key=f"btn_close_mod_{p['id']}", use_container_width=True):
                                        st.session_state[f"show_mod_{p['id']}"] = False
                                        st.rerun()

                    has_analysis = p.get('analysis_result') not in ["분석 안됨", "분석 없음", None]
                    with st.expander("🧠 AI 심층 분석 결과", expanded=has_analysis):
                        st.markdown(p.get('analysis_result', '분석 없음'))
                    
                    if not has_analysis and p.get('pdf_url') != '로컬파일':
                        col_ctx, col_btn = st.columns([3, 1])
                        with col_ctx:
                            ctx_tab2 = st.text_input("맞춤형 분석 요구사항 (선택)", key=f"ctx_tab2_{p['id']}")
                        with col_btn:
                            st.write("") # for alignment
                            if st.button("🧠 심층 분석 실행", key=f"ana_tab2_{p['id']}", use_container_width=True):
                                if not api_key: st.error("API 키가 필요합니다.")
                                else:
                                    with st.spinner("정밀 분석 중..."):
                                        try:
                                            res_text = analyze_paper_with_gemini(api_key, selected_model, p['pdf_url'], ctx_tab2)
                                            p['analysis_result'] = res_text
                                            save_paper_to_db(st.session_state.username, p)
                                            st.rerun()
                                        except ValueError as e:
                                            err_msg = str(e)
                                            if err_msg.startswith("RATE_LIMIT"):
                                                st.error(f"🚨 **API 사용량 초과 (Rate Limit)**\n\n현재 무료 한도를 초과했습니다. 잠시 후 다시 시도해주세요.\n\n*(상세 원인: {err_msg})*")
                                            else:
                                                st.error(f"🚨 분석 중 오류가 발생했습니다: {err_msg}")
                    
                    c1, c2, c3 = st.columns([6, 2, 2])
                    if p.get('pdf_url') != '로컬파일': 
                        with c1:
                            col_tab2_pdf, col_tab2_abs = st.columns([1, 1])
                            with col_tab2_pdf:
                                st.link_button("📄 원문 PDF 열기", p['pdf_url'], use_container_width=True)
                            with col_tab2_abs:
                                st.link_button("🌐 ArXiv 원문", f"https://arxiv.org/abs/{p['id']}", use_container_width=True)
                    with c2:
                        with st.popover("🔖 인용 복사", use_container_width=True):
                            apa, bibtex = get_citation(p)
                            st.markdown("**APA**"); st.code(apa, language="text")
                            st.markdown("**BibTeX**"); st.code(bibtex, language="bibtex")
                    with c3:
                        if st.button("🗑️ 삭제", key=f"del_p_{p['id']}", type="secondary", use_container_width=True):
                            delete_paper_from_db(st.session_state.username, p['id']); st.rerun() 
                st.markdown("---")

    with tab3:
        col_nav, col_chat = st.columns([1, 3])
        with col_nav:
            st.markdown("### 🗂️ 채팅방 목록")
            if st.button("➕ 새로운 채팅 시작", use_container_width=True, type="primary"):
                st.session_state.current_chat_session = create_chat_session(st.session_state.username)
                st.rerun()
                
            sessions = get_chat_sessions(st.session_state.username)
            if not sessions: st.info("채팅 내역이 없습니다.")
            else:
                if "current_chat_session" not in st.session_state or st.session_state.current_chat_session is None:
                    st.session_state.current_chat_session = sessions[0]['id']
                    
                for s in sessions:
                    with st.container(border=True):
                        title_text = s.get('title', '새 채팅')
                        is_shared = s.get('is_shared', False)
                        
                        btn_type = "primary" if st.session_state.get('current_chat_session') == s['id'] else "secondary"
                        if st.button(f"💬 {title_text}", key=f"sess_{s['id']}", use_container_width=True, type=btn_type):
                            st.session_state.current_chat_session = s['id']
                            st.rerun()
                        
                        sc1, sc2 = st.columns([1, 1])
                        with sc1:
                            if st.button("🗑️", key=f"del_s_{s['id']}", use_container_width=True):
                                delete_chat_session(st.session_state.username, s['id'])
                                if st.session_state.get('current_chat_session') == s['id']:
                                    st.session_state.current_chat_session = None
                                st.rerun()
                        with sc2:
                            with st.popover("🔗 공유", use_container_width=True):
                                st.write("팀원과 대화 내역(읽기 전용)을 공유합니다.")
                                new_share_status = st.toggle("링크 공유 활성화", value=is_shared, key=f"tg_{s['id']}")
                                if new_share_status != is_shared:
                                    share_chat_session(st.session_state.username, s['id'], new_share_status)
                                    st.rerun()
                                if new_share_status:
                                    share_link = f"/?shared_user={st.session_state.username}&shared_chat={s['id']}"
                                    st.info("아래 링크 주소를 복사하여 전달하세요:")
                                    st.markdown(f"[공유 링크 열기 (우클릭하여 주소 복사)]({share_link})")
                                    st.code(share_link, language="text")

        with col_chat:
            curr_session = st.session_state.get('current_chat_session')
            if curr_session:
                hc1, hc2 = st.columns([8, 2])
                with hc1: st.markdown("### 💬 AI 논문 비서")
                with hc2:
                    chat_history = get_chat_history(st.session_state.username, curr_session)
                    curr_session_title = next((s['title'] for s in sessions if s['id'] == curr_session), '새 채팅')
                    if chat_history:
                        md_log = export_chat_as_markdown(chat_history, curr_session_title)
                        st.download_button("⬇️ 대화 내보내기", md_log, file_name=f"{curr_session_title}_노트.md", use_container_width=True)
                
                saved_papers = get_saved_papers(st.session_state.username)
                paper_options = {p['title']: p for p in saved_papers}
                selected_titles = st.multiselect("🧠 대화에 참고할 논문 선택:", options=list(paper_options.keys()), key=f"multi_{curr_session}")
                selected_papers_data = [paper_options[t] for t in selected_titles]
                
                st.caption("💡 추천 질문 (클릭 시 자동 전송)")
                bc1, bc2, bc3, bc4 = st.columns(4)
                auto_query = None
                with bc1: 
                    if st.button("📄 핵심 요약", use_container_width=True): auto_query = "선택된 논문들의 핵심 내용을 알기 쉽게 요약해 줘."
                with bc2: 
                    if st.button("🔬 방법론 비교", use_container_width=True): auto_query = "선택된 논문들이 사용한 연구 방법론의 차이점과 특징을 비교해 줘."
                with bc3: 
                    if st.button("⚠️ 한계점 파악", use_container_width=True): auto_query = "선택된 논문들이 공통적으로 가진 한계점이나 아쉬운 점을 찾아 줘."
                with bc4:
                    if st.button("📑 다중 논문 통합 보고서", use_container_width=True): auto_query = "선택된 여러 논문을 종합하여 '최근 연구 동향 보고서'를 작성해 줘. 주요 학설 대립과 향후 과제를 반드시 포함해 줘."
                
                chat_container = st.container(height=400)
                with chat_container:
                    if not chat_history: st.info("새로운 대화를 시작했습니다! 단축 버튼을 누르거나 질문해 보세요.")
                    for msg in chat_history:
                        with st.chat_message(msg["role"]): st.markdown(msg["content"])
                
                user_query = st.chat_input("여기에 질문을 입력하세요...")
                final_query = auto_query if auto_query else user_query

                if final_query:
                    if not api_key: st.error("API 키를 입력해주세요.")
                    else:
                        current_session_info = next((s for s in sessions if s['id'] == curr_session), None)
                        if current_session_info and current_session_info.get('title', '새 채팅') == '새 채팅':
                            new_title = generate_chat_title(api_key, selected_model, final_query)
                            update_chat_session_title(st.session_state.username, curr_session, new_title)

                        with chat_container:
                            with st.chat_message("user"): st.markdown(final_query)
                        save_chat_message(st.session_state.username, curr_session, "user", final_query)
                        
                        with chat_container:
                            with st.chat_message("assistant"):
                                response_stream = chat_with_ai_stream(api_key, selected_model, final_query, selected_papers_data, get_chat_history(st.session_state.username, curr_session))
                                # 실시간 스트리밍 출력!
                                ai_response = st.write_stream(response_stream)
                        save_chat_message(st.session_state.username, curr_session, "assistant", ai_response)

    with tab4:
        st.markdown("### ⚙️ 회원 설정 및 계정 관리")
        st.caption("API 키 관리 및 비밀번호 변경 등 내 계정 정보를 설정합니다.")
        st.markdown("---")
        
        col_acc1, col_acc2 = st.columns([1, 1])
        with col_acc1:
            st.markdown("#### 🔑 Google Gemini API 키 설정")
            current_key = get_api_key(st.session_state.username)
            if current_key:
                masked_key = current_key[:6] + "****************" if len(current_key) > 6 else "******"
                st.info(f"🔒 **현재 등록된 API 키**: `{masked_key}`")
            else:
                st.warning("현재 저장된 개인 API 키가 없습니다. (시스템 기본 키 사용 중)")
                
            with st.form(key="update_api_key_form"):
                new_key_input = st.text_input("새 Gemini API Key 입력", type="password", help="Google AI Studio(aistudio.google.com)에서 발급받은 API 키를 입력하세요.")
                if st.form_submit_button("💾 API 키 저장 및 업데이트", type="primary", use_container_width=True):
                    if new_key_input.strip():
                        save_api_key(st.session_state.username, new_key_input)
                        st.toast("🎉 API 키가 성공적으로 저장되었습니다!", icon="🔑")
                        st.success("✅ API 키가 성공적으로 업데이트되었습니다.")
                        st.rerun()
                    else:
                        st.error("올바른 API 키를 입력해주세요.")

        with col_acc2:
            st.markdown("#### 🔒 비밀번호 변경")
            with st.form(key="update_pw_form"):
                new_pw_input = st.text_input("새 비밀번호 입력", type="password")
                confirm_pw_input = st.text_input("새 비밀번호 확인", type="password")
                if st.form_submit_button("💾 비밀번호 변경", type="primary", use_container_width=True):
                    if not new_pw_input.strip():
                        st.error("새 비밀번호를 입력해주세요.")
                    elif new_pw_input != confirm_pw_input:
                        st.error("비밀번호 확인이 일치하지 않습니다.")
                    else:
                        if update_password(st.session_state.username, new_pw_input):
                            st.toast("🎉 비밀번호가 변경되었습니다!", icon="🔒")
                            st.success("✅ 비밀번호가 성공적으로 변경되었습니다.")
                        else:
                            st.error("비밀번호 변경 중 오류가 발생했습니다.")

