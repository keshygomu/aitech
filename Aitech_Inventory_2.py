import streamlit as st
from streamlit_qrcode_scanner import qrcode_scanner
from simple_salesforce import Salesforce
import requests
import os
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime

material = ''
peso = 0
pagamento = ''
data_to_save = []
inventory = str(datetime.now().strftime("%Y%m%d"))

# Exibe a imagem como header
st.image("aitech_logo_B.png", use_container_width=True)

# Função para carregar credenciais do Salesforce
def carregar_credenciais():
    try:
        if os.path.exists('.streamlit/secrets.toml'):
            import toml
            secrets = toml.load('.streamlit/secrets.toml')
        else:
            secrets = st.secrets
        return secrets
    except Exception as e:
        st.error(f"認証情報の読み込みエラー: {e}")
        st.stop()

# Carregar as credenciais
secrets = carregar_credenciais()

# Inicializar o Firebase usando as credenciais do secrets
if not firebase_admin._apps:
    if "firebase" in secrets:
        firebase_secrets = dict(secrets["firebase"])
        required_keys = [
            "type", "project_id", "private_key_id", "private_key",
            "client_email", "client_id", "auth_uri", "token_uri",
            "auth_provider_x509_cert_url", "client_x509_cert_url"
        ]
        missing_keys = [key for key in required_keys if key not in firebase_secrets or not firebase_secrets[key]]
        if missing_keys:
            st.error(f"firebase_secretsに必須キーが欠けています: {missing_keys}")
            st.stop()

        if isinstance(firebase_secrets["private_key"], str) and "\\n" in firebase_secrets["private_key"]:
            firebase_secrets["private_key"] = firebase_secrets["private_key"].replace("\\n", "\n")
        elif not isinstance(firebase_secrets["private_key"], str):
            st.error("「private_key」は有効な文字列ではありません！")
            st.stop()

        cred = credentials.Certificate(firebase_secrets)
        firebase_admin.initialize_app(cred, {
            "databaseURL": "https://uminventory-4a2a8-default-rtdb.asia-southeast1.firebasedatabase.app/"
        })
    else:
        st.error("secretsに「firebase」キーが見つかりません！")
        st.stop()

# Função para autenticar no Salesforce usando OAuth2
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
    except Exception as e:
        st.error(f"認証中に予期しないエラーが発生しました: {e}")
        st.stop()

# Inicializa estados de sessão necessários
if 'owner' not in st.session_state:
    st.session_state['owner'] = ''
if 'reset_form' not in st.session_state:
    st.session_state['reset_form'] = False
if 'registrado' not in st.session_state:
    st.session_state['registrado'] = False
if 'update' not in st.session_state:
    st.session_state['update'] = False
if 'mostrar_sucesso' not in st.session_state:
    st.session_state['mostrar_sucesso'] = False
if 'dados_registro' not in st.session_state:
    st.session_state['dados_registro'] = {}
if 'process_order_atual' not in st.session_state:
    st.session_state['process_order_atual'] = None  # Inicializado como None

# Função para verificar se o registro já existe no Firebase
def check_existing_record_with_date(production_order, date_str, data_to_save):
    ref = db.reference(inventory)
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
    ref = db.reference(inventory)
    records = ref.order_by_child("production_order").equal_to(production_order).get()
    if records:
        for key, value in records.items():
            record_date = value.get("datetime", "").split()[0]
            if record_date == date_str:
                return True, key
    return False, None

# Função para gravar no Firebase
def gravar_firebase(data):
    ref = db.reference(inventory)
    new_record = ref.push(data)
    return new_record.key

# Função para atualizar registro no Firebase
def update_firebase(record_id, data):
    ref = db.reference(f"{inventory}/{record_id}")
    ref.update(data)
    return record_id

# Função para verificar o último registro no Firebase
def verify_last_record(record_id):
    ref = db.reference(inventory)
    return ref.child(record_id).get()

# Função para resetar o formulário
def reset_formulario():
    st.session_state['reset_form'] = True
    st.session_state['registrado'] = False
    st.session_state['update'] = False
    st.session_state['mostrar_sucesso'] = False
    st.session_state['process_order_atual'] = None
    st.rerun()

# Função para processar o registro bem-sucedido
def registrar_sucesso(quantidade, process_order, work_place, cumulative_cost, process_name, product_code, production_order, material, peso, pagamento):
    datetime_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_only = datetime.now().strftime("%Y-%m-%d")

    data_to_save = {
        "datetime": datetime_str,
        "production_order": production_order,
        "quantity": quantidade,
        "owner": st.session_state['owner'],
        "product_code": product_code,
        "process_name": process_name,
        "process_order": process_order,
        "work_place": work_place,
        "cumulative_cost": cumulative_cost,
        "material": material,
        "material_provision_type": pagamento,
        "material_weight": peso
    }

    exists, existing_key = check_existing_record_with_date(production_order, date_only, data_to_save)

    update_exists, update_key = check_for_update(production_order, date_only)
    if update_exists:
        st.session_state['update'] = True
        update_firebase(update_key, data_to_save)
    else:
        record_id = gravar_firebase(data_to_save)

    st.session_state['registrado'] = True
    st.session_state['mostrar_sucesso'] = True
    st.session_state['dados_registro'] = {
        'production_order': production_order,
        'product_code': product_code,
        'work_place': work_place,
        'process_name': process_name,
        'quantidade': quantidade,
        'process_order': process_order
    }
    st.rerun()

# Campo para digitar o "Owner" no início
if not st.session_state['owner']:
    st.session_state['owner'] = st.text_input("担当者コードを入力してください:", key="owner_input")
    if not st.session_state['owner']:
        st.stop()

# Se já registrou com sucesso, mostrar mensagem e botão para novo registro
if st.session_state['mostrar_sucesso']:
    if st.session_state['update']:
        st.success("登録が正常に更新されました！")
    else:
        st.success("登録が正常に完了しました！")

    col1, col2 = st.columns(2)

    with col1:
        st.write(f"担当者: {st.session_state['owner']}")
        st.write(f"移行票: {st.session_state['dados_registro'].get('production_order', '')}")
        st.write(f"工程名: {st.session_state['dados_registro'].get('process_name', '')}")
    with col2:
        st.write(f"作業場所: {st.session_state['dados_registro'].get('work_place', '')}")
        st.write(f"報告数量: {st.session_state['dados_registro'].get('quantidade', 0)}")
        st.write(f"工程順序: {st.session_state['dados_registro'].get('process_order', '')}")

    if st.button("新規登録", key="btn_novo_registro"):
        reset_formulario()
    st.stop()

# Leitura do QR-Code ou input manual
col1, col2 = st.columns(2)

with col1:
    qr_code = qrcode_scanner(key="qr_code_scanner")
    if qr_code:
        pass

with col2:
    if st.session_state['reset_form']:
        input_manual = st.text_input(
            "移行票番号を入力してください:",
            value="",
            key="input_manual_reset"
        )
    else:
        input_manual = st.text_input(
            "移行票番号を入力してください:",
            key="input_manual_normal"
        )

# Processamento do input
production_order = ""
if qr_code:
    production_order = qr_code.strip()
    st.session_state['reset_form'] = False
elif input_manual:
    production_order = f"PO-{str(input_manual.strip()).zfill(6)}"

if production_order:
    st.write(f"検出された移行票: {production_order}")
else:
    st.info("QRコードの読み取りまたは手動入力を待っています。")

# Função para buscar dados do Salesforce
def buscar_dados_salesforce(production_order, process_order=None):
    try:
        sf = authenticate_salesforce()
        query = f"""
            SELECT Id, Name, snps_um__ProcessName__c, snps_um__ActualQt__c, snps_um__Item__r.Id, 
                snps_um__Item__r.Name, snps_um__ProcessOrderNo__c, snps_um__ProdOrder__r.Id, 
                snps_um__ProdOrder__r.Name, snps_um__Status__c, snps_um__WorkPlace__r.Id, 
                snps_um__WorkPlace__r.Name, snps_um__StockPlace__r.Name, snps_um__Item__c, 
                snps_um__Process__r.AITC_Acumulated_Price__c, AITC_OrderQt__c, snps_um__EndDateTime__c 
            FROM snps_um__WorkOrder__c 
            WHERE snps_um__ProdOrder__r.Name = '{production_order}'
        """
        if process_order is not None:
            query += f" AND snps_um__ProcessOrderNo__c = {process_order}"
        query += " ORDER BY snps_um__ProcessOrderNo__c DESC"
        result = sf.query(query)
        return result['records']
    except Exception as e:
        st.error(f"Salesforceからのデータ取得エラー: {e}")
        return []

def buscar_materiais(materiais):
    try:
        sf = authenticate_salesforce()
        query = f"""
                SELECT snps_um__ChildItem__r.Name, snps_um__AddQt__c, 
                       snps_um__ChildItem__r.AITC_ProcessPattern__c 
                FROM snps_um__Composition2__c
                WHERE snps_um__ParentItem2__c = '{materiais}'
                """
        result = sf.query(query)
        return result['records']
    except Exception as e:
        st.error(f"この製品では材料が使用されていません: {e}")
        return []

# Busca inicial e formulário
if production_order and not st.session_state['registrado']:
    # Busca inicial para o último "Done"
    registros = buscar_dados_salesforce(production_order)
    if not registros:
        st.warning("この移行票に対応する記録が見つかりませんでした。")
    else:
        registros_done = [r for r in registros if r.get('snps_um__Status__c') == 'Done']
        if not registros_done:
            st.warning("この移行票には生産記録がありません。")
        else:
            ultimo_done = registros_done[0]
            quantidade_atual = int(ultimo_done.get('snps_um__ActualQt__c', 0))
            process_order_no = int(ultimo_done.get('snps_um__ProcessOrderNo__c', 0))
            work_place = str(ultimo_done.get("snps_um__WorkPlace__r", {}).get("Name", ""))
            cumulative_cost = float(ultimo_done.get("snps_um__Process__r", {}).get("AITC_Acumulated_Price__c", 0.00))
            process_name = str(ultimo_done.get("snps_um__ProcessName__c", ""))
            product_code = str(ultimo_done.get("snps_um__Item__r", {}).get("Name", "N/A"))

            # Busca de materiais (executada apenas uma vez)
            try:
                materiais = registros[0]['snps_um__Item__c']
                materiais = buscar_materiais(materiais)
                if materiais:
                    material = materiais[0]['snps_um__ChildItem__r']['Name']
                    peso = materiais[0]['snps_um__AddQt__c']
                    kosei = materiais[0]['snps_um__ChildItem__r']['AITC_ProcessPattern__c']
                    sf = authenticate_salesforce()
                    query = f"""
                            SELECT snps_um__PaidProvideDiv__c
                            FROM snps_um__Process__c
                            WHERE snps_um__ProcessPattern__c = '{kosei}'
                            """
                    pagamento = sf.query(query)
                    if pagamento['totalSize'] > 0:
                        pagamento = "有償支給" if pagamento['records'][0]['snps_um__PaidProvideDiv__c'] == "Paid" else "無償支給"
            except Exception as e:
                print(e)

            with st.form(key="form_registro_inventario"):
                st.subheader(f"在庫登録 - {product_code}")

                quantidade_contagem = st.number_input(
                    "最後の完了工程の登録数",
                    value=quantidade_atual,
                    step=1,
                    key="quantidade_input_form"
                )

                process_order_input = st.number_input(
                    "工程順序 (10〜999)",
                    min_value=10,
                    max_value=999,
                    value=process_order_no,
                    step=10,
                    key="process_order_input_form"
                )

                # Inicializar valores padrão
                if st.session_state['process_order_atual'] is None:
                    st.session_state['process_order_atual'] = process_order_no

                # Atualizar dados com base no process_order_input
                if process_order_input != st.session_state['process_order_atual']:
                    st.session_state['process_order_atual'] = process_order_input
                    registros_atualizados = buscar_dados_salesforce(production_order, process_order_input)
                    if registros_atualizados:
                        registro_atual = registros_atualizados[0]
                        work_place = str(registro_atual.get("snps_um__WorkPlace__r", {}).get("Name", ""))
                        cumulative_cost = float(registro_atual.get("snps_um__Process__r", {}).get("AITC_Acumulated_Price__c", 0.00))
                        process_name = str(registro_atual.get("snps_um__ProcessName__c", ""))
                    else:
                        st.warning(f"工程順序 {process_order_input} に対応する記録が見つかりませんでした。")
                        work_place = ""
                        cumulative_cost = 0.00
                        process_name = ""

                col1, col2 = st.columns(2)
                # Exibir os valores atuais para depuração
                with col1:
                    st.write(f"作業場所: {work_place}")
                    division_checkbox = st.checkbox("分割")
                with col2:
                    st.write(f"工程名: {process_name}")
                    submit_button = st.form_submit_button(label="登録")

                if division_checkbox:
                    production_order = production_order + "-1"

            if submit_button and work_place != "":
                registrar_sucesso(quantidade_contagem, process_order_input, work_place, cumulative_cost,
                                  process_name, product_code, production_order, material, peso, pagamento)

