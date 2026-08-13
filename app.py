import streamlit as st
import requests
import xml.etree.ElementTree as ET
import re

# 페이지 기본 설정
st.set_page_config(
    page_title="Research Mate & Paper Navigator V5.0",
    page_icon="🔬",
    layout="wide"
)

# 메인 헤더
st.title("🔬 Research Mate & Paper Navigator V5.0")
st.caption("ArXiv 연동, 3단계 수식 정밀 해설(Math Dissector), GitHub 코드 매핑 및 R&D 지능형 분석 플랫폼")

st.markdown("---")

# GCP Cloud Run 백엔드 엔드포인트 주소
CLOUD_RUN_URL = "https://parse-arxiv-pdf-810432145390.asia-northeast3.run.app"

# 🧠 한국어 자연어 ➔ ArXiv 영문 학술 키워드 스마트 번역 에이전트
def parse_smart_query(user_query):
    q = user_query.strip().lower()
    
    # 1. ArXiv ID 형태인 경우 (예: 2310.06825)
    match = re.search(r'\d{4}\.\d{4,5}', q)
    if match:
        return f"id:{match.group(0)}", f"ArXiv ID: {match.group(0)}"

    # 2. 한국어 의미 기반 영문 학술 키워드 맵핑 사전
    keyword_map = {
        "초전도": ('all:"superconductivity" OR all:"HTS"', '초전도 (Superconductivity)'),
        "트랜스포머": ('all:"transformer" AND all:"attention"', '트랜스포머 (Transformer)'),
        "생성형": ('all:"generative model"', '생성형 모델 (Generative Model)'),
        "비전": ('all:"computer vision"', '컴퓨터 비전 (Computer Vision)'),
        "로봇": ('all:"robotics"', '로봇 공학 (Robotics)'),
        "자율주행": ('all:"autonomous driving"', '자율주행 (Autonomous Driving)'),
        "강화학습": ('all:"reinforcement learning"', '강화학습 (Reinforcement Learning)'),
        "양자": ('all:"quantum computing"', '양자 컴퓨팅 (Quantum Computing)'),
        "반도체": ('all:"semiconductor"', '반도체 (Semiconductor)'),
        "배터리": ('all:"battery"', '배터리 (Battery)'),
        "의료": ('all:"medical" OR all:"healthcare"', '의료/헬스케어 (Medical)'),
        "금융": ('all:"finance"', '금융 (Finance)'),
        "이슈": ('all:"large language model" OR all:"deep learning"', '최신 딥러닝 트렌드'),
        "핫한": ('all:"large language model" OR all:"deep learning"', '최신 딥러닝 트렌드'),
        "트렌드": ('all:"state of the art" OR all:"survey"', '최신 기술 동향 (SOTA)')
    }
    
    search_terms = []
    translated_names = []
    
    for ko_word, (en_query, display_name) in keyword_map.items():
        if ko_word in q:
            search_terms.append(f"({en_query})")
            translated_names.append(display_name)
            
    if "ai" in q or "인공지능" in q or "llm" in q or "머신러닝" in q or "딥러닝" in q:
        search_terms.append('(all:"artificial intelligence" OR all:"large language model")')
        translated_names.append("인공지능 (AI & LLM)")
        
    # 매칭된 키워드가 있으면 조합
    if search_terms:
        final_query = " AND ".join(search_terms)
        display_text = " + ".join(translated_names)
    else:
        # 매칭된 키워드가 없으면 불용어 제거 후 영문 번역 시도
        clean = re.sub(r'[^\w\s]', '', q)
        for word in ["추천해줘", "추천", "관련", "논문", "찾아줘", "대해", "보여줘", "원해", "요즘", "핫한", "알려줘", "이슈가", "되는", "최신"]:
            clean = clean.replace(word, "")
        clean = clean.strip()
        
        # 여전히 한글이 남아있다면 가장 핫한 딥러닝 논문으로 기본 유도
        if re.search(r'[가-힣]', clean) or not clean:
            final_query = 'all:"deep learning" OR all:"machine learning"'
            display_text = "딥러닝 기본 추천 (Deep Learning)"
        else:
            final_query = f'all:"{clean}"'
            display_text = f"영문 직접 검색 ({clean})"

    # 이중 인코딩 버그 제거: 순수 쿼리 문자열 그대로 반환
    return final_query, display_text

# ArXiv API 검색 함수
def search_arxiv_papers(user_query, max_results=4):
    arxiv_query, display_text = parse_smart_query(user_query)
    
    try:
        url = "https://export.arxiv.org/api/query"
        # requests.get의 params로 넘기면 URL 인코딩을 가장 안전하게 1번만 알아서 해줍니다!
        params = {
            "search_query": arxiv_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending"
        }
        
        res = requests.get(url, params=params, timeout=10)
        root = ET.fromstring(res.text)
        
        papers = []
        for entry in root.findall('{http://www.w3.org/2005/Atom}entry'):
            title = entry.find('{http://www.w3.org/2005/Atom}title').text.replace('\n', ' ').strip()
            summary = entry.find('{http://www.w3.org/2005/Atom}summary').text.replace('\n', ' ').strip()
            published = entry.find('{http://www.w3.org/2005/Atom}published').text[:10]
            
            authors = [a.find('{http://www.w3.org/2005/Atom}name').text for a in entry.findall('{http://www.w3.org/2005/Atom}author')]
            author_str = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
            
            paper_id = entry.find('{http://www.w3.org/2005/Atom}id').text.split('/')[-1]
            pdf_url = f"https://arxiv.org/pdf/{paper_id}.pdf"
            
            papers.append({
                "id": paper_id,
                "title": title,
                "authors": author_str,
                "published": published,
                "summary": summary,
                "pdf_url": pdf_url
            })
        return papers, display_text
    except Exception as e:
        return [], ""

# 세션 상태 초기화
if "search_results" not in st.session_state:
    st.session_state.search_results = []
if "display_topic" not in st.session_state:
    st.session_state.display_topic = ""

# 폼(Form)을 활용하여 엔터(Enter) 키 제출 구현
with st.form(key="search_form", clear_on_submit=False):
    col1, col2 = st.columns([4, 1])
    with col1:
        search_input = st.text_input(
            "검색어, 연구 주제, 또는 ArXiv ID를 입력하세요 (엔터키로 즉시 검색):",
            value="최신 자율주행 자동차 관련 논문 찾아줘",
            placeholder="예: 최신 자율주행 로봇 논문 찾아줘, 초전도체, 2310.06825"
        )
    with col2:
        st.write("") 
        st.write("")
        submit_button = st.form_submit_button("🔍 관련도순 검색", use_container_width=True)

# 엔터 키나 검색 버튼을 눌렀을 때 실행
if submit_button and search_input:
    with st.spinner(f"🔍 ArXiv에서 '{search_input}' 관련 최상위 논문을 찾고 있습니다..."):
        results, topic = search_arxiv_papers(search_input)
        st.session_state.search_results = results
        st.session_state.display_topic = topic

# 검색 결과 목록 출력
if st.session_state.search_results:
    st.markdown(f"### 📄 💡 AI 추천 관련도 최상위 논문 ({len(st.session_state.search_results)}건)")
    st.success(f"**스마트 번역 에이전트:** 사용자의 질문을 `[ {st.session_state.display_topic} ]` (으)로 분석하여 가장 많이 인용된 학술 논문을 찾아왔습니다! 🤖")
    
    for idx, paper in enumerate(st.session_state.search_results):
        with st.container():
            st.markdown(f"#### {idx+1}. {paper['title']}")
            st.caption(f"✍️ 저자: {paper['authors']} | 📅 발행일: {paper['published']} | 🆔 arXiv:{paper['id']}")
            st.write(f"**초록 (Abstract)**: {paper['summary'][:280]}...")
            
            c1, c2, c3 = st.columns([2, 2, 4])
            with c1:
                st.link_button("📄 PDF 원문 보기", paper['pdf_url'], use_container_width=True)
            with c2:
                btn_analyze_item = st.button(f"👁️ V5.0 멀티모달 심층 분석", key=f"btn_analyze_{paper['id']}", use_container_width=True)
            
            st.markdown("---")
            
            # 심층 분석 버튼 로직
            if btn_analyze_item:
                with st.spinner(f"⚡ '{paper['title']}' 논문의 3단계 수식, GitHub 코드, 시각 다이어그램을 정밀 분석 중입니다..."):
                    try:
                        payload = {"pdf_url": paper['pdf_url']}
                        response = requests.post(CLOUD_RUN_URL, json=payload, timeout=120)
                        
                        if response.status_code == 200:
                            res_json = response.json()
                            extracted_text = res_json.get("extracted_text", "")
                            
                            st.success(f"✅ '{paper['title']}' V5.0 심층 분석 완료!")
                            st.markdown("## 📊 V5.0 R&D 심층 분석 리포트")
                            st.markdown(extracted_text)
                        else:
                            st.error(f"백엔드 분석 실패: {response.text}")
                    except Exception as e:
                        st.error(f"분석 중 연결 에러 발생: {str(e)}")

elif submit_button:
    st.warning("관련 논문을 찾지 못했습니다. 영문 키워드나 구체적인 주제로 다시 시도해 보세요.")
