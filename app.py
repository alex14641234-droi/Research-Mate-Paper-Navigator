import functions_framework
import json
import requests
import vertexai
from vertexai.generative_models import GenerativeModel, Part

# 현재 프로젝트 정보 (GCP 프로젝트 ID 및 리전)
PROJECT_ID = "iceu-674"
LOCATION = "asia-northeast3"

@functions_framework.http
def parse_arxiv_pdf(request):
    """
    ArXiv PDF URL을 받아 Gemini 1.5 AI를 통해
    텍스트, 표(Table), 그래프(Figure), 공식 깃허브(GitHub) 코드 주소까지
    통합 시각적 정밀 분석을 수행하는 V5.0 파서입니다.
    """
    # 1. 요청 파라미터 파싱
    request_json = request.get_json(silent=True)
    if not request_json:
        return (json.dumps({"error": "No JSON data provided. 'pdf_url' is required."}), 400, {'Content-Type': 'application/json'})
        
    pdf_url = request_json.get("pdf_url", "").strip()
    if not pdf_url:
        return (json.dumps({"error": "'pdf_url' is required"}), 400, {'Content-Type': 'application/json'})

    # ArXiv 논문 URL 정제 (abs 주소가 들어올 경우 pdf 주소로 자동 변환)
    if "arxiv.org/abs/" in pdf_url:
        pdf_url = pdf_url.replace("arxiv.org/abs/", "arxiv.org/pdf/")
    if not pdf_url.endswith(".pdf"):
        pdf_url += ".pdf"

    try:
        # 2. PDF 파일 다운로드
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(pdf_url, headers=headers, timeout=20)
        response.raise_for_status()
        
        pdf_data = response.content
        
        # 3. Vertex AI (Gemini 1.5 Pro) 초기화 및 정확한 모델 버전 지정
        vertexai.init(project=PROJECT_ID, location=LOCATION)
        
        # 404 에러 해결: 정확한 세부 모델 ID인 "gemini-1.5-pro-001" 지정
        model = GenerativeModel("gemini-1.5-pro-001")
        
        # PDF 데이터를 AI가 직접 볼 수 있는 Part 객체로 변환
        pdf_part = Part.from_data(data=pdf_data, mime_type="application/pdf")
        
        # 4. 시각적 분석(Vision) 및 V5.0 코드/수식 추출 프롬프트 설정
        prompt = """
        당신은 세계 최고 수준의 시각 및 텍스트 융합 논문 분석 전문가입니다.
        첨부된 PDF 논문 원문을 처음부터 끝까지 자세히 읽고 핵심 내용을 추출해 주십시오.
        
        특별히 다음 3가지 핵심 요소를 완벽하게 분석하여 텍스트로 정리해 주십시오:
        1. **공식 코드(GitHub) 주소 발췌**: 논문 내(주로 1페이지 Footnote, Introduction, 또는 Code Availability 섹션)에 기재된 공식 깃허브 Repository 주소(예: https://github.com/...)나 오픈소스 구현체 링크를 반드시 찾아내어 상단에 마크다운 링크로 강조해 주십시오. 만약 논문 내에 코드 링크가 없다면 '공식 코드 링크 미기재'로 명시하십시오.
        2. **표(Table) 및 수식(Equations) 정밀 추출**: 중요한 성능 비교 표의 수치와, 논문의 핵심 수식을 LaTeX 표기법($...$)으로 원문 그대로 발췌해 주십시오.
        3. **그래프(Figure) 시각적 분석**: 그래프의 축 정보, 데이터 추세, 아키텍처 다이어그램의 생김새를 시각적으로 직접 보고 자세히 설명해 주십시오.
        
        결과는 마크다운(Markdown) 형식으로 깔끔하게 정리하여 반환해 주십시오.
        """
        
        # 5. AI에게 분석 요청 및 응답 대기
        responses = model.generate_content(
            [pdf_part, prompt],
            generation_config={
                "max_output_tokens": 8192,
                "temperature": 0.1,
            }
        )
        
        final_text = responses.text
        
        return (json.dumps({
            "status": "success",
            "extracted_text": final_text,
            "note": "🚀 V5.0 Gemini 1.5 Pro-001 멀티모달 파싱 완료 (GitHub 코드 매핑, 표, 수식, 그래프 시각 분석 포함)"
        }), 200, {'Content-Type': 'application/json'})

    except Exception as e:
        return (json.dumps({"error": f"V5.0 멀티모달 파싱 중 에러 발생: {str(e)}"}), 500, {'Content-Type': 'application/json'})
