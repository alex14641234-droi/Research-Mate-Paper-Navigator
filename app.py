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

# 🧠 한국어/자연어 ➔ ArXiv 영문 학술 키워드 스마트 변환 엔진
def parse_smart_query(user_query):
    q = user_query.strip().lower()
    
    # 1. ArXiv ID 형태인 경우 (예: 2310.06825)
    if re.search(r'\d{4}\.\d{4,5}', q):
        match = re.search(r'\d{4}\.\d{4,5}', q)
        return f"id:{match.group(0)}"

    # 2. 한국어 의미 기반 영문 학술 키워드 맵핑
    if "초전도" in q or "superconduct" in q:
        return 'all:"superconductivity" OR all:"HTS coil"'
    elif "트랜스포머" in q or "transformer" in q:
        return 'all:"transformer" AND all:"attention"'
    elif any(word in q for word in
