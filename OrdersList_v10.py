import streamlit as st

st.title("HTML render test")

html = (
    "<table>"
    "<thead><tr><th>完了</th><th>受注番号</th></tr></thead>"
    "<tbody>"
    "<tr><td>✔️</td><td>1001-250904</td></tr>"
    "<tr><td>✔️</td><td>1001-250905</td></tr>"
    "</tbody>"
    "</table>"
)

st.markdown(html, unsafe_allow_html=True)
