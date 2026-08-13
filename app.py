import streamlit as st
import requests
import xml.etree.ElementTree as ET

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

# 1. 검색 영역 UI
col1, col2 = st.columns([4, 1])

with col1:
    search_input = st.text_input(
        "검색어, 연구 주제, 또는 ArXiv ID를 입력하세요:",
        value="초전도체",
        placeholder="예: 초전도체, ai 관련 논문 추천해줘, 2310.06825, HTS Coil"
    )

with col2:
    st.write("") # 버튼 높이 맞춤용
    st.write("")
    btn_search = st.button("🔍 검색", use_container_width=True)

# ArXiv API 검색 함수
def search_arxiv_papers(query, max_results=4):
    clean_query = query.strip()
    
    # 한국어 자연어 검색어 대응 정제
    search_term = clean_query
    for stop_word in ["추천해줘", "관련", "논문", "찾아줘", "대해"]:
        search_term = search_term.replace(stop_word, "").strip()
    if not search_term:
        search_term = "artificial intelligence"
    if search_term == "초전도체":
        search_term = "superconductivity"

    try:
        url = f"https://export.arxiv.org/api/query?search_query=all:{search_term}&start=0&max_results={max_results}"
        res = requests.get(url, timeout=10)
        root = ET.fromstring(res.text)
        
        papers = []
        for entry in root.findall('{http://www.w3.org/2005/Atom}entry'):
            title = entry.find('{http://www.w3.org/2005/Atom}title').text.replace('\n', ' ').strip()
            summary = entry.find('{http://www.w3.org/2005/Atom}summary').text.replace('\n', ' ').strip()
            published = entry.find('{http://www.w3.org/2005/Atom}published').text[:10]
            
            # 저자
            authors = [a.find('{http://www.w3.org/2005/Atom}name').text for a in entry.findall('{http://www.w3.org/2005/Atom}author')]
            author_str = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
            
            # ID 및 PDF 링크
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
        return papers
    except Exception as e:
        return []

# 세션 상태 초기화 (검색 결과 및 분석 결과 유지)
if "search_results" not in st.session_state:
    st.session_state.search_results = []

# 검색 버튼 클릭 시
if btn_search and search_input:
    with st.spinner(f"🔍 ArXiv에서 '{search_input}' 관련 최신 논문을 찾는 중..."):
        st.session_state.search_results = search_arxiv_papers(search_input)

# 2. 검색 결과 목록 출력
if st.session_state.search_results:
    st.markdown(f"### 📄 검색된 추천 논문 목록 ({len(st.session_state.search_results)}건)")
    
    for idx, paper in enumerate(st.session_state.search_results):
        with st.container():
            st.markdown(f"#### {idx+1}. {paper['title']}")
            st.caption(f"✍️ 저자: {paper['authors']} | 📅 발행일: {paper['published']} | 🆔 arXiv:{paper['id']}")
            st.write(f"**초록 (Abstract)**: {paper['summary'][:250]}...")
            
            c1, c2, c3 = st.columns([2, 2, 4])
            with c1:
                st.link_button("📄 PDF 원문 보기", paper['pdf_url'], use_container_width=True)
            with c2:
                btn_analyze_item = st.button(f"👁️ V5.0 멀티모달 심층 분석", key=f"btn_analyze_{paper['id']}", use_container_width=True)
            
            st.markdown("---")
            
            # 특정 논문의 심층 분석 버튼을 눌렀을 때
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

elif btn_search:
    st.warning("관련 논문을 찾지 못했습니다. 다른 검색어로 시도해 보세요.")
