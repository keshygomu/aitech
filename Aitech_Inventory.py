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
        st.error(f"認証情報の読み込みエラー: {e}")  # "Erro ao carregar credenciais"
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
            st.error(f"firebase_secretsに必須キーが欠けています: {missing_keys}")  # "Chaves obrigatórias ausentes em firebase_secrets"
            st.stop()

        if isinstance(firebase_secrets["private_key"], str) and "\\n" in firebase_secrets["private_key"]:
            firebase_secrets["private_key"] = firebase_secrets["private_key"].replace("\\n", "\n")
        elif not isinstance(firebase_secrets["private_key"], str):
            st.error("「private_key」は有効な文字列ではありません！")  # "A chave 'private_key' não é uma string válida!"
            st.stop()

        cred = credentials.Certificate(firebase_secrets)
        firebase_admin.initialize_app(cred, {
            "databaseURL": "https://uminventory-4a2a8-default-rtdb.asia-southeast1.firebasedatabase.app/"
        })
    else:
        st.error("secretsに「firebase」キーが見つかりません！")  # "A chave 'firebase' não foi encontrada em secrets!"
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
        st.error(f"認証エラー: {e}")  # "Erro de autenticação"
        st.stop()
    except Exception as e:
        st.error(f"認証中に予期しないエラーが発生しました: {e}")  # "Erro inesperado durante autenticação"
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
    st.rerun()

# Função para processar o registro bem-sucedido
def registrar_sucesso(quantidade, process_order, work_place, cumulative_cost, process_name, product_code, production_order):
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
    st.session_state['owner'] = st.text_input("担当者の名前またはコードを入力してください:", key="owner_input")  # "Digite o nome ou código do responsável:"
    if not st.session_state['owner']:
        st.warning("続行する前に担当者を入力してください。")  # "Por favor, insira o responsável antes de continuar."
        st.stop()

# Se já registrou com sucesso, mostrar mensagem e botão para novo registro
if st.session_state['mostrar_sucesso']:
    if st.session_state['update']:
        st.success("登録が正常に更新されました！")  # "Registro foi atualizado com sucesso!"
    else:
        st.success("登録が正常に完了しました！")  # "Registro realizado com sucesso!"

    # Dividir em duas colunas
    col1, col2 = st.columns(2)

    with col1:
        st.write(f"担当者: {st.session_state['owner']}")  # "Responsável"
        st.write(f"生産オーダー: {st.session_state['dados_registro'].get('production_order', '')}")  # "Production Order"
        st.write(f"プロセス名: {st.session_state['dados_registro'].get('process_name', '')}")  # "Process Name"

    with col2:
        st.write(f"作業場所: {st.session_state['dados_registro'].get('work_place', '')}")  # "Work Place"
        st.write(f"報告数量: {st.session_state['dados_registro'].get('quantidade', 0)}")  # "Quantidade Informada"
        st.write(f"プロセスオーダー番号: {st.session_state['dados_registro'].get('process_order', '')}")  # "ProcessOrderNo"

    if st.button("新規登録", key="btn_novo_registro"):  # "Novo Registro"
        reset_formulario()
    st.stop()

# Leitura do QR-Code ou input manual
col1, col2 = st.columns(2)

# Sempre renderizar o QR code scanner
with col1:
    qr_code = qrcode_scanner(key="qr_code_scanner")
    if qr_code:
        pass

# Input manual com reset controlado
with col2:
    if st.session_state['reset_form']:
        input_manual = st.text_input(
            "生産オーダーの番号を入力してください (PO-なし):",  # "Digite o número da Ordem de Produção (sem PO-)"
            value="",
            key="input_manual_reset"
        )
    else:
        input_manual = st.text_input(
            "生産オーダーの番号を入力してください (PO-なし):",  # "Digite o número da Ordem de Produção (sem PO-)"
            key="input_manual_normal"
        )

# Processamento do input
production_order = ""
if qr_code:
    production_order = qr_code.strip()
    st.session_state['reset_form'] = False
elif input_manual:
    production_order = f"PO-{str(input_manual.strip()).zfill(6)}"

# Exibir o production_order para depuração
if production_order:
    st.write(f"検出された生産オーダー: {production_order}")  # "Ordem de Produção detectada"
else:
    st.info("QRコードの読み取りまたは手動入力を待っています。")  # "Aguardando leitura do QR-Code ou entrada manual."

# Se temos um production_order, autenticar no Salesforce e buscar dados
registros = []
if production_order and not st.session_state['registrado']:
    try:
        sf = authenticate_salesforce()

        def buscar_dados_salesforce(production_order):
            try:
                query = f"""
                    SELECT Id, Name, snps_um__ProcessName__c, snps_um__ActualQt__c, snps_um__Item__r.Id, 
                        snps_um__Item__r.Name, snps_um__ProcessOrderNo__c, snps_um__ProdOrder__r.Id, 
                        snps_um__ProdOrder__r.Name, snps_um__Status__c, snps_um__WorkPlace__r.Id, 
                        snps_um__WorkPlace__r.Name, snps_um__StockPlace__r.Name, snps_um__Item__c, 
                        snps_um__Process__r.AITC_Acumulated_Price__c, AITC_OrderQt__c, snps_um__EndDateTime__c 
                    FROM snps_um__WorkOrder__c 
                    WHERE snps_um__ProdOrder__r.Name = '{production_order}'
                    ORDER BY snps_um__EndDateTime__c DESC
                """
                result = sf.query(query)
                return result['records']
            except Exception as e:
                st.error(f"Salesforceからのデータ取得エラー: {e}")  # "Erro ao buscar dados do Salesforce"
                return []

        def buscar_materiais(materiais):
            try:
                query = f"""
                        SELECT snps_um__ChildItem__r.Name, snps_um__AddQt__c, 
                               snps_um__ChildItem__r.AITC_ProcessPattern__c 
                        FROM snps_um__Composition2__c
                        WHERE snps_um__ParentItem2__c = '{materiais}'
                        """
                result = sf.query(query)
                return result['records']
            except Exception as e:
                st.error(f"この製品では材料が使用されていません: {e}")  # "Material não é usado nesse produto"
                return []

        registros = buscar_dados_salesforce(production_order)
        if not registros:
            st.warning("この生産オーダーに対応する記録が見つかりませんでした。")  # "Nenhum registro encontrado para essa Ordem de Produção."
        else:
            try:
                materiais = registros[0]['snps_um__Item__c']
                materiais = buscar_materiais(materiais)
            except Exception as e:
                print(e)

            if materiais:
                material = materiais[0]['snps_um__ChildItem__r']['Name']
                peso = materiais[0]['snps_um__AddQt__c']
                kosei = materiais[0]['snps_um__ChildItem__r']['AITC_ProcessPattern__c']
                query = f"""
                        SELECT snps_um__PaidProvideDiv__c
                        FROM snps_um__Process__c
                        WHERE snps_um__ProcessPattern__c = '{kosei}'
                        """
                pagamento = sf.query(query)
                if pagamento['totalSize'] > 0:
                    pagamento = "有償支給" if pagamento['records'][0]['snps_um__PaidProvideDiv__c'] == "Paid" else "無償支給"

    except Exception as e:
        st.error(f"Salesforceへの認証ができませんでした: {e}")  # "Não foi possível autenticar no Salesforce"

# Exibição dos registros e formulário
if registros and not st.session_state['registrado']:
    registros_done = [r for r in registros if r.get('snps_um__Status__c') == 'Done']

    if not registros_done:
        st.warning("この生産オーダーには生産記録がありません。")  # "Esse production_order não tem registro de produção."
    else:
        ultimo_done = registros_done[0]
        quantidade_atual = float(ultimo_done.get('snps_um__ActualQt__c', 0.0))
        process_order_no = str(ultimo_done.get('snps_um__ProcessOrderNo__c', ''))
        work_place = str(ultimo_done.get("snps_um__WorkPlace__r", {}).get("Name", ""))
        cumulative_cost = str(ultimo_done.get("snps_um__Process__r", {}).get("AITC_Acumulated_Price__c", 0.0))
        process_name = str(ultimo_done.get("snps_um__ProcessName__c", ""))
        product_code = str(ultimo_done.get("snps_um__Item__r", {}).get("Name", "N/A"))

        with st.form(key="form_registro_inventario"):
            st.subheader("在庫登録")  # "Registrar Inventário"

            quantidade_contagem = st.number_input(
                "現在の数量（最後のDone記録に基づく）",  # "Quantidade Atual (baseada no último registro Done)"
                value=quantidade_atual,
                step=0.01,
                key="quantidade_input_form"
            )

            process_order_input = st.text_input(
                "プロセスオーダー番号（最後のDone記録に基づく）",  # "ProcessOrderNo (baseado no último registro Done)"
                value=process_order_no,
                key="process_order_input_form"
            )

            submit_button = st.form_submit_button(label="登録")  # "Registrar"

        if submit_button:
            registrar_sucesso(quantidade_contagem, process_order_input, work_place, cumulative_cost, process_name, product_code, production_order)

