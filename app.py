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
        filtered = [m for m in all_models if ("pro" in m or "flash" in m) and "embedding" not in m and "imagen" not in m and "aqa" not in m]
        return filtered if filtered else all_models
    except Exception:
        return ["gemini-3.1-pro", "gemini-1.5-pro", "gemini-2.0-flash", "gemini-1.5-flash"]

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

def signup(username, password):
    if not db: return False
    doc_ref = db.collection('users').document(username)
    if doc_ref.get().exists: return False
    doc_ref.set({'password': hash_password(password), 'api_key': ""})
    return True

def login(username, password):
    if not db: return False
    doc_ref = db.collection('users').document(username)
    doc = doc_ref.get()
    if doc.exists and doc.to_dict().get('password') == hash_password(password):
        return True
    return False

def save_api_key(username, api_key):
    if not db: return
    db.collection('users').document(username).update({'api_key': api_key})

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
        prompt = f"다음 사용자의 질문을 바탕으로 3~5단어 길이의 짧고 직관적인 채팅방 제목을 만들어주세요. 따옴표나 특수기호 없이 핵심 제목만 출력하세요.\n\n질문 내용: {first_query}"
        model = genai.GenerativeModel(model_name)
        res = model.generate_content(prompt, generation_config={"temperature": 0.3})
        return res.text.strip().replace('"', '').replace("'", "")
    except Exception:
        return "새 대화"

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

def parse_smart_query(user_query):
    q = user_query.strip().lower()
    match = re.search(r'\d{4}\.\d{4,5}', q)
    if match: return f"id:{match.group(0)}", f"ArXiv ID: {match.group(0)}"

    keyword_map = {
        "초전도": 'all:"superconductivity" OR all:"HTS"', "트랜스포머": 'all:"transformer" AND all:"attention"',
        "생성형": 'all:"generative model"', "비전": 'all:"computer vision"', "로봇": 'all:"robotics"',
        "자율주행": 'all:"autonomous driving"', "이슈": 'all:"deep learning"', "핫한": 'all:"deep learning"'
    }
    
    search_terms = []
    for ko_word, en_query in keyword_map.items():
        if ko_word in q: search_terms.append(f"({en_query})")
            
    if any(w in q for w in ["ai", "인공지능", "llm", "머신러닝", "딥러닝"]):
        search_terms.append('(all:"artificial intelligence" OR all:"large language model")')
        
    if search_terms:
        final_query = " AND ".join(search_terms)
    else:
        clean = re.sub(r'[^\w\s가-힣]', '', q)
        for word in ["추천해줘", "찾아줘", "대해", "요즘", "핫한", "알려줘", "이슈가", "되는", "최신", "논문"]:
            clean = clean.replace(word, "")
        clean = clean.strip()
        
        if not clean:
            clean = "deep learning"

        if re.search(r'[가-힣]', clean):
            en_query = translate_to_en(clean)
        else:
            en_query = clean

        final_query = f'all:"{en_query}"'

    return urllib.parse.quote(final_query), "번역 검색 완료"

@st.cache_data(ttl=3600, show_spinner=False)
def search_arxiv_papers(user_query, max_results=4):
    import time
    arxiv_query, _ = parse_smart_query(user_query)
    try:
        url = f"https://export.arxiv.org/api/query?search_query={arxiv_query}&start=0&max_results={max_results}&sortBy=relevance&sortOrder=descending"
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
            
            papers.append({
                "id": clean_id,
                "title": ko_title,
                "en_title": title,
                "authors": ", ".join([a.find('{http://www.w3.org/2005/Atom}name').text for a in entry.findall('{http://www.w3.org/2005/Atom}author')][:3]),
                "published": entry.find('{http://www.w3.org/2005/Atom}published').text[:10],
                "summary": ko_summary,
                "pdf_url": f"https://arxiv.org/pdf/{clean_id}.pdf"
            })
        return papers
    except ValueError as ve:
        raise ve
    except Exception:
        return []

# --- 🤖 AI 분석 및 챗봇 로직 (스트리밍) ---
def analyze_local_pdf(api_key, model_name, pdf_bytes, filename, custom_context):
    try:
        genai.configure(api_key=api_key)
        context_prompt = f"\n\n**[사용자의 현재 연구 상황 및 특별 요구사항]**:\n{custom_context}\n(위 요구사항을 최우선적으로 반영하여 분석 리포트를 작성해 주십시오.)" if custom_context else ""
        prompt = """
        당신은 세계 최고 수준의 시각 및 텍스트 융합 논문 분석 전문가입니다.
        업로드된 로컬 PDF 논문을 바탕으로 다음 3가지를 가시성이 뛰어나고 깔끔한 마크다운 형식으로 정리해 주십시오:
        ### 🔗 1. 핵심 요약 및 기여점
        ### 🧮 2. 핵심 수식 및 변수 분석 (해당 시)
        ### 📊 3. 주요 아키텍처 및 시각적 인사이트
        """ + context_prompt
        model = genai.GenerativeModel(model_name)
        res = model.generate_content([{"mime_type": "application/pdf", "data": pdf_bytes}, prompt], generation_config={"max_output_tokens": 8192, "temperature": 0.2})
        return res.text
    except Exception as e:
        if "429" in str(e) or "quota" in str(e).lower():
            raise ValueError(f"RATE_LIMIT: {str(e)}")
        raise ValueError(f"ERROR: {str(e)}")

def analyze_paper_with_gemini(api_key, model_name, pdf_url, custom_context):
    try:
        genai.configure(api_key=api_key)
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(pdf_url, headers=headers, timeout=20)
        response.raise_for_status()
        context_prompt = f"\n\n**[사용자의 현재 연구 상황 및 특별 요구사항]**:\n{custom_context}" if custom_context else ""
        prompt = """
        당신은 세계 최고 수준의 시각 및 텍스트 융합 논문 분석 전문가입니다.
        첨부된 PDF 논문을 바탕으로 다음을 정리해 주십시오:
        ### 🔗 1. 공식 코드(GitHub) 주소
        ### 🧮 2. 핵심 수식 및 변수 분석
        ### 📊 3. 주요 아키텍처 및 시각적 인사이트
        """ + context_prompt
        model = genai.GenerativeModel(model_name)
        res = model.generate_content([{"mime_type": "application/pdf", "data": response.content}, prompt], generation_config={"max_output_tokens": 8192, "temperature": 0.2})
        return res.text
    except Exception as e:
        if "429" in str(e) or "quota" in str(e).lower():
            raise ValueError(f"RATE_LIMIT: {str(e)}")
        raise ValueError(f"ERROR: {str(e)}")

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
                if st.form_submit_button("회원가입", use_container_width=True):
                    if signup(signup_id, signup_pw): st.success("회원가입 성공! 로그인해주세요.")
                    else: st.error("이미 존재하는 아이디입니다.")
else:
    with st.sidebar:
        st.markdown(f"### 👤 {st.session_state.username}님 환영합니다!")
        if st.button("로그아웃"):
            st.session_state.logged_in = False
            st.session_state.username = ""
            st.rerun()
            
        st.markdown("---")
        st.markdown("### 🔑 Google AI Studio 설정")
        saved_api_key = get_api_key(st.session_state.username)
        api_key = st.text_input("Gemini API Key를 입력하세요", type="password", value=saved_api_key)
        if api_key and api_key != saved_api_key: save_api_key(st.session_state.username, api_key)
        
        selected_model = None
        if api_key:
            with st.spinner("AI 모델 불러오는 중..."):
                available_models = get_available_models(api_key)
            if available_models:
                st.markdown("---")
                default_idx = 0
                for i, m in enumerate(available_models):
                    if "3.1" in m or "pro" in m:
                        default_idx = i; break
                selected_model = st.selectbox("⚙️ AI 모델", options=available_models, index=default_idx)
            else: st.error("API 키 오류")

    st.title("🔬 Research Mate")
    st.caption("AI 기반 맞춤형 심층 분석 및 개인 연구 아카이빙 플랫폼")
    st.markdown("---")
    
    tab1, tab2, tab3 = st.tabs(["🔍 논문 탐색 및 업로드", "🗄️ 내 연구 DB (My Library)", "💬 AI 논문 비서"])

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
            
            if uploaded_file is not None:
                if st.button("🧠 업로드한 논문 분석 및 저장", type="primary", use_container_width=True):
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
                                    "summary": "로컬 PDF 분석 데이터", "pdf_url": "로컬파일", "analysis_result": result_text
                                }
                                save_paper_to_db(st.session_state.username, paper_to_save)
                                st.success(f"'{uploaded_file.name}' 저장 완료!")
                                with st.expander("결과 미리보기", expanded=True): st.markdown(result_text)
                            except ValueError as e:
                                err_msg = str(e)
                                if err_msg.startswith("RATE_LIMIT"):
                                    st.error(f"🚨 **API 사용량 초과 (Rate Limit)**\n\n현재 무료 한도를 초과했습니다. 잠시 후 다시 시도해주세요.\n\n*(상세 원인: {err_msg})*")
                                else:
                                    st.error(f"🚨 분석 중 오류가 발생했습니다: {err_msg}")

        query_to_search = search_input.strip() or custom_context_search.strip()
        if submit_search and query_to_search:
            with st.spinner("논문을 찾고 있습니다... (잠시만 기다려주세요)"):
                try:
                    results = search_arxiv_papers(query_to_search)
                    st.session_state.search_results = results
                    if not results:
                        st.error("⚠️ 검색 결과가 없거나 ArXiv 서버 응답이 없습니다. 영어 키워드나 다른 검색어로 다시 시도해 보세요.")
                except ValueError as e:
                    if str(e) == "RATE_LIMIT":
                        st.error("🚨 ArXiv 서버 접근 제한(Rate Limit)에 걸렸습니다. 1~2분 정도 후에 다시 시도해주세요.")
                    else:
                        st.error(f"🚨 ArXiv 서버 응답 지연(Timeout) 또는 접속 오류가 발생했습니다. 잠시 후 다시 시도해 주세요. ({e})")
                    st.session_state.search_results = []

        if st.session_state.get("search_results"):
            st.markdown("### 📊 ArXiv 검색 결과")
            for idx, paper in enumerate(st.session_state.search_results):
                with st.expander(f"📄 {paper['title'][:40]}...", expanded=False):
                    st.caption(f"✍️ {paper['authors']} | 📅 {paper['published']} | 🆔 {paper['id']}")
                    st.write(f"{paper['summary'][:200]}...")
                    
                    btn_analyze = st.button("🧠 AI 심층 분석", key=f"ana_{paper['id']}", use_container_width=True)
                    btn_save = st.button("💾 내 DB에 저장", key=f"save_{paper['id']}", type="primary", use_container_width=True)
                    
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

                    if btn_save:
                        paper_to_save = paper.copy()
                        paper_to_save['analysis_result'] = st.session_state.get(f"result_{paper['id']}", "분석 안됨")
                        save_paper_to_db(st.session_state.username, paper_to_save)
                        st.success("저장 완료!")

    with tab2:
        st.markdown(f"### 🗄️ {st.session_state.username}님의 연구 논문 아카이브")
        saved_papers = get_saved_papers(st.session_state.username)
        if not saved_papers: st.info("저장된 논문이 없습니다.")
        else:
            for p in reversed(saved_papers):
                with st.container():
                    st.markdown(f"#### 📌 {p['title']}")
                    st.caption(f"🆔 {p['id']} | 💾 {p['saved_at']}")
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
                        with c1: st.link_button("📄 PDF 열기", p['pdf_url'], use_container_width=True)
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
