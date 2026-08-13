import streamlit as st
import requests

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
        "분석할 ArXiv ID, 논문 URL, 또는 논문 제목을 입력하세요:",
        value="2310.06825",
        placeholder="예: 2310.06825 또는 https://arxiv.org/abs/2310.06825"
    )

with col2:
    st.write("") # 간격 맞춤용
    st.write("")
    btn_analyze = st.button("🚀 심층 분석 실행", use_container_width=True)

# GCP Cloud Run 백엔드 엔드포인트 주소
CLOUD_RUN_URL = "https://parse-arxiv-pdf-810432145390.asia-northeast3.run.app"

if btn_analyze and search_query:
    with st.spinner("🔍 V5.0 Gemini 1.5 Pro 멀티모달 비전 엔진이 논문 전체(표, 그래프, 수식, GitHub 코드)를 분석 중입니다..."):
        try:
            # GCP Cloud Run Function 백엔드 API 호출
            payload = {"pdf_url": search_query}
            response = requests.post(CLOUD_RUN_URL, json=payload, timeout=120)
            
            if response.status_code == 200:
                result_data = response.json()
                extracted_text = result_data.get("extracted_text", "분석 결과를 가져오지 못했습니다.")
                
                st.success("✅ V5.0 멀티모달 정밀 분석이 성공적으로 완료되었습니다!")
                
                # 분석 결과 출력 (마크다운 지원)
                st.markdown("### 📊 V5.0 심층 분석 리포트")
                st.markdown(extracted_text)
                
            else:
                st.error(f"❌ 분석 중 백엔드 에러가 발생했습니다 (코드: {response.status_code}): {response.text}")
                
        except Exception as e:
            st.error(f"❌ 연결 에러 발생: {str(e)}")

# 하단 가이드 팁
st.markdown("---")
st.info("💡 **TIP**: 제주대 초전도체응용연구실 및 최신 AI 논문 분석 시 `2310.06825` (Mistral 7B) 또는 `1706.03762` (Transformer)를 입력하여 V5.0 3단계 수식 해설과 GitHub 매핑 성능을 시험해 보세요!")
