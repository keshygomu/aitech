import streamlit as st
import requests
import datetime

# ==================================================
# Função para conectar ao Salesforce
# ==================================================
def connect_salesforce():
    auth_url = st.secrets["salesforce"]["DOMAIN"] + "/services/oauth2/token"
    data = {
        "grant_type": "password",
        "client_id": st.secrets["salesforce"]["CLIENT_ID"],
        "client_secret": st.secrets["salesforce"]["CLIENT_SECRET"],
        "username": st.secrets["salesforce"]["USERNAME"],
        "password": st.secrets["salesforce"]["PASSWORD"],
    }
    res = requests.post(auth_url, data=data)
    res.raise_for_status()
    return res.json()

# ==================================================
# Função para rodar query SOQL
# ==================================================
def run_query(token, instance_url, soql):
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(instance_url + "/services/data/v58.0/query",
                       headers=headers, params={"q": soql})
    res.raise_for_status()
    return res.json()["records"]

# ==================================================
# Função para atualizar status no Salesforce
# ==================================================
def atualizar_status_salesforce(record_id, status):
    try:
        access_token = st.session_state.sf_token
        instance_url = st.session_state.sf_instance
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        url = f"{instance_url}/services/data/v58.0/sobjects/snps_um__SalesOrderDetail__c/{record_id}"
        res = requests.patch(url, headers=headers, json={"AITC_Shipping_Prep_Complete__c": status})
        return res.status_code == 204
    except Exception as e:
        st.error(f"Erro ao atualizar registro {record_id}: {e}")
        return False

# ==================================================
# CSS customizado
# ==================================================
st.markdown("""
<style>
.completo {
    background-color: #000000 !important;
    color: #ff80ab !important;
    font-weight: bold;
    padding: 0.2rem 0;
}
div[data-testid="stCheckbox"] {
    display: flex;
    align-items: center;
    margin-top: 0px;
    margin-bottom: 0px;
}
</style>
""", unsafe_allow_html=True)

# ==================================================
# Título
# ==================================================
st.markdown("## 📦 出荷計画リスト")

# ==================================================
# Formulário de filtro
# ==================================================
col1, col2, col3 = st.columns([1,1,1])
with col1:
    data_inicio = st.date_input("開始日", datetime.date.today())
with col2:
    data_fim = st.date_input("終了日", datetime.date.today())
with col3:
    mostrar_todos = st.checkbox("すべて表示", value=False)

if st.button("検索"):
    # autentica se necessário
    if "sf_token" not in st.session_state:
        auth = connect_salesforce()
        st.session_state.sf_token = auth["access_token"]
        st.session_state.sf_instance = auth["instance_url"]

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

    dados = run_query(st.session_state.sf_token, st.session_state.sf_instance, query)
    st.session_state["dados"] = dados

# ==================================================
# Exibir resultados agrupados
# ==================================================
if "dados" in st.session_state and st.session_state["dados"]:
    # agrupa por data
    grupos = {}
    for r in st.session_state["dados"]:
        data = r.get("snps_um__ShipPlanDate__c")
        if data not in grupos:
            grupos[data] = []
        grupos[data].append(r)

    for data in sorted(grupos.keys()):
        st.markdown(f"### <span style='color:orange'>{data}</span>", unsafe_allow_html=True)

        for r in grupos[data]:
            container = st.container()
            if r["AITC_Shipping_Prep_Complete__c"]:
                container.markdown("<div class='completo'>", unsafe_allow_html=True)
            else:
                container.markdown("<div>", unsafe_allow_html=True)

            with container:
                cols = st.columns([1,2,2,2,1,2,2])
                marcado = cols[0].checkbox(" ", value=r["AITC_Shipping_Prep_Complete__c"], key=r["Id"])
                if marcado != r["AITC_Shipping_Prep_Complete__c"]:
                    sucesso = atualizar_status_salesforce(r["Id"], marcado)
                    if sucesso:
                        r["AITC_Shipping_Prep_Complete__c"] = marcado
                        st.rerun()

                cols[1].write(r["snps_um__SalesOrder__r"]["Name"])
                cols[2].write(r["snps_um__Note__c"])
                cols[3].write(r["snps_um__Item__r"]["Name"])
                cols[4].markdown(f"<div style='text-align:right; font-size:1.1rem;'>{int(r['snps_um__Quantity__c'])}</div>", unsafe_allow_html=True)
                cols[5].write(r["snps_um__SalesOrder__r"]["snps_um__BillCust__r"]["Name"])
                cols[6].write(r["snps_um__DeliveryPeriod__c"])

            container.markdown("</div>", unsafe_allow_html=True)
