# -*- coding: utf-8 -*-
import requests
import streamlit as st
from datetime import date
import textwrap
from html import escape

# =========================================
# Conectar ao Salesforce
# =========================================
def connect_salesforce():
    url = f"{st.secrets['salesforce']['DOMAIN']}/services/oauth2/token"
    data = {
        "grant_type": "password",
        "client_id": st.secrets["salesforce"]["CLIENT_ID"],
        "client_secret": st.secrets["salesforce"]["CLIENT_SECRET"],
        "username": st.secrets["salesforce"]["USERNAME"],
        "password": st.secrets["salesforce"]["PASSWORD"],
    }
    resp = requests.post(url, data=data)
    resp.raise_for_status()
    return resp.json()["access_token"], resp.json()["instance_url"]

# =========================================
# Query Salesforce
# =========================================
def query_salesforce(token, instance_url, data_inicio, data_fim, mostrar_todos):
    filtro_status = ""
    if not mostrar_todos:
        filtro_status = "AND AITC_Shipping_Prep_Complete__c = False"

    query = f"""
        SELECT Id,
               snps_um__ShipPlanDate__c,
               snps_um__SalesOrder__r.Name,
               snps_um__Note__c,
               snps_um__Item__r.Name,
               snps_um__Quantity__c,
               snps_um__SalesOrder__r.snps_um__BillCust__r.Name,
               snps_um__DeliveryPeriod__c,
               AITC_Shipping_Prep_Complete__c
        FROM snps_um__SalesOrderDetail__c
        WHERE snps_um__SalesOrderRemainCloseFlg__c = False
          AND snps_um__ShipPlanDate__c >= {data_inicio}
          AND snps_um__ShipPlanDate__c <= {data_fim}
          {filtro_status}
        ORDER BY snps_um__ShipPlanDate__c, snps_um__Note__c
    """

    url = f"{instance_url}/services/data/v57.0/query"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, params={"q": query})
    resp.raise_for_status()
    return resp.json()["records"]

# =========================================
# Atualizar status no Salesforce
# =========================================
def update_salesforce(record_id, token, instance_url):
    url = f"{instance_url}/services/data/v57.0/sobjects/snps_um__SalesOrderDetail__c/{record_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    data = {"AITC_Shipping_Prep_Complete__c": True}
    resp = requests.patch(url, headers=headers, json=data)
    return resp.status_code == 204

# =========================================
# Estilo CSS
# =========================================
st.markdown("""
<style>
body {
  background-color: #121212;
  color: #e0e0e0;
}
table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 20px;
}
th, td {
  padding: 4px 8px !important;
  font-size: 13px !important;
  text-align: left;
  border-bottom: 1px solid #333;
}
tr:hover td {
  background-color: #1e1e1e;
}
tr.completo td {
  background-color: #121212 !important;
  color: #ff80ab !important;
  font-weight: bold;
}
th {
  background-color: #2c2c2c;
  color: #00e5ff;
}
input[type=submit] {
  background-color: #00e676;
  border: none;
  border-radius: 4px;
  padding: 2px 8px;
  cursor: pointer;
  font-weight: bold;
}
input[type=submit]:hover {
  background-color: #00c853;
}
</style>
""", unsafe_allow_html=True)

# =========================================
# Captura update via query param
# =========================================
params = st.query_params
if "update" in params:
    record_id = params["update"]
    if "token" in st.session_state:
        ok = update_salesforce(record_id, st.session_state["token"], st.session_state["instance_url"])
        if ok:
            # Atualiza estado local
            for rec in st.session_state.get("dados", []):
                if rec["Id"] == record_id:
                    rec["AITC_Shipping_Prep_Complete__c"] = True
            # Se não for mostrar todos, remove da lista
            if not st.session_state.get("mostrar_todos", False):
                st.session_state["dados"] = [x for x in st.session_state["dados"] if x["Id"] != record_id]
        st.rerun()

# =========================================
# App Streamlit
# =========================================
st.title("📦 出荷計画リスト")

if "token" not in st.session_state:
    st.session_state["token"], st.session_state["instance_url"] = connect_salesforce()

with st.form("filtro"):
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        data_inicio = st.date_input("開始日", value=date.today())
    with col2:
        data_fim = st.date_input("終了日", value=date.today())
    with col3:
        mostrar_todos = st.checkbox("すべて表示", value=False)

    buscar = st.form_submit_button("検索")

if buscar:
    dados = query_salesforce(
        st.session_state["token"],
        st.session_state["instance_url"],
        data_inicio,
        data_fim,
        mostrar_todos,
    )
    st.session_state["dados"] = dados
    st.session_state["mostrar_todos"] = mostrar_todos

# =========================================
# Renderizar tabela em HTML
# =========================================
if "dados" in st.session_state:
    dados = st.session_state["dados"]
    mostrar_todos = st.session_state["mostrar_todos"]

    html = textwrap.dedent("""
    <table>
      <thead>
        <tr>
          <th>完了</th>
          <th>受注番号</th>
          <th>備考</th>
          <th>品目</th>
          <th>数量</th>
          <th>顧客</th>
          <th>納期</th>
        </tr>
      </thead>
      <tbody>
    """)

    for r in dados:
        completo = r.get("AITC_Shipping_Prep_Complete__c", False)
        row_class = "completo" if (completo and mostrar_todos) else ""

        if not completo:
            check_html = f"<form method='get'><input type='hidden' name='update' value='{r['Id']}'><input type='submit' value='✅'></form>"
        else:
            check_html = "✔️"

        html += f"""
        <tr class='{row_class}'>
          <td>{check_html}</td>
          <td>{escape(r["snps_um__SalesOrder__r"]["Name"])}</td>
          <td>{escape(r["snps_um__Note__c"] or "")}</td>
          <td>{escape(r["snps_um__Item__r"]["Name"])}</td>
          <td style="text-align:right;">{int(r["snps_um__Quantity__c"])}</td>
          <td>{escape(r["snps_um__SalesOrder__r"]["snps_um__BillCust__r"]["Name"])}</td>
          <td>{escape(r["snps_um__DeliveryPeriod__c"])}</td>
        </tr>
        """

    html += "</tbody></table>"

    st.markdown(html, unsafe_allow_html=True)
