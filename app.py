Antigravity, the app has a critical UI state bug and a prompt adherence issue. The user's "Custom Analysis Requirements" are being completely ignored during the AI paper analysis, and they are also polluting the ArXiv search queries.

Please fix this by implementing the following 3 architectural changes in `app.py`:

1. Separate Search from Analysis (Fix Keyword Pollution):
In Tab 1, remove `custom_context_search` from `st.form("search_form")`. The form should ONLY contain `search_input`. Do NOT append any custom analysis text to `query_to_search`. The search query must remain purely academic.

2. Move Analysis Input to the Result Cards (Fix Streamlit Form State Bug):
In Tab 1's search results loop (`for idx, paper in enumerate(st.session_state.search_results):`), add a dedicated text input for the custom analysis right above the "🧠 AI 심층 분석" button. 
Example: 
```python
ctx_tab1 = st.text_input("맞춤형 분석 요구사항 (선택)", key=f"ctx_tab1_{paper['id']}")
btn_analyze = st.button("🧠 AI 심층 분석", key=f"ana_{paper['id']}", use_container_width=True)
