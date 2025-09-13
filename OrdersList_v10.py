import streamlit as st
import requests
import pandas as pd
from collections import defaultdict

# ==============================
# Conexão Salesforce
# ==============================
def connect_salesforce():
    login_url = "https://login.salesforce.com/services/oauth2/token"
    data = {
        "grant_type": "password",
        "client_id": st.secrets["salesforce"]["CLIENT_ID"],
        "client_secret": st.secrets["salesforce"]["CLIENT_SECRET"],
        "username": st.secrets["salesforce"]["USERNAME"],
        "password": st.secrets["salesforce"]["PASSWORD"]
    }
    resp = requests.post(login_url, data=data)
    resp.raise_for_status()
    return resp.json()

def query_salesforce(query, token, instance_url):
    url = f"{instance_url}/services/data/v58.0/query/"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, params={"q": query})
    resp.raise_for_status()
    return resp.json()

def update_salesforce(record_id, token, instance_url):
    url = f"{instance_url}/services/data/v58.0/sobjects/snps_um__SalesOrderDetail__c/{record_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resp = requests.patch(url, headers=headers, json={"AITC_Shipping_Prep_Complete__c": True})
    return resp.status_code == 204

# ==============================
# Estilo CSS
# ==============================
st.markdown("""
<style>
/* Compactar linhas */
table, th, td {
  padding: 3px 6px !important;
  font-size: 13px !important;
}

/* Estilo das linhas completas */
tr.completo td {
  background-color: #121212 !important;
  color: #ff80ab !important;
  font-weight: bold;
}
</style>
""", unsafe_allow_html=True)

# ==============================
# Título
# ==============================
st.title("出荷計画")

# ==============================
# Filtros
# ==============================
with st.form("filtro_datas"):
    data_inicio = st.date_input("開始日")
    data_fim = st.date_input("終了日")
    mostrar_todos = st.checkbox("すべて表示", value=False)
    buscar = st.form_submit_button("検索")

if buscar:
    auth = connect_salesforce()
    token = auth["access_token"]
    instance_url = auth["instance_url"]

    filtro_status = "" if mostrar_todos else "AND AITC_Shipping_Prep_Complete__c = False"

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

    results = query_salesforce(query, token, instance_url)
    st.session_state["dados"] = results["records"]
    st.session_state["token"] = token
    st.session_state["instance_url"] = instance_url
    st.session_state["mostrar_todos"] = mostrar_todos

# ==============================
# Mostrar resultados
# ==============================
if "dados" in st.session_state:
    dados = st.session_state["dados"]
    mostrar_todos = st.session_state["mostrar_todos"]

    grupos = defaultdict(list)
    for r in dados:
        grupos[r["snps_um__ShipPlanDate__c"]].append(r)

    for data, registros in grupos.items():
        st.markdown(f"### 📅 {data}")
        df_display = []

        for r in registros:
            completo = r.get("AITC_Shipping_Prep_Complete__c", False)
            row_style = "completo" if (completo and mostrar_todos) else ""

            cols = st.columns([1, 2, 2, 2, 1, 2, 2, 1])
            with cols[0]:
                if not completo:
                    if st.button("✅ 完了", key=r["Id"]):
                        ok = update_salesforce(r["Id"], st.session_state["token"], st.session_state["instance_url"])
                        if ok:
                            r["AITC_Shipping_Prep_Complete__c"] = True
                            if not mostrar_todos:
                                # Remove da lista
                                st.session_state["dados"] = [x for x in st.session_state["dados"] if x["Id"] != r["Id"]]
                            st.experimental_rerun()
                else:
                    st.write("✔️")

            cols[1].write(r["snps_um__SalesOrder__r"]["Name"])
            cols[2].write(r["snps_um__Note__c"])
            cols[3].write(r["snps_um__Item__r"]["Name"])
            cols[4].write(int(r["snps_um__Quantity__c"]))
            cols[5].write(r["snps_um__SalesOrder__r"]["snps_um__BillCust__r"]["Name"])
            cols[6].write(r["snps_um__DeliveryPeriod__c"])
