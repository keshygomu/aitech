import streamlit as st
import requests
import datetime
import html

# ========================
# 🔑 Conexão Salesforce
# ========================
def connect_salesforce():
    auth_url = st.secrets["salesforce"]["DOMAIN"] + "/services/oauth2/token"
    data = {
        "grant_type": "password",
        "client_id": st.secrets["salesforce"]["CLIENT_ID"],
        "client_secret": st.secrets["salesforce"]["CLIENT_SECRET"],
        "username": st.secrets["salesforce"]["USERNAME"],
        "password": st.secrets["salesforce"]["PASSWORD"],
    }
    resp = requests.post(auth_url, data=data)
    resp.raise_for_status()
    return resp.json()

def query_salesforce(token, instance_url, soql):
    url = f"{instance_url}/services/data/v57.0/query"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, params={"q": soql})
    resp.raise_for_status()
    return resp.json()["records"]

def update_salesforce(token, instance_url, record_id):
    url = f"{instance_url}/services/data/v57.0/sobjects/snps_um__SalesOrderDetail__c/{record_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    data = {"AITC_Shipping_Prep_Complete__c": True}
    resp = requests.patch(url, headers=headers, json=data)
    return resp.status_code == 204

# ========================
# ⚙️ Configuração página
# ========================
st.set_page_config(page_title="出荷計画リスト", layout="wide")

st.title("📦 出荷計画リスト")

# ========================
# 📅 Filtros
# ========================
col1, col2, col3 = st.columns([1,1,1])
with col1:
    data_inicio = st.date_input("開始日", datetime.date.today())
with col2:
    data_fim = st.date_input("終了日", datetime.date.today())
with col3:
    mostrar_todos = st.checkbox("すべて表示", value=False)

if st.button("検索"):
    try:
        auth = connect_salesforce()
        token = auth["access_token"]
        instance_url = auth["instance_url"]

        filtro_status = ""
        if not mostrar_todos:
            filtro_status = "AND AITC_Shipping_Prep_Complete__c = False"

        soql = f"""
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

        dados = query_salesforce(token, instance_url, soql)

        # ========================
        # 🎨 Estilo CSS
        # ========================
        st.markdown("""
        <style>
        table {
            border-collapse: collapse;
            width: 100%;
            margin: 10px 0;
            font-size: 14px;
        }
        th, td {
            border: 1px solid #444;
            padding: 4px 8px;
            text-align: left;
        }
        td.right {
            text-align: right;
        }
        tr.completo {
            background-color: #000000;
            color: #ff80ab;
            font-weight: bold;
        }
        </style>
        """, unsafe_allow_html=True)

        # ========================
        # 📝 Monta tabela HTML
        # ========================
        rows = []
        for r in dados:
            completo = r.get("AITC_Shipping_Prep_Complete__c", False)
            row_class = "completo" if completo else ""
            checkmark = "✔️" if completo else "⬜"

            rows.append(
                f"<tr class='{row_class}'>"
                f"<td>{checkmark}</td>"
                f"<td>{html.escape(r['snps_um__SalesOrder__r']['Name'])}</td>"
                f"<td>{html.escape(r.get('snps_um__Note__c',''))}</td>"
                f"<td>{html.escape(r['snps_um__Item__r']['Name'])}</td>"
                f"<td class='right'>{int(r['snps_um__Quantity__c'])}</td>"
                f"<td>{html.escape(r['snps_um__SalesOrder__r']['snps_um__BillCust__r']['Name'])}</td>"
                f"<td>{html.escape(r['snps_um__DeliveryPeriod__c'])}</td>"
                "</tr>"
            )

        html_table = (
            "<table>"
            "<thead><tr>"
            "<th>完了</th><th>受注番号</th><th>備考</th><th>品目</th><th>数量</th><th>顧客</th><th>納期</th>"
            "</tr></thead>"
            "<tbody>"
            + "".join(rows) +
            "</tbody></table>"
        )

        st.markdown(html_table, unsafe_allow_html=True)

    except Exception as e:
        st.error(f"⚠️ Erro: {e}")
