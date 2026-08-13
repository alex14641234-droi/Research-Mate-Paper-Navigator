import streamlit as st
import requests
import xml.etree.ElementTree as ET

# 페이지 기본 설정 및 디자인
st.set_page_config(
    page_title="Research Mate & Paper Navigator V5.0",
    page_icon="🔬",
    layout="wide"
)

# 메인 타이틀 및 소개
st.title("🔬 Research Mate & Paper Navigator V5.0")
st.caption("ArXiv 연동, 3단계 수식 정밀 해설(Math Dissector), GitHub 코드 매핑 및 R&D 지능형 분석 플랫폼")

st.markdown("---")

# 검색 및 입력 세션
col1, col2 = st.columns([3, 1])

with col1:
    search_query = st.text_input(
        "분석할 ArXiv ID, 논문 URL, 또는 키워드(예: 초전도체, Mistral 7B)를 입력하세요:",
        value="2310.06825",
        placeholder="예: 초전도체, 2310.06825, 또는 https://arxiv.org/abs/2310.06825"
    )

with col2:
    st.write("") # 간격 맞춤용
    st.write("")
    btn_analyze = st.button("🚀 심층 분석 실행", use_container_width=True)

# GCP Cloud Run 백엔드 엔드포인트 주소
CLOUD_RUN_URL = "https://parse-arxiv-pdf-810432145390.asia-northeast3.run.app"

def resolve_pdf_url(query):
    """
    입력값이 일반 키워드(예: '초전도체')인 경우 ArXiv API로 최신 논문 PDF URL을 자동 추출하고,
    ArXiv ID나 URL인 경우 정상 PDF URL로 변환합니다.
    """
    query = query.strip()
    
    # 1. 이미 URL이거나 ArXiv ID 형태인 경우
    if query.startswith("http://") or query.startswith("https://"):
        if "arxiv.org/abs/" in query:
            return query.replace("arxiv.org/abs/", "arxiv.org/pdf/") + ".pdf"
        return query
    
    # 2. ArXiv ID 형태인 경우 (예: 2310.06825 또는 1706.03762)
    if any(c.isdigit() for c in query) and "." in query and len(query) < 15:
        clean_id = query.replace("arXiv:", "").strip()
        return f"https://arxiv.org/pdf/{clean_id}.pdf"
    
    # 3. 일반 단어/키워드인 경우 (예: '초전도체', 'HTS Coil') -> ArXiv API 검색
    try:
        arxiv_api_url = f"https://export.arxiv.org/api/query?search_query=all:{query}&start=0&max_results=1"
        res = requests.get(arxiv_api_url, timeout=10)
        root = ET.fromstring(res.text)
        
        # XML에서 pdf url 추출
        for entry in root.findall('{http://www.w3.org/2005/Atom}entry'):
            for link in entry.findall('{http://www.w3.org/2005/Atom}link'):
                if link.attrib.get('title') == 'pdf':
                    return link.attrib.get('href') + ".pdf"
                
        # 기본 fallback
        return "https://arxiv.org/pdf/2310.06825.pdf"
    except Exception:
        return f"https://arxiv.org/pdf/{query}.pdf"

if btn_analyze and search_query:
    with st.spinner("🔍 키워드 검색 및 V5.0 Gemini 1.5 Pro 멀티모달 비전 엔진으로 논문을 정밀 분석 중입니다..."):
        try:
            # 1. 입력값을 올바른 PDF URL로 변환
            target_pdf_url = resolve_pdf_url(search_query)
            st.info(f"📄 분석 대상 논문 PDF: `{target_pdf_url}`")
            
            # 2. GCP Cloud Run 백엔드 API 호출
            payload = {"pdf_url": target_pdf_url}
            response = requests.post(CLOUD_RUN_URL, json=payload, timeout=120)
            
            if response.status_code == 200:
                result_data = response.json()
                extracted_text = result_data.get("extracted_text", "분석 결과를 가져오지 못했습니다.")
                
                st.success("✅ V5.0 멀티모달 정밀 분석이 성공적으로 완료되었습니다!")
                
                # 분석 결과 출력 (마크다운 지원)
                st.markdown("### 📊 V5.0 심층 분석 리포트")
                st.markdown(extracted_text)
                
            else:
                st.error(f"❌ 백엔드 분석 실패 (코드: {response.status_code}): {response.text}")
                
        except Exception as e:
            st.error(f"❌ 연결 에러 발생: {str(e)}")

# 하단 가이드 팁
st.markdown("---")
st.info("💡 **TIP**: `초전도체`, `HTS Coil`, `Mistral 7B`, 또는 `2310.06825` 등 단어나 ID 아무거나 입력해보세요!")
