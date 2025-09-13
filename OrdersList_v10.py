import streamlit as st
import requests
import datetime
import html
from collections import defaultdict

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

def update_salesforce(token, instance_url, record_id, value: bool):
    url = f"{instance_url}/services/data/v57.0/sobjects/snps_um__SalesOrderDetail__c/{record_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    data = {"AITC_Shipping_Prep_Complete__c": value}
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

# ========================
# 🔎 Executar consulta
# ========================
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
        .completo {
            background-color: #000000 !important;
            color: #ff80ab !important;
            font-weight: bold;
        }
        .right {
            text-align: right;
        }
        .stCheckbox {
            transform: scale(1.2);
        }
        </style>
        """, unsafe_allow_html=True)

        # ========================
        # 📊 Agrupar por data
        # ========================
        grupos = defaultdict(list)
        for r in dados:
            data = r.get("snps_um__ShipPlanDate__c")
            grupos[data].append(r)

        # ========================
        # 📝 Renderizar tabelas
        # ========================
        for data, registros in sorted(grupos.items()):
            st.markdown(f"<h3 style='color:#ff9100;'>{html.escape(data)}</h3>", unsafe_allow_html=True)

            for r in registros:
                record_id = r["Id"]
                completo = r.get("AITC_Shipping_Prep_Complete__c", False)

                # Colunas da linha
                cols = st.columns([1,2,2,2,1,2,2])
                with cols[0]:
                    novo_status = st.checkbox("完了", value=completo, key=f"chk_{record_id}")
                with cols[1]:
                    st.write(r['snps_um__SalesOrder__r']['Name'])
                with cols[2]:
                    st.write(r.get('snps_um__Note__c',''))
                with cols[3]:
                    st.write(r['snps_um__Item__r']['Name'])
                with cols[4]:
                    st.write(int(r['snps_um__Quantity__c']))
                with cols[5]:
                    st.write(r['snps_um__SalesOrder__r']['snps_um__BillCust__r']['Name'])
                with cols[6]:
                    st.write(r['snps_um__DeliveryPeriod__c'])

                # Se o usuário mudar o estado do checkbox
                if novo_status != completo:
                    st.warning("⚠️ 確認: この注文を更新しますか？")
                    c1, c2 = st.columns([1,1])
                    with c1:
                        if st.button("はい", key=f"yes_{record_id}"):
                            sucesso = update_salesforce(token, instance_url, record_id, novo_status)
                            if sucesso:
                                st.success("✅ 更新しました")
                                st.rerun()
                            else:
                                st.error("❌ 更新失敗しました")
                    with c2:
                        if st.button("いいえ", key=f"no_{record_id}"):
                            st.session_state[f"chk_{record_id}"] = completo
                            st.info("キャンセルしました")

    except Exception as e:
        st.error(f"⚠️ エラー: {e}")
