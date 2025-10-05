from typing import Any, Dict, List, Optional
import pandas as pd
import requests
import getpass
import snowflake.connector
import streamlit as st

# ---------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------
DATABASE = "CORTEX_ANALYST_DEMO"
SCHEMA = "SHESAFE"
STAGE = "RAW_DATA"
FILE = "earthquake_model.yaml"
WAREHOUSE = "SHESAFE_WH"

HOST = "WOIVVAJ-BJC38732.snowflakecomputing.com"
ACCOUNT = "WOIVVAJ-BJC38732"
USER = "RB1458"
ROLE = "ACCOUNTADMIN"

# ---------------------------------------------------
# CONNECT TO SNOWFLAKE
# ---------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_snowflake_conn():
    """Create a connection to Snowflake with MFA."""
    return snowflake.connector.connect(
        user=USER,
        password=getpass.getpass("Snowflake password: "),
        account=ACCOUNT,
        warehouse=WAREHOUSE,
        role=ROLE,
        authenticator="snowflake",
        passcode=getpass.getpass("Enter your 6-digit MFA code: "),
    )

if "CONN" not in st.session_state or st.session_state.CONN is None:
    st.session_state.CONN = get_snowflake_conn()

# ---------------------------------------------------
# SEND QUERY TO CORTEX ANALYST API
# ---------------------------------------------------
def send_message(prompt: str) -> Dict[str, Any]:
    """Send user prompt to Snowflake Cortex Analyst."""
    request_body = {
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        "semantic_model_file": f"@{DATABASE}.{SCHEMA}.{STAGE}/{FILE}",
    }

    resp = requests.post(
        url=f"https://{HOST}/api/v2/cortex/analyst/message",
        json=request_body,
        headers={
            "Authorization": f'Snowflake Token="{st.session_state.CONN.rest.token}"',
            "Content-Type": "application/json",
        },
    )

    request_id = resp.headers.get("X-Snowflake-Request-Id")
    if resp.status_code < 400:
        return {**resp.json(), "request_id": request_id}
    else:
        raise Exception(
            f"❌ Failed request (id: {request_id}) — {resp.status_code}: {resp.text}"
        )

# ---------------------------------------------------
# DISPLAY CHAT CONTENT
# ---------------------------------------------------
def display_content(
    content: List[Dict[str, str]],
    request_id: Optional[str] = None,
    message_index: Optional[int] = None,
) -> None:
    """Display response blocks (text, SQL, suggestions)."""
    message_index = message_index or len(st.session_state.messages)
    if request_id:
        with st.expander("Request ID", expanded=False):
            st.markdown(request_id)

    for item in content:
        if item["type"] == "text":
            st.markdown(item["text"])

        elif item["type"] == "suggestions":
            with st.expander("Suggestions", expanded=True):
                for i, suggestion in enumerate(item["suggestions"]):
                    if st.button(suggestion, key=f"{message_index}_{i}"):
                        st.session_state.active_suggestion = suggestion

        elif item["type"] == "sql":
            with st.expander("SQL Query", expanded=False):
                st.code(item["statement"], language="sql")

            with st.expander("Results", expanded=True):
                with st.spinner("Running query..."):
                    df = pd.read_sql(item["statement"], st.session_state.CONN)
                    if not df.empty:
                        tabs = st.tabs(["Data", "Line Chart", "Bar Chart"])
                        tabs[0].dataframe(df)
                        if len(df.columns) > 1:
                            df = df.set_index(df.columns[0])
                            tabs[1].line_chart(df)
                            tabs[2].bar_chart(df)
                    else:
                        st.info("No results found for this query.")

# ---------------------------------------------------
# PROCESS USER INPUT
# ---------------------------------------------------
def process_message(prompt: str):
    """Handle user input and display assistant's response."""
    st.session_state.messages.append(
        {"role": "user", "content": [{"type": "text", "text": prompt}]}
    )

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing rescue data..."):
            response = send_message(prompt)
            request_id = response["request_id"]
            content = response["message"]["content"]
            display_content(content, request_id)

    st.session_state.messages.append(
        {"role": "assistant", "content": content, "request_id": request_id}
    )

# ---------------------------------------------------
# STREAMLIT UI
# ---------------------------------------------------
st.set_page_config(page_title="SheSafe Analyst", page_icon="🆘", layout="wide")
st.title("🆘 SheSafe Analyst – Earthquake Response Chatbot")
st.caption(
    "Ask natural questions like *'Show me the top 5 people needing oxygen'* "
    "or *'Which locations have the most severe incidents?'.*"
)

if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.active_suggestion = None

for i, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        display_content(message["content"], message.get("request_id"), i)

if user_input := st.chat_input("Ask SheSafe Analyst..."):
    process_message(user_input)

if st.session_state.active_suggestion:
    process_message(st.session_state.active_suggestion)
    st.session_state.active_suggestion = None
