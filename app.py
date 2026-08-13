import streamlit as st
import requests
import xml.etree.ElementTree as ET
import re
import urllib.parse
import json
import os
from datetime import datetime
import hashlib
import google.generativeai as genai

st.set_page_config(page_title="Research Mate V6.0", page_icon="🧠", layout="wide")

USERS_DB_FILE = "users_db.json"
PAPERS_DB_FILE = "my_lab_db.json"

# --- 💾 데이터베이스 & 인증 로직 ---
def load_json(filepath):
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def signup(username, password):
    users = load_json(USERS_DB_FILE)
    if username in users:
        return False
    users[username] = hash_password(password)
    save_json(USERS_DB_FILE, users)
    return True

def login(username, password):
    users = load_json(USERS_DB_FILE)
    if username in users and users[username] == hash_password(password):
        return True
    return False

def save_paper_to_db(username, paper_info):
    db = load_json(PAPERS_DB_FILE)
    if username not in db:
        db[username] = []
    
    if any(p['id'] == paper_info['id'] for p in db[username]):
        return False
        
    paper_info['saved_at'] = datetime.now().strftime("%Y-%m-%d %H:%M")
    db[username].append(paper_info)
    save_json(PAPERS_DB_FILE, db)
    return True

def delete_paper_from_db(username, paper_id):
    db = load_json(PAPERS_DB_FILE)
    if username in db:
        db[username] = [p for p in db[username] if p['id'] != paper_id]
        save_json(PAPERS_DB_FILE, db)
        return True
    return False

def get_saved_papers(username):
    db = load_json(PAPERS_DB_FILE)
    return db.get(username, [])

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
        clean = re.sub(r'[^\w\s]', '', q)
        for word in ["추천해줘", "찾아줘", "대해", "요즘", "핫한", "알려줘", "이슈가", "되는", "최신", "논문"]:
            clean = clean.replace(word, "")
        final_query = 'all:"deep learning"' if re.search(r'[가-힣]', clean) or not clean.strip() else f'all:"{clean.strip()}"'

    return urllib.parse.quote(final_query), "스마트 맞춤 키워드 변환 완료"

def search_arxiv_papers(user_query, max_results=4):
    arxiv_query, _ = parse_smart_query(user_query)
    try:
        url = f"https://export.arxiv.org/api/query?search_query={arxiv_query}&start=0&max_results={max_results}&sortBy=relevance&sortOrder=descending"
        res = requests.get(url, timeout=10)
        root = ET.fromstring(res.text)
        papers = []
        for entry in root.findall('{http://www.w3.org/2005/Atom}entry'):
            title = entry.find('{http://www.w3.org/2005/Atom}title').text.replace('\n', ' ').strip()
            summary = entry.find('{http://www.w3.org/2005/Atom}summary').text.replace('\n', ' ').strip()
            
            ko_title = translate_to_ko(title)
            ko_summary = translate_to_ko(summary)
            
            papers.append({
                "id": entry.find('{http://www.w3.org/2005/Atom}id').text.split('/')[-1],
                "title": ko_title,
                "en_title": title,
                "authors": ", ".join([a.find('{http://www.w3.org/2005/Atom}name').text for a in entry.findall('{http://www.w3.org/2005/Atom}author')][:3]),
                "published": entry.find('{http://www.w3.org/2005/Atom}published').text[:10],
                "summary": ko_summary,
                "pdf_url": f"https://arxiv.org/pdf/{entry.find('{http://www.w3.org/2005/Atom}id').text.split('/')[-1]}.pdf"
            })
        return papers
    except Exception as e:
        return []

# --- 🤖 에러 없는 All-in-one 로컬 AI 호출 로직 ---
def analyze_paper_with_gemini(api_key, pdf_url, custom_context):
    try:
        genai.configure(api_key=api_key)
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(pdf_url, headers=headers, timeout=20)
        response.raise_for_status()
        
        model = genai.GenerativeModel("gemini-1.5-pro")
        
        context_prompt = f"\n\n[사용자의 현재 연구 상황 및 특별 요구사항]:\n{custom_context}\n(위 요구사항을 최우선적으로 반영하여 분석 리포트를 작성해 주십시오.)" if custom_context else ""
        prompt = """
        당신은 세계 최고 수준의 시각 및 텍스트 융합 논문 분석 전문가입니다.
        첨부된 PDF 논문을 바탕으로 다음 3가지를 마크다운으로 완벽히 정리해 주십시오:
        1. **공식 코드(GitHub) 주소**: 논문 내 오픈소스 링크 발췌.
        2. **수식 및 표 추출**: 핵심 수식을 LaTeX 표기법($...$)으로 발췌하고, 변수를 표로 분해하여 설명.
        3. **그래프 시각적 분석**: 주요 아키텍처나 그래프 추세 설명.
        """ + context_prompt

        response = model.generate_content([
            {"mime_type": "application/pdf", "data": response.content},
            prompt
        ], generation_config={"max_output_tokens": 8192, "temperature": 0.2})
        
        return response.text
    except Exception as e:
        return f"에러 발생: {str(e)}"

# --- 💻 메인 앱 & UI ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = ""

if not st.session_state.logged_in:
    st.title("🔐 Research Mate 로그인")
    st.caption("나만의 논문 DB와 AI 분석을 위해 로그인하거나 회원가입하세요.")
    
    tab_login, tab_signup = st.tabs(["🔑 로그인", "📝 회원가입"])
    
    with tab_login:
        login_id = st.text_input("아이디 (ID)", key="login_id")
        login_pw = st.text_input("비밀번호 (Password)", type="password", key="login_pw")
        if st.button("로그인", use_container_width=True):
            if login(login_id, login_pw):
                st.session_state.logged_in = True
                st.session_state.username = login_id
                st.rerun()
            else:
                st.error("아이디 또는 비밀번호가 올바르지 않습니다.")
                
    with tab_signup:
        signup_id = st.text_input("새 아이디 (ID)", key="signup_id")
        signup_pw = st.text_input("새 비밀번호 (Password)", type="password", key="signup_pw")
        if st.button("회원가입", use_container_width=True):
            if signup_id.strip() == "" or signup_pw.strip() == "":
                st.warning("아이디와 비밀번호를 입력해주세요.")
            elif signup(signup_id, signup_pw):
                st.success("회원가입 성공! 이제 로그인 탭에서 로그인해주세요.")
            else:
                st.error("이미 존재하는 아이디입니다.")

else:
    with st.sidebar:
        st.markdown(f"### 👤 {st.session_state.username}님 환영합니다!")
        if st.button("로그아웃"):
            st.session_state.logged_in = False
            st.session_state.username = ""
            st.rerun()
            
        st.markdown("---")
        st.markdown("### 🔑 Google AI Studio 설정")
        st.markdown("구글에서 [무료 API 키 발급받기](https://aistudio.google.com/app/apikey)")
        api_key = st.text_input("Gemini API Key를 입력하세요", type="password")
        if api_key:
            st.success("API 키 입력 완료! (분석 기능 활성화 됨)")

    st.title("🧠 Research Mate V6.0")
    st.caption("AI 기반 맞춤형 심층 분석 및 개인 연구 아카이빙 플랫폼")
    st.markdown("---")
    
    tab1, tab2 = st.tabs(["🔍 논문 탐색 및 맞춤 분석", "🗄️ 내 연구 DB (My Library)"])

    with tab1:
        with st.form(key="search_form"):
            search_input = st.text_input("🔍 검색어, 연구 주제를 입력하세요 (예: 자율주행 최신 논문 추천해줘)")
            st.markdown("---")
            st.markdown("**💡 맞춤형 분석 요구사항 (선택사항)**")
            custom_context = st.text_area(
                "현재 연구 상황이나 특별히 알고 싶은 내용을 적어주세요.", 
                placeholder="예: 저는 인공지능 연구를 시작하는 초보자입니다. 이 논문의 핵심 알고리즘이 기존 모델들과 어떻게 다른지 비유를 들어 쉽게 설명해주세요."
            )
            submit_button = st.form_submit_button("🚀 스마트 논문 검색", use_container_width=True)

        if submit_button and search_input:
            with st.spinner("최상위 관련 논문을 찾고, 한국어로 번역하고 있습니다... (약 2~3초 소요)"):
                st.session_state.search_results = search_arxiv_papers(search_input)

        if st.session_state.get("search_results"):
            st.markdown("### 📄 발견된 최상위 논문 (한국어 자동 번역 🇰🇷)")
            for idx, paper in enumerate(st.session_state.search_results):
                with st.expander(f"[{idx+1}] {paper['title']} (클릭하여 열기)", expanded=True):
                    st.caption(f"✍️ 저자: {paper['authors']} | 📅 {paper['published']} | 🆔 {paper['id']}")
                    st.markdown(f"**원제(English)**: *{paper['en_title']}*")
                    st.write(f"**초록 요약**: {paper['summary'][:350]}...")
                    
                    c1, c2, c3 = st.columns([2, 3, 2])
                    with c1: st.link_button("📄 영문 원본 보기", paper['pdf_url'], use_container_width=True)
                    
                    with c2: btn_analyze = st.button("🧠 맞춤형 AI 심층 분석", key=f"ana_{paper['id']}", use_container_width=True)
                    with c3: btn_save = st.button("💾 내 DB에 저장", key=f"save_{paper['id']}", type="primary", use_container_width=True)
                    
                    if btn_save:
                        if save_paper_to_db(st.session_state.username, paper): 
                            st.success("✅ [내 연구 DB]에 저장되었습니다!")
                        else: 
                            st.warning("이미 DB에 저장된 논문입니다.")

                    if btn_analyze:
                        if not api_key:
                            st.error("⚠️ 에러: 화면 좌측(사이드바)에 Gemini API 키를 먼저 입력해주세요!")
                        else:
                            with st.spinner(f"⚡ 요구사항을 반영하여 논문을 정밀 분석 중입니다... (최대 30초 소요)"):
                                result_text = analyze_paper_with_gemini(api_key, paper['pdf_url'], custom_context)
                                if "에러 발생" in result_text:
                                    st.error(result_text)
                                else:
                                    st.success("✨ 맞춤형 심층 분석 완료!")
                                    st.markdown(result_text)

    with tab2:
        st.markdown(f"### 🗄️ {st.session_state.username}님의 연구 논문 아카이브")
        saved_papers = get_saved_papers(st.session_state.username)
        
        if not saved_papers:
            st.info("아직 저장된 논문이 없습니다. 탐색 탭에서 '💾 내 DB에 저장' 버튼을 눌러보세요!")
        else:
            for p in reversed(saved_papers):
                with st.container():
                    st.markdown(f"#### 📌 {p['title']}")
                    st.caption(f"🆔 arXiv:{p['id']} | 💾 저장일시: {p['saved_at']}")
                    
                    col1, col2 = st.columns([8, 2])
                    with col1:
                        st.link_button("📄 PDF 원문 열기", p['pdf_url'])
                    with col2:
                        if st.button("🗑️ 삭제하기", key=f"del_{p['id']}", type="secondary", use_container_width=True):
                            delete_paper_from_db(st.session_state.username, p['id'])
                            st.rerun() # 삭제 후 즉시 화면 새로고침
                st.markdown("---")
