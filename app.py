import streamlit as st
import google.generativeai as genai
import requests
import arxiv
from datetime import datetime

# 1. 페이지 기본 설정
st.set_page_config(
    page_title="자가 발전형 논문 분석 플랫폼",
    page_icon="🔬",
    layout="wide"
)

st.title("🔬 Research Mate & Paper Navigator")
st.caption("ArXiv 연동, 수식 정밀 해설(Math Dissector), 학술 족보(Citation Genealogy) 및 Notion DB 아카이빙")

st.markdown("---")

# 2. 사이드바 API 설정
with st.sidebar:
    st.header("⚙️ 시스템 API 설정")
    gemini_api_key = st.text_input("Gemini API Key", type="password", help="Google AI Studio에서 발급받은 API 키")
    notion_api_key = st.text_input("Notion API Key", type="password", help="secret_... 형태의 통합 키")
    notion_db_id = st.text_input("Notion Database ID", value="3bb18c4eb1148015a73afbade4591cb8", help="Notion DB 32자리 ID")
    
    st.markdown("---")
    st.markdown("### 💡 주요 분석 기능")
    st.markdown("- **Math Dissector**: 수식/변수/단위 3단계 정밀 해설")
    st.markdown("- **Citation Genealogy**: 선행/후속 연구 족보 제시")
    st.markdown("- **Notion Archiving**: DB 자동 저장 및 자산화")

# 3. 에이전트 시스템 프롬프트 정의
AGENT_SYSTEM_INSTRUCTION = """
당신은 '자가 발전형 논문 분석 플랫폼'의 전문 연구 총괄 에이전트입니다.
사용자가 제공한 논문 제목, 내용, 또는 ArXiv ID에 대해 다음 지침을 엄격히 따라 분석을 수행하십시오:

1. **Math Dissector (수식 정밀 해설)**:
   - 논문의 주요 핵심 수식을 LaTeX 형식 (...)으로 명확히 표기하십시오.
   - 변수 분해 표를 작성하십시오 (기호 | 한글 명칭 | 물리적/수학적 의미 | 단위).
   - 수식의 직관적 역할 및 시스템 내 의미를 설명하십시오.

2. **Citation Genealogy (논문 인용 족보)**:
   - 해당 연구의 근간이 된 핵심 선행 연구(Prerequisite)를 제시하십시오.
   - 해당 연구를 발전시킨 후속 연구 흐름 및 기술적 파생 관계를 정리하십시오.

3. **Tone & Manner**:
   - 전문적이고 체계적인 연구 조교의 톤을 유지하십시오.
   - 한국어로 작성하십시오.
"""

# 4. 사용자 입력부
col1, col2 = st.columns([3, 1])
with col1:
    user_input = st.text_input("분석할 ArXiv ID, 논문 제목, 또는 연구 주제를 입력하세요:", "1706.03762")
with col2:
    st.write(" ")
    st.write(" ")
    analyze_btn = st.button("🚀 심층 분석 실행", use_container_width=True)

# 5. 분석 로직 실행
if analyze_btn and user_input:
    if not gemini_api_key:
        st.error("사이드바에 Gemini API Key를 입력해 주세요.")
    else:
        try:
            genai.configure(api_key=gemini_api_key)
            model = genai.GenerativeModel(
                model_name="gemini-1.5-pro",
                system_instruction=AGENT_SYSTEM_INSTRUCTION
            )
            
            with st.spinner("ArXiv 데이터 수집 및 에이전트 심층 분석 진행 중..."):
                arxiv_title = user_input
                arxiv_summary = ""
                try:
                    client = arxiv.Client()
                    search = arxiv.Search(query=user_input, max_results=1)
                    results = list(client.results(search))
                    if results:
                        paper = results[0]
                        arxiv_title = paper.title
                        arxiv_summary = paper.summary
                        st.success(f"📄 ArXiv 논문 탐색 성공: **{arxiv_title}**")
                except Exception:
                    pass
                
                prompt = f"다음 논문/주제에 대해 심층 분석(Math Dissector 및 Citation Genealogy 포함)을 수행해 줘:\n제목/주제: {arxiv_title}\n요약: {arxiv_summary}"
                response = model.generate_content(prompt)
                analysis_result = response.text
            
            st.markdown("---")
            st.markdown("## 📊 에이전트 분석 결과")
            st.markdown(analysis_result)
            
            # 6. Notion DB 저장 기능
            if notion_api_key and notion_db_id:
                st.markdown("---")
                if st.button("📥 이 분석 결과를 Notion DB에 영구 저장하기"):
                    headers = {
                        "Authorization": f"Bearer {notion_api_key}",
                        "Content-Type": "application/json",
                        "Notion-Version": "2022-06-08"
                    }
                    payload = {
                        "parent": {"database_id": notion_db_id},
                        "properties": {
                            "제목": {"title": [{"text": {"content": arxiv_title[:100]}}]},
                            "ArXiv ID": {"rich_text": [{"text": {"content": user_input[:50]}}]},
                            "요약 및 수식": {"rich_text": [{"text": {"content": analysis_result[:1900]}}]},
                            "저장일자": {"date": {"start": datetime.now().strftime("%Y-%m-%d")}}
                        }
                    }
                    res = requests.post("https://api.notion.com/v1/pages", headers=headers, json=payload)
                    if res.status_code == 200:
                        st.balloons()
                        st.success("🎉 성공적으로 Notion 데이터베이스에 아카이빙되었습니다!")
                    else:
                        st.error(f"Notion 저장 실패 (상태 코드: {res.status_code}). API Key와 DB ID를 확인하세요.")
            else:
                st.info("💡 사이드바에 Notion API Key와 DB ID를 입력하시면 자동 아카이빙 기능을 사용할 수 있습니다.")

        except Exception as e:
            st.error(f"분석 중 오류가 발생했습니다: {str(e)}")
