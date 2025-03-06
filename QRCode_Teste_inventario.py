import streamlit as st
from streamlit_qrcode_scanner import qrcode_scanner
import firebase_admin
from firebase_admin import credentials, db
import pandas as pd
import requests
import os
from simple_salesforce import Salesforce
from datetime import datetime
import re
import time

# Função para carregar credenciais
def carregar_credenciais():
    if os.path.exists('.streamlit/secrets.toml'):
        import toml
        secrets = toml.load('.streamlit/secrets.toml')
    else:
        secrets = st.secrets
    return secrets

# Carregar as credenciais
secrets = carregar_credenciais()

# Inicializar o Firebase usando as credenciais do secrets
if not firebase_admin._apps:
    if "firebase" in secrets:
        firebase_secrets = dict(secrets["firebase"])
        # Verificar se todas as chaves obrigatórias estão presentes
        required_keys = [
            "type", "project_id", "private_key_id", "private_key",
            "client_email", "client_id", "auth_uri", "token_uri",
            "auth_provider_x509_cert_url", "client_x509_cert_url"
        ]
        missing_keys = [key for key in required_keys if key not in firebase_secrets or not firebase_secrets[key]]
        if missing_keys:
            st.error(f"Chaves obrigatórias ausentes em firebase_secrets: {missing_keys}")
            st.stop()

        # Garantir que private_key tenha quebras de linha reais, apenas se necessário
        if isinstance(firebase_secrets["private_key"], str) and "\\n" in firebase_secrets["private_key"]:
            firebase_secrets["private_key"] = firebase_secrets["private_key"].replace("\\n", "\n")
        elif not isinstance(firebase_secrets["private_key"], str):
            st.error("A chave 'private_key' não é uma string válida!")
            st.stop()

        cred = credentials.Certificate(firebase_secrets)
        firebase_admin.initialize_app(cred, {
            "databaseURL": "https://uminventory-4a2a8-default-rtdb.asia-southeast1.firebasedatabase.app/"
        })
    else:
        st.error("A chave 'firebase' não foi encontrada em secrets!")
        st.stop()

# Função de autenticação do Salesforce usando as credenciais do secrets
def authenticate_salesforce():
    auth_url = f"{secrets['DOMAIN']}/services/oauth2/token"
    auth_data = {
        'grant_type': 'password',
        'client_id': secrets['CONSUMER_KEY'],
        'client_secret': secrets['CONSUMER_SECRET'],
        'username': secrets['USERNAME'],
        'password': secrets['PASSWORD']
    }
    try:
        response = requests.post(auth_url, data=auth_data, timeout=10)
        response.raise_for_status()
        token_data = response.json()
        access_token = token_data['access_token']
        instance_url = token_data['instance_url']
        return Salesforce(instance_url=instance_url, session_id=access_token)
    except requests.exceptions.RequestException as e:
        st.error(f"認証エラー: {e}")
        st.stop()

# Função para consultar Salesforce
def consultar_salesforce(production_order, sf):
    query = f"""
        SELECT Id, Name, snps_um__ProcessName__c, snps_um__ActualQt__c, snps_um__Item__r.Id, 
               snps_um__Item__r.Name, snps_um__ProcessOrderNo__c, snps_um__ProdOrder__r.Id, 
               snps_um__ProdOrder__r.Name, snps_um__Status__c, snps_um__WorkPlace__r.Id, 
               snps_um__WorkPlace__r.Name, snps_um__StockPlace__r.Name, snps_um__Item__c, 
               snps_um__Process__r.AITC_Acumulated_Price__c, AITC_OrderQt__c, snps_um__EndDateTime__c 
        FROM snps_um__WorkOrder__c 
        WHERE snps_um__ProdOrder__r.Name = '{production_order}'
    """
    try:
        result = sf.query(query)
        records = result['records']
        if not records:
            return pd.DataFrame(), None, None, 0.0

        df = pd.DataFrame(records)
        st.session_state.all_data = df.to_dict(orient="records")
        
        df_done = df[df['snps_um__Status__c'] == 'Done']
        if not df_done.empty:
            last_record = df_done.loc[df_done['snps_um__ProcessOrderNo__c'].idxmax()].to_dict()
            cumulative_cost = last_record.get("snps_um__Process__r", {}).get("AITC_Acumulated_Price__c", 0.0)
            if cumulative_cost is None:
                cumulative_cost = 0.0

            father_id = last_record['snps_um__Item__c']
            composition_query = f"""
                SELECT 
                snps_um__ChildItem__r.Name,
                snps_um__AddQt__c
                FROM snps_um__Composition2__c
                WHERE snps_um__ParentItem2__c = '{father_id}'
            """
            composition_result = sf.query(composition_query)
            composition_records = composition_result['records']
            if composition_records:
                material = composition_records[0].get("snps_um__ChildItem__r", {}).get("Name", "N/A")
                material_weight = composition_records[0].get("snps_um__AddQt__c", 0.0)
            else:
                material = "N/A"
                material_weight = 0.0
            return pd.DataFrame([last_record]), material, material_weight, cumulative_cost
        return pd.DataFrame(), None, None, 0.0
    except Exception as e:
        st.error(f"Salesforceクエリエラー: {e}")
        return pd.DataFrame(), None, None, 0.0

# Função para limpar quantidade e converter para float
def clean_quantity(value):
    if isinstance(value, str):
        num = re.sub(r'[^\d.]', '', value)
        return float(num) if num else 0.0
    return float(value) if value else 0.0

# Função para preparar DataFrame simplificado
def simplify_dataframe(df):
    if df.empty:
        return df
    relevant_columns = [
        'snps_um__ProcessName__c',
        'snps_um__ProcessOrderNo__c',
        'snps_um__Status__c',
        'snps_um__WorkPlace__r.Name',
        'snps_um__ActualQt__c',
        'AITC_OrderQt__c'
    ]
    simplified_df = pd.DataFrame()
    for col in relevant_columns:
        if col in df.columns:
            if col == 'snps_um__WorkPlace__r.Name':
                simplified_df[col] = df[col].apply(lambda x: x.get('Name', '') if isinstance(x, dict) else '' if x is None else str(x))
            elif col in ['snps_um__ActualQt__c', 'AITC_OrderQt__c']:
                simplified_df[col] = df[col].apply(clean_quantity)
            else:
                simplified_df[col] = df[col]
    return simplified_df

# Função para verificar se o registro já existe no Firebase
def check_existing_record_with_date(production_order, date_str, data_to_save):
    ref = db.reference("inventory")
    records = ref.order_by_child("production_order").equal_to(production_order).get()
    if records:
        for key, value in records.items():
            record_date = value.get("datetime", "").split()[0]
            if record_date == date_str:
                if (value.get("quantity") == data_to_save["quantity"] and
                    value.get("owner") == data_to_save["owner"] and
                    value.get("product_code") == data_to_save["product_code"] and
                    value.get("process_name") == data_to_save["process_name"] and
                    value.get("process_order") == data_to_save["process_order"] and
                    value.get("work_place") == data_to_save["work_place"] and
                    value.get("cumulative_cost") == data_to_save["cumulative_cost"] and
                    value.get("material") == data_to_save["material"] and
                    value.get("material_provision_type") == data_to_save["material_provision_type"] and
                    value.get("material_weight") == data_to_save["material_weight"]):
                    return True, key
    return False, None

# Função para verificar se o registro já existe para update
def check_for_update(production_order, date_str):
    ref = db.reference("inventory")
    records = ref.order_by_child("production_order").equal_to(production_order).get()
    if records:
        for key, value in records.items():
            record_date = value.get("datetime", "").split()[0]
            if record_date == date_str:
                return True, key
    return False, None

# Função para gravar no Firebase
def gravar_firebase(data):
    ref = db.reference("inventory")
    new_record = ref.push(data)
    return new_record.key

# Função para atualizar registro no Firebase
def update_firebase(record_id, data):
    ref = db.reference(f"inventory/{record_id}")
    ref.update(data)
    return record_id

# Função para verificar o último registro no Firebase
def verify_last_record(record_id):
    ref = db.reference("inventory")
    return ref.child(record_id).get()

# Interface Streamlit
st.image("aitech_logo_b.png", use_container_width=True)

# Autenticar no Salesforce
if "sf" not in st.session_state:
    try:
        st.session_state.sf = authenticate_salesforce()
        st.success("Salesforceに正常に接続しました！")
    except Exception as e:
        st.error(f"認証エラー: {e}")
        st.stop()

# Inicializar estados necessários
if "production_order" not in st.session_state:
    st.session_state.production_order = None
if "show_camera" not in st.session_state:
    st.session_state.show_camera = True
if "data" not in st.session_state:
    st.session_state.data = None
if "owner" not in st.session_state:
    st.session_state.owner = ""
if "quantity" not in st.session_state:
    st.session_state.quantity = 0.0
if "process_order" not in st.session_state:
    st.session_state.process_order = 0
if "material" not in st.session_state:
    st.session_state.material = None
if "material_weight" not in st.session_state:
    st.session_state.material_weight = None
if "cumulative_cost" not in st.session_state:
    st.session_state.cumulative_cost = 0.0
if "manual_input_value" not in st.session_state:
    st.session_state.manual_input_value = ""

# Opção de digitação manual do production_order
manual_input = st.text_input("生産オーダー番号を入力してください (6桁、例: 000000):",
                            value=st.session_state.manual_input_value,
                            max_chars=6,
                            key="manual_input")
if manual_input and len(manual_input) == 6 and manual_input.isdigit():
    st.session_state.production_order = f"PO-{manual_input.zfill(6)}"
    st.session_state.manual_input_value = manual_input
    st.session_state.show_camera = False

# Exibir câmera e botão de reexibição
if st.session_state.show_camera:
    st.write("QRコードをスキャンして開始してください:")
    production_order = qrcode_scanner(key="qrcode_scanner_" + str(datetime.now().timestamp()))
    if production_order:
        st.session_state.production_order = production_order
        st.session_state.manual_input_value = ""
        st.session_state.show_camera = False

# Botão de reexibição sempre visível
if st.button("カメラを再表示"):
    st.session_state.show_camera = True
    st.session_state.production_order = None
    st.session_state.manual_input_value = ""
    st.rerun()

# Formulário sempre renderizado
with st.form(key="registro_form"):
    default_quantity = 0.0
    default_process_order = 0
    if st.session_state.production_order is not None:
        df, material, material_weight, cumulative_cost = consultar_salesforce(st.session_state.production_order, st.session_state.sf)
        if "all_data" in st.session_state and st.session_state.all_data:
            st.write("Salesforceで発見されたすべての記録:")
            simplified_df = simplify_dataframe(pd.DataFrame(st.session_state.all_data))
            st.dataframe(simplified_df)
        if not df.empty:
            st.session_state.data = df.to_dict(orient="records")
            st.session_state.material = material
            st.session_state.material_weight = material_weight
            st.session_state.cumulative_cost = cumulative_cost
            last_record = st.session_state.data[0]
            default_quantity = clean_quantity(last_record.get("snps_um__ActualQt__c") or last_record.get("AITC_OrderQt__c") or 0.0)
            default_process_order = int(last_record.get("snps_um__ProcessOrderNo__c", 0))
        else:
            st.session_state.data = None
            st.session_state.material = None
            st.session_state.material_weight = None
            st.session_state.cumulative_cost = 0.0
            st.warning("生産オーダーに該当する 'Done' ステータスの記録が見つかりませんでした。")

    # Campos de entrada
    owner_value = "" if st.session_state.data is None else st.session_state.owner
    owner = st.text_input("所有者 (工程):", key="owner", value=owner_value)
    if st.session_state.data:
        quantity = st.number_input("数量 (工程):", value=default_quantity, key="quantity")
        process_order = st.number_input("工程順序:", value=default_process_order, step=1, key="process_order")
    else:
        quantity = st.number_input("数量 (工程):", value=0.0, key="quantity", disabled=True)
        process_order = st.number_input("工程順序:", value=0, key="process_order", disabled=True)

    # Botão de submissão
    submit_button = st.form_submit_button("Firebaseに保存")

    # Lógica de gravação
    if submit_button and st.session_state.data is not None:
        owner_input = st.session_state.get("owner", "").strip()
        if not owner_input:
            st.error("'所有者' フィールドを入力してください。")
        else:
            quantity_value = st.session_state["quantity"]
            process_order_value = int(st.session_state["process_order"])
            record = st.session_state.data[0]
            datetime_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            date_only = datetime.now().strftime("%Y-%m-%d")

            work_place = record.get("snps_um__WorkPlace__r", {}).get("Name", "")

            data_to_save = {
                "datetime": datetime_str,
                "production_order": st.session_state.production_order,
                "quantity": quantity_value,
                "owner": owner_input,
                "product_code": record.get("snps_um__Item__r", {}).get("Name", "N/A"),
                "process_name": record.get("snps_um__ProcessName__c", ""),
                "process_order": process_order_value,
                "work_place": work_place,
                "cumulative_cost": st.session_state.cumulative_cost,
                "material": st.session_state.material if st.session_state.material is not None else "N/A",
                "material_provision_type": "Manual",
                "material_weight": st.session_state.material_weight if st.session_state.material_weight is not None else 0.0
            }

            exists, existing_key = check_existing_record_with_date(st.session_state.production_order, date_only, data_to_save)
            if exists:
                st.warning("この記録は既に存在します。")
                # Limpar todos os campos mesmo em caso de registro existente
                st.session_state.production_order = None
                st.session_state.manual_input_value = ""
                st.session_state.data = None
                st.session_state.all_data = None
                st.session_state.material = None
                st.session_state.material_weight = None
                st.session_state.cumulative_cost = 0.0
                st.session_state.show_camera = True
                st.rerun()
            else:
                update_exists, update_key = check_for_update(st.session_state.production_order, date_only)
                if update_exists:
                    update_firebase(update_key, data_to_save)
                    st.success("更新が成功しました。")
                else:
                    record_id = gravar_firebase(data_to_save)
                    st.success(f"ID {record_id} の記録が保存されました")
                time.sleep(2)
                verified_record = verify_last_record(record_id if not update_exists else update_key)
                if verified_record:
                    st.write(f"確認: ID {record_id if not update_exists else update_key} の記録がFirebaseに正常に保存されました。")
                else:
                    st.error(f"エラー: ID {record_id if not update_exists else update_key} の記録の確認に失敗しました。")
                
                # Limpar todos os campos após gravação ou atualização
                st.session_state.production_order = None
                st.session_state.manual_input_value = ""
                st.session_state.data = None
                st.session_state.all_data = None
                st.session_state.material = None
                st.session_state.material_weight = None
                st.session_state.cumulative_cost = 0.0
                st.session_state.show_camera = True
                st.rerun()

if not st.session_state.production_order:
    st.warning("QRコードをスキャンするか、生産オーダー番号を入力して開始してください。")

st.markdown("**指示:** QRコードを生産オーダー番号でスキャンするか、6桁の生産オーダー番号を入力してください (例: 000000)。'Done' ステータスの最新の記録に対して '所有者' を入力し、必要に応じて '数量' と '工程順序' を調整してください。'所有者' を入力した後、'保存' をクリックしてください。")

