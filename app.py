import streamlit as st
import anthropic
import os

# ── 페이지 설정 ──────────────────────────────────────────────
st.set_page_config(
    page_title="노마 법령 어시스턴트",
    page_icon="⚖️",
    layout="centered"
)

st.title("⚖️ 노마 법령 어시스턴트")
st.caption("상가임대차 · 권리금 · 보증금 · 중개보수 관련 법령·판례를 조회합니다")

# ── 환경변수 ─────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MCP_URL = os.environ.get("LAW_MCP_URL", "https://korean-law-mcp.fly.dev/mcp?oc=noma")

if not ANTHROPIC_API_KEY:
    st.error("환경변수 ANTHROPIC_API_KEY가 설정되지 않았습니다.")
    st.stop()

# ── 시스템 프롬프트 (프로젝트 지침 + 참조 테이블 통합) ───────
SYSTEM_PROMPT = """# 공인중개사 법률 어시스턴트
공인중개사 업무 중 발생하는 분쟁 상황에 대해 법령·판례·해석례를 조회해 실무 정보를 제공한다. 법률 판단 대행이 아닌 조문·판례 기반 정보 제공이 목적이다.

---

## 자연어 처리 규칙
사용자 발화에서 법률 관계(임대인/임차인/매도인/매수인/중개사)와 쟁점 명사 2–4개를 추출해 API query로 변환한다.

| 사용자 표현 | 추출 키워드 예시 |
|---|---|
| "계약금 돌려줘야 하나요?" | 계약금 반환 해약 |
| "권리금 못 받게 막았어요" | 권리금 회수 방해 상가임대차 |
| "전세금 못 돌려받아요" | 보증금 반환 임대차 |
| "수수료 너무 많이 받았어요" | 중개보수 한도 초과 |
| "허위매물로 신고당했어요" | 허위광고 중개사 행정처분 |
| "임대인이 나가라고 해요" | 계약갱신 거절 명도 |
| "묵시적 갱신 됐나요?" | 묵시적 갱신 임대차 |
| "하자 숨겼어요" | 하자담보책임 고지의무 |

---

## API 선택 기준
- 법령명이 특정됨 → search_law("법령명") → get_law_text(mst, jo)
- 복합 법률 질문(일반) → chain_full_research(query="핵심키워드")
- "어떻게 해야 해요?" 절차·기한 질문 → chain_full_research(query="핵심키워드", scenario="action_plan")
- 소송·행정심판 준비 → chain_dispute_prep(query="분쟁키워드")
- 행정처분 근거·처분기준 확인 → chain_action_basis(query="처분유형+키워드")

참조 파일(법령_판례_참조테이블.md)에서 관련 법령명·조문번호를 확인한 뒤 query에 반영한다.

---

## 판례 조회 규칙 (필수)
모든 질문에 대해 반드시 관련 판례를 조회하고 응답에 포함한다.

### 판례 조회 순서
1. 위 API로 법령·해석례 조회와 동시에 search_decisions(domain="precedent", query="쟁점키워드")를 실행한다.
2. 결과 중 쟁점과 가장 관련성 높은 판례 1~3건을 선택한다.
3. 필요 시 get_decision_text(domain="precedent", id="...")로 판시 요지 전문을 추가 조회한다.

### 판례 제시 형식
📌 관련 판례
[대법원 / 하급심] 사건번호 (선고일)
판시 요지: (2~3줄 요약)
→ 이 사안과의 관련성: (현재 질문에 어떻게 적용되는지 1줄)

판례가 없거나 조회 결과가 쟁점과 무관한 경우에만 "관련 판례를 찾지 못했습니다"로 명시한다.

---

## 응답 구조 (순서 준수)
1. 쟁점 요약 — 사용자 상황을 한 줄로 정리
2. 관련 조문 — 핵심 조문 요지 요약
3. 관련 판례 — 위 판례 조회 규칙에 따라 반드시 제시
4. 실무 안내 — 즉각 행동(기한·내용증명 등)이 있으면 우선 안내
5. 면책 고지
   위 내용은 법령·판례 데이터베이스 기반 참고 정보입니다. 구체적 판단은 변호사·법무사 등 전문가와 상담하시기 바랍니다.

단정적 법률 판단·소송 전략 제공은 금지한다.
"""

# ── 채팅 기록 초기화 ──────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

# ── 채팅 기록 표시 ────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── 초기 안내 메시지 ──────────────────────────────────────────
if not st.session_state.messages:
    with st.chat_message("assistant"):
        st.markdown("""안녕하세요! 노마 법령 어시스턴트입니다. 😊

궁금한 내용을 편하게 물어보세요:

- 권리금 회수를 방해받았는데 어떻게 해야 하나요?
- 보증금을 못 받았을 때 대응 순서가 어떻게 되나요?
- 상가 계약갱신요구권 기간이 어떻게 되나요?
- 중개보수를 초과해서 받으면 어떤 처벌을 받나요?
- 허위매물로 신고당했을 때 대응 방법이 있나요?""")

# ── 입력 처리 ─────────────────────────────────────────────────
if prompt := st.chat_input("법령·판례 관련 질문을 입력하세요..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("법령·판례 조회 중..."):
            try:
                client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

                response = client.beta.messages.create(
                    model="claude-sonnet-4-5",
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    messages=[
                        {"role": m["role"], "content": m["content"]}
                        for m in st.session_state.messages
                    ],
                    mcp_servers=[
                        {
                            "type": "url",
                            "url": MCP_URL,
                            "name": "korean-law"
                        }
                    ],
                    betas=["mcp-client-2025-04-04"]
                )

                # 텍스트 응답 추출 (tool_use 블록 제외)
                answer = ""
                for block in response.content:
                    if hasattr(block, "type") and block.type == "text":
                        answer += block.text

                if not answer:
                    answer = "응답을 받지 못했습니다. 다시 시도해 주세요."

                st.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})

            except anthropic.APIStatusError as e:
                st.error(f"API 오류 ({e.status_code}): {e.message}")
            except Exception as e:
                st.error(f"오류가 발생했습니다: {str(e)}")

# ── 사이드바: 자주 묻는 질문 ──────────────────────────────────
with st.sidebar:
    st.subheader("💡 자주 묻는 질문")
    quick_questions = [
        "권리금 회수 방해 손해배상 청구 방법",
        "상가 계약갱신요구권 10년 적용 기준",
        "보증금 반환 임차권등기명령 절차",
        "중개보수 한도 초과 시 처벌 기준",
        "허위매물 광고 행정처분 기준",
        "묵시적 갱신 성립 요건",
        "매도인 하자담보책임 범위",
        "계약금 해약 기준",
    ]
    for q in quick_questions:
        if st.button(q, use_container_width=True, key=q):
            st.session_state.messages.append({"role": "user", "content": q})
            st.rerun()

    st.divider()
    if st.session_state.messages:
        if st.button("🗑️ 대화 초기화", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
