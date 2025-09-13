import streamlit as st
import pandas as pd
import requests
from io import BytesIO

# ========================
# FUNÇÕES SALESFORCE
# ========================

def connect_salesforce():
    cfg = st.secrets["salesforce"]
    url = f"{cfg['domain']}/services/oauth2/token"
    params = {
        "grant_type": "password",
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "username": cfg["username"],
        "password": cfg["password"]
    }
    resp = requests.post(url, data=params)
    resp.raise_for_status()
    return resp.json()

def run_query(access_token, instance_url, query):
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"{instance_url}/services/data/v57.0/query/"
    resp = requests.get(url, headers=headers, params={"q": query})
    resp.raise_for_status()
    return resp.json()["records"]

def update_status(access_token, instance_url, record_id):
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    url = f"{instance_url}/services/data/v57.0/sobjects/snps_um__SalesOrderDetail__c/{record_id}"
    data = {"AITC_Shipping_Prep_Complete__c": True}
    resp = requests.patch(url, headers=headers, json=data)
    return resp.status_code == 204

# ========================
# STREAMLIT APP
# ========================
st.set_page_config(page_title="出荷計画", layout="wide")
st.title("📦 出荷計画データ")

# CSS para destacar linhas concluídas
st.markdown("""
<style>
.row-completo {
    background-color: black !important;
    color: #ff80ab !important; /* texto pink */
    font-weight: bold;
}
</style>
""", unsafe_allow_html=True)

# Inputs
col1, col2, col3 = st.columns([1,1,1])
with col1:
    data_inicio = st.date_input("開始日")
with col2:
    data_fim = st.date_input("終了日")
with col3:
    mostrar_todos = st.checkbox("すべて表示")

if st.button("検索"):
    try:
        # Autenticar
        auth = connect_salesforce()
        token = auth["access_token"]
        instance = auth["instance_url"]

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

        registros = run_query(token, instance, query)

        if registros:
            df = pd.json_normalize(registros)

            # Filtro de cliente
            clientes = sorted(df["snps_um__SalesOrder__r.snps_um__BillCust__r.Name"].dropna().unique())
            cliente_sel = st.selectbox("顧客で絞り込み", ["すべて"] + clientes)

            if cliente_sel != "すべて":
                df = df[df["snps_um__SalesOrder__r.snps_um__BillCust__r.Name"] == cliente_sel]

            # Resumo geral
            colA, colB, colC, colD = st.columns(4)
            colA.metric("出荷件数", len(df))
            colB.metric("完了", (df["AITC_Shipping_Prep_Complete__c"]==True).sum())
            colC.metric("待ち", (df["AITC_Shipping_Prep_Complete__c"]==False).sum())
            colD.metric("合計", int(df["snps_um__Quantity__c"].sum()))

            # Gráfico (完了 vs 待ち por dia)
            resumo = df.groupby(["snps_um__ShipPlanDate__c","AITC_Shipping_Prep_Complete__c"]).size().unstack().fillna(0)
            resumo = resumo.rename(columns={True:"完了", False:"待ち"})
            st.bar_chart(resumo)

            st.subheader("📋 明細一覧")

            # Tabela interativa com botões 完了
            for idx, row in df.iterrows():
                # Classe CSS condicional
                row_class = "row-completo" if (row["AITC_Shipping_Prep_Complete__c"] and mostrar_todos) else ""

                st.markdown(f"<div class='{row_class}'>", unsafe_allow_html=True)

                cols = st.columns([1,2,2,2,1,2,2,1])
                with cols[0]:
                    if not row["AITC_Shipping_Prep_Complete__c"]:
                        if st.button("✅ 完了", key=row["Id"]):
                            ok = update_status(token, instance, row["Id"])
                            if ok:
                                st.success(f"{row['snps_um__Note__c']} を完了にしました")
                                if not mostrar_todos:
                                    # Ocultar linha → recarregar
                                    st.experimental_rerun()
                            else:
                                st.error("更新エラー")
                    else:
                        st.write("✔️")

                cols[1].write(str(row.get("snps_um__ShipPlanDate__c","")))
                cols[2].write(str(row.get("snps_um__SalesOrder__r.Name","")))
                cols[3].write(str(row.get("snps_um__Note__c","")))
                cols[4].write(int(row.get("snps_um__Quantity__c",0)))
                cols[5].write(str(row.get("snps_um__SalesOrder__r.snps_um__BillCust__r.Name","")))
                cols[6].write(str(row.get("snps_um__DeliveryPeriod__c","")))
                cols[7].write("完了" if row["AITC_Shipping_Prep_Complete__c"] else "待ち")

                st.markdown("</div>", unsafe_allow_html=True)

            # Exportar Excel
            output = BytesIO()
            df.to_excel(output, index=False, engine="openpyxl")
            st.download_button("📥 Excel ダウンロード",
                               data=output.getvalue(),
                               file_name="shipments.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.warning("データがありません。")

    except Exception as e:
        st.error(f"エラー: {e}")
