import streamlit as st
import requests
import xml.etree.ElementTree as ET
import re
import urllib.parse
import json
import os
from datetime import datetime

st.set_page_config(page_title="Research Mate V5.0", page_icon="🔬", layout="wide")

st.title("🔬 Research Mate & Paper Navigator V5.0")
st.caption("맞춤형 심층 분석, 3단계 수식 해설, 그리고 나만의 연구 DB 아카이빙 플랫폼")
st.markdown("---")

CLOUD_RUN_URL = "https://parse-arxiv-pdf-810432145390.asia-northeast3.run.app"
DB_FILE = "my_lab_db.json"

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_to_db(paper_info):
    db = load_db()
    if not any(p['id'] == paper_info['id'] for p in db):
        paper_info['saved_at'] = datetime.now().strftime("%Y-%m-%d %H:%M")
        db.append(paper_info)
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=4)
        return True
    return False

# 🌐 구글 무료 번역 API를 활용한 영->한 자동 번역 함수
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
            
            # ✨ 제목과 초록을 실시간으로 한국어로 번역합니다!
            ko_title = translate_to_ko(title)
            ko_summary = translate_to_ko(summary)
            
            papers.append({
                "id": entry.find('{http://www.w3.org/2005/Atom}id').text.split('/')[-1],
                "title": ko_title,          # 번역된 제목 화면 표시
                "en_title": title,          # 원본 제목 (참고용)
                "authors": ", ".join([a.find('{http://www.w3.org/2005/Atom}name').text for a in entry.findall('{http://www.w3.org/2005/Atom}author')][:3]),
                "published": entry.find('{http://www.w3.org/2005/Atom}published').text[:10],
                "summary": ko_summary,      # 번역된 초록 화면 표시
                "pdf_url": f"https://arxiv.org/pdf/{entry.find('{http://www.w3.org/2005/Atom}id').text.split('/')[-1]}.pdf"
            })
        return papers
    except Exception as e:
        return []

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
        submit_button = st.form_submit_button("🚀 AI 스마트 검색", use_container_width=True)

    if submit_button and search_input:
        # 번역 때문에 시간이 살짝 더 걸리므로 안내 멘트 추가
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
                with c2: btn_analyze = st.button("👁️ 맞춤형 심층 분석 실행", key=f"ana_{paper['id']}", use_container_width=True)
                with c3: btn_save = st.button("💾 내 DB에 저장", key=f"save_{paper['id']}", type="primary", use_container_width=True)
                
                if btn_save:
                    if save_to_db(paper): st.success("✅ [내 연구 DB]에 저장되었습니다! 상단 탭에서 확인하세요.")
                    else: st.warning("이미 DB에 저장된 논문입니다.")

                if btn_analyze:
                    with st.spinner(f"⚡ 요구사항을 반영하여 논문을 정밀 분석 중입니다..."):
                        try:
                            payload = {"pdf_url": paper['pdf_url'], "custom_context": custom_context}
                            response = requests.post(CLOUD_RUN_URL, json=payload, timeout=120)
                            if response.status_code == 200:
                                st.success("✅ V5.0 맞춤형 심층 분석 완료!")
                                st.markdown(response.json().get("extracted_text", ""))
                            else:
                                st.error(f"백엔드 에러: {response.text}")
                        except Exception as e:
                            st.error(f"연결 에러: {str(e)}")

with tab2:
    st.markdown("### 🗄️ 내가 아카이빙한 연구 논문 모음")
    saved_papers = load_db()
    
    if not saved_papers:
        st.info("아직 저장된 논문이 없습니다. 탐색 탭에서 '💾 내 DB에 저장' 버튼을 눌러보세요!")
    else:
        for p in reversed(saved_papers):
            st.markdown(f"#### 📌 {p['title']}")
            st.caption(f"🆔 arXiv:{p['id']} | 💾 저장일시: {p['saved_at']}")
            st.link_button("📄 PDF 다시 보기", p['pdf_url'])
            st.markdown("---")
