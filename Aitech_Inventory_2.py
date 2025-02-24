import streamlit as st
import pandas as pd
from simple_salesforce import Salesforce
import os
import pytz
from datetime import datetime
import requests
from google.oauth2.service_account import Credentials
import gspread
import toml
from streamlit_qrcode_scanner import qrcode_scanner

# Dicionário de traduções
translations = {
    "ja": {
        "title": "棚卸管理システム",
        "qr_code_prompt": "カメラが動作しない場合は、Safariを使用するか、ページを再読み込みしてみてください。",
        "input_label": "移行票の数値部分のみを入力してください (またはQRコードをスキャンしてください):",
        "invalid_qr": "QRコードが無効です。PO-000000の形式を使用してください。",
        "invalid_input": "有効な数値を0から999999の間で入力してください。",
        "already_registered": "登録済",
        "no_record_found": "入力されたコードに対して、レコードが見つかりませんでした。",
        "salesforce_error": "Salesforceへの問い合わせでエラーが発生しました: {error}",
        "quantity_label": "数量:",
        "responsible_label": "担当者コード",
        "register_button": "データ登録",
        "not_started": "生産が開始されていないため。移行票№: {code}　は登録されません。",
        "success_message": "データが正常に確認されました！",
        "details_label": "移行票№: {code} / {item}",
        "quantity_responsible": "数量: {quantity}     担当者コード: {responsible}",
        "pending_label": "移行票 {total}件(登録済み)　再確認待ち {pending}件",
        "pending_popover": "再確認待ち",
        "details_popover": "現在棚卸詳細",
        "empty_warning": "空",
        "save_button": "Google Sheet 保存",
        "save_success": "Googleスプレッドシートにデータを追加しました！",
        "already_saved": "すべてのデータはすでにGoogle Sheetsに保存されています。",
        "no_data_to_save": "保存するデータがありません。",
        "cell_limit_exceeded": "セルの上限を超えました。新しいシートを追加できません。既存のシートを削除するか、不要なシートを整理してください。",
        "new_sheet_success": "新しいシートが作成され、{rows} 行のデータが保存されました！",
        "new_sheet_error": "新しいシートの作成中にエラーが発生しました: {error}",
        "save_error": "Google Sheetsへの保存エラー: {error}",
        "sheets_load_error": "Google Sheets の既存データの読み込み中にエラーが発生しました: {error}",
        "process_selection": "工程選択:",
        "last_completion_date": "最後完了日",
        "item": "品目",
        "rank": "ランク",
        "completed_process": "完了工程",
        "order": "順序",
        "cumulative_cost": "累積単価"
    },
    "en": {
        "title": "Inventory Management System",
        "qr_code_prompt": "If the camera doesn't work, try using Safari or reloading the page.",
        "input_label": "Enter only the numeric part of the production order (or scan the QR code):",
        "invalid_qr": "Invalid QR code. Use the format PO-000000.",
        "invalid_input": "Enter a valid number between 0 and 999999.",
        "already_registered": "Already registered",
        "no_record_found": "No records found for the entered code.",
        "salesforce_error": "Error querying Salesforce: {error}",
        "quantity_label": "Quantity:",
        "responsible_label": "Responsible Code",
        "register_button": "Register Data",
        "not_started": "Production has not started, so production order {code} will not be registered.",
        "success_message": "Data successfully confirmed!",
        "details_label": "Production Order: {code} / {item}",
        "quantity_responsible": "Quantity: {quantity}     Responsible Code: {responsible}",
        "pending_label": "Production Orders {total} (registered)　Pending Confirmation {pending}",
        "pending_popover": "Pending Confirmation",
        "details_popover": "Current Inventory Details",
        "empty_warning": "Empty",
        "save_button": "Save to Google Sheet",
        "save_success": "Data added to Google Sheets!",
        "already_saved": "All data is already saved in Google Sheets.",
        "no_data_to_save": "No data to save.",
        "cell_limit_exceeded": "Cell limit exceeded. Cannot add a new sheet. Please delete or clean up existing sheets.",
        "new_sheet_success": "New sheet created and data saved with {rows} rows!",
        "new_sheet_error": "Error creating new sheet: {error}",
        "save_error": "Error saving to Google Sheets: {error}",
        "sheets_load_error": "Error loading existing Google Sheets data: {error}",
        "process_selection": "Process Selection:",
        "last_completion_date": "Last Completion Date",
        "item": "Item",
        "rank": "Rank",
        "completed_process": "Completed Process",
        "order": "Order",
        "cumulative_cost": "Cumulative Cost"
    }
}

# Seletor de idioma
if "language" not in st.session_state:
    st.session_state.language = "ja"  # Idioma padrão: japonês
language = st.selectbox("Language / 言語", ["Japanese / 日本語", "English / 英語"],
                        index=0 if st.session_state.language == "ja" else 1)
st.session_state.language = "ja" if language == "Japanese / 日本語" else "en"


# Função para obter a tradução
def t(key, **kwargs):
    return translations[st.session_state.language][key].format(**kwargs)


# Função para carregar credenciais de acordo com o ambiente
def carregar_credenciais():
    if os.path.exists('secrets.toml'):
        secrets = toml.load('secrets.toml')
    else:
        secrets = st.secrets
    return secrets


# Carrega as credenciais
secrets = carregar_credenciais()

# Configuração do Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials_dict = {
    "type": secrets["google_service_account"]["type"],
    "project_id": secrets["google_service_account"]["project_id"],
    "private_key_id": secrets["google_service_account"]["private_key_id"],
    "private_key": secrets["google_service_account"]["private_key"],
    "client_email": secrets["google_service_account"]["client_email"],
    "client_id": secrets["google_service_account"]["client_id"],
    "auth_uri": secrets["google_service_account"]["auth_uri"],
    "token_uri": secrets["google_service_account"]["token_uri"],
    "auth_provider_x509_cert_url": secrets["google_service_account"]["auth_provider_x509_cert_url"],
    "client_x509_cert_url": secrets["google_service_account"]["client_x509_cert_url"],
    "universe_domain": secrets["google_service_account"]["universe_domain"],
}
creds = Credentials.from_service_account_info(credentials_dict, scopes=scope)
client = gspread.authorize(creds)

# Fuso horário do Japão (JST)
jst = pytz.timezone('Asia/Tokyo')

# Inicializa o estado da sessão
if "botao_confirmar_ativo" not in st.session_state:
    st.session_state.botao_confirmar_ativo = True
if "google_sheet_data" not in st.session_state:
    st.session_state.google_sheet_data = {
        "df_todos": pd.DataFrame(),
        "valores_coluna": pd.Series(),
        "df_filtrado": pd.DataFrame(),
        "total_prodorder": 0,
        "total_prodorder_check": 0
    }
if "last_codigo" not in st.session_state:
    st.session_state.last_codigo = ""
if "codigo_input" not in st.session_state:
    st.session_state.codigo_input = ""
if "quantidade_input" not in st.session_state:
    st.session_state.quantidade_input = ""
if "codigo_responsavel_input" not in st.session_state:
    st.session_state.codigo_responsavel_input = ""
if "record_exists" not in st.session_state:
    st.session_state.record_exists = True  # Inicialmente True até a consulta

st.image('aitech_logo_B.png', use_container_width=True)


# Função para autenticar no Salesforce (Cache por 10 minutos)
@st.cache_data(ttl=600)
def authenticate_salesforce():
    auth_url = f"{secrets['DOMAIN']}/services/oauth2/token"
    auth_data = {
        'grant_type': 'password',
        'client_id': secrets['CONSUMER_KEY'],
        'client_secret': secrets['CONSUMER_SECRET'],
        'username': secrets['USERNAME'],
        'password': secrets['PASSWORD']
    }
    response = requests.post(auth_url, data=auth_data)
    response.raise_for_status()
    return Salesforce(instance_url=response.json()['instance_url'], session_id=response.json()['access_token'])


# Mapeamento dos status (mantido em japonês por ser parte dos dados)
status_mapping = {
    "BeforeOrderConfirmation": "確定前",
    "OrderConfirmed": "確定",
    "InProduction": "製造中",
    "Done": "作業完了",
    "Cancelled": "キャンセル"
}


# Função para carregar dados existentes do Google Sheets (apenas para verificação)
def carregar_dados_existentes_google_sheet():
    try:
        spreadsheet = client.open("棚卸_記録")
        nome_aba = datetime.now(jst).strftime("%Y%m%d")
        sheet_names = [sheet.title for sheet in spreadsheet.worksheets()]
        if nome_aba in sheet_names:
            worksheet = spreadsheet.worksheet(nome_aba)
            df = pd.DataFrame(worksheet.get_all_records())
            if not df.empty:
                df = df.reset_index(drop=True)
                return df
        return pd.DataFrame()
    except Exception as e:
        st.error(t("sheets_load_error", error=str(e)))
        return pd.DataFrame()


# Leitura do QR code
qr_code = qrcode_scanner(key="qr_scanner")
if qr_code is None:
    st.info(t("qr_code_prompt"))

# Campo de entrada manual com valor inicial do QR code, se disponível
if qr_code:
    if qr_code.startswith("PO-") and qr_code[3:].isdigit() and len(qr_code) == 9:
        st.session_state.codigo_input = qr_code[3:]  # Extrai apenas os dígitos para entrada manual
        if st.session_state.botao_confirmar_ativo:
            st.session_state.quantidade_input = "0"
    else:
        st.warning(t("invalid_qr"))

codigo_input = st.text_input(
    t("input_label"),
    value=st.session_state.codigo_input,
    key="codigo_input"
)

# Formata o código para "PO-000000"
if qr_code and qr_code.startswith("PO-") and qr_code[3:].isdigit() and len(qr_code) == 9:
    codigo_formatado = qr_code
elif codigo_input.isdigit() and 0 <= int(codigo_input) <= 999999:
    codigo_formatado = f"PO-{int(codigo_input):06d}"
else:
    codigo_formatado = None
    if codigo_input and not qr_code:
        st.warning(t("invalid_input"))


# Verifica se o código existe nos dados salvos ou temporários
def verificar_codigo_existente(codigo_formatado):
    # Verifica nos dados salvos no Google Sheets
    dados_existentes = carregar_dados_existentes_google_sheet()
    exists_in_sheets = any(
        dados_existentes["移行票№"].str.slice(0, 9) == codigo_formatado) if not dados_existentes.empty else False

    # Verifica nos dados temporários
    dados_temp = st.session_state.google_sheet_data["df_todos"]
    exists_in_temp = any(dados_temp["移行票№"].str.slice(0, 9) == codigo_formatado) if not dados_temp.empty else False

    # Retorna True se existe em qualquer um dos dois
    exists = exists_in_sheets or exists_in_temp
    if exists:
        st.warning(t("already_registered"))
        st.session_state.record_exists = False  # Desativa o botão se duplicado
    return exists


# Consulta ao Salesforce e verificação de duplicatas
if codigo_formatado:
    try:
        # Consulta ao Salesforce sempre para atualizar a quantidade
        sf = authenticate_salesforce()
        query = f"""
        SELECT Name, snps_um__ProcessName__c, snps_um__ActualQt__c, snps_um__Item__r.Name, 
               snps_um__Item__r.AITC_PrintItemName__c, snps_um__ProcessOrderNo__c, 
               snps_um__ProdOrder__r.Name, snps_um__Status__c, snps_um__WorkPlace__r.Name,
               snps_um__StockPlace__r.Name, snps_um__Item__c, snps_um__Process__r.Process_cost__c, 
               snps_um__Item__r.AITC_ItemRank__c, snps_um__Item__r.snps_um__Weight__c, 
               AITC_OrderQt__c, snps_um__EndDateTime__c 
        FROM snps_um__WorkOrder__c 
        WHERE snps_um__ProdOrder__r.Name = '{codigo_formatado}'
        """
        result = sf.query(query)

        material, pagamento, peso = "-", "-", "-"
        lista_kotei = []
        last_done_record = None

        if result['totalSize'] > 0:
            father_id = result['records'][0]['snps_um__Item__c']
            query = f"""
                    SELECT snps_um__ChildItem__r.Name, snps_um__AddQt__c, snps_um__ChildItem__r.AITC_ProcessPattern__c 
                    FROM snps_um__Composition2__c
                    WHERE snps_um__ParentItem2__c = '{father_id}'
                    """
            procura_shikyu1 = sf.query(query)
            if procura_shikyu1['totalSize'] > 0:
                peso = procura_shikyu1['records'][0]['snps_um__AddQt__c']
                kosei = procura_shikyu1['records'][0]['snps_um__ChildItem__r']['AITC_ProcessPattern__c']
                query = f"""
                        SELECT snps_um__PaidProvideDiv__c
                        FROM snps_um__Process__c
                        WHERE snps_um__ProcessPattern__c = '{kosei}'
                        """
                procura_shikyu2 = sf.query(query)
                if procura_shikyu2['totalSize'] > 0:
                    material = procura_shikyu1['records'][0]['snps_um__ChildItem__r']['Name']
                    pagamento = "有償支給" if procura_shikyu2['records'][0][
                                                  'snps_um__PaidProvideDiv__c'] == "Paid" else "無償支給"

            first_record = result['records'][0]
            prod_order_no = first_record['snps_um__ProdOrder__r']['Name']
            item_name = first_record['snps_um__Item__r']['Name']
            rank = first_record['snps_um__Item__r']['AITC_ItemRank__c']
            original_order = first_record['AITC_OrderQt__c']

            table_data = []
            price = 0
            headers = ["作業オーダー", "工程", "順序", "数量", "ステータス", "作業場所", "工程単価", "累積単価",
                       "最後完了日"] if st.session_state.language == "ja" else ["Work Order", "Process", "Order",
                                                                                "Quantity", "Status", "Workplace",
                                                                                "Process Cost", "Cumulative Cost",
                                                                                "Last Completion Date"]
            for record in result['records']:
                process_name = record['snps_um__ProcessName__c']
                process_order_no = int(record['snps_um__ProcessOrderNo__c'])
                status = status_mapping.get(record['snps_um__Status__c'], record['snps_um__Status__c'])
                actual_qty = int(record['snps_um__ActualQt__c'])
                work_place_name = record['snps_um__WorkPlace__r']['Name']
                cost_price = record['snps_um__Process__r']['Process_cost__c'] or 0
                price += cost_price
                done_date = record['snps_um__EndDateTime__c']
                done_date = datetime.strptime(done_date, "%Y-%m-%dT%H:%M:%S.%f%z").strftime(
                    "%y/%m/%d") if done_date else "0"

                lista_kotei.append(f"{process_order_no}:{process_name}:{work_place_name}")
                table_data.append([record['Name'], process_name, process_order_no, actual_qty, status, work_place_name,
                                   round(cost_price, 2), round(price, 2), done_date])

            df = pd.DataFrame(table_data, columns=headers)
            last_done_record = df[df[headers[4]] == "作業完了" if st.session_state.language == "ja" else "Done"].iloc[
                -1] if not df[
                df[headers[4]] == ("作業完了" if st.session_state.language == "ja" else "Done")].empty else None

            st.write(t("details_label", code=prod_order_no,
                       item=item_name) + f"　ー　{original_order}　ー　{t('last_completion_date')}: {last_done_record[headers[8]] if last_done_record is not None else '0'}")
            st.write(
                f"**{t('item')}:** {item_name}　**{t('rank')}:** {rank}　**{t('completed_process')}:** {last_done_record[headers[1]] if last_done_record is not None else '(0)'}")


            def highlight_zero_quantity(row):
                return ['background-color: green' if row[headers[3]] != 0 else '' for _ in row]


            styled_df = df.iloc[:, :-2].style.apply(highlight_zero_quantity, axis=1)
            with st.popover(t("details_popover")):
                st.dataframe(styled_df.data)

            selecionado = st.selectbox(t("process_selection"), lista_kotei,
                                       index=len(lista_kotei) - 1 if last_done_record is None else
                                       df.index[df[headers[2]] == last_done_record[headers[2]]].tolist()[0])

            # Atualiza quantidade independentemente de duplicatas
            if last_done_record is not None and st.session_state.botao_confirmar_ativo:
                st.session_state.quantidade_input = str(last_done_record[headers[3]])

            # Verifica duplicatas após consulta ao Salesforce
            if verificar_codigo_existente(codigo_formatado):
                pass  # A mensagem "登録済" já é exibida na função verificar_codigo_existente
            else:
                st.session_state.record_exists = True  # Ativa o botão se não duplicado
        else:
            st.warning(t("no_record_found"))
            st.session_state.record_exists = False  # Desativa o botão se não existe no Salesforce
            last_done_record = None
    except Exception as e:
        st.error(t("salesforce_error", error=str(e)))
        st.session_state.record_exists = False  # Desativa o botão em caso de erro
        last_done_record = None
else:
    last_done_record = None

# Campos de entrada
quantidade = st.text_input(t("quantity_label"), max_chars=10, value=st.session_state.quantidade_input,
                           key="quantidade_input")
codigo_responsavel = st.text_input(t("responsible_label"), value=st.session_state.codigo_responsavel_input,
                                   key="codigo_responsavel_input")

# Botão de confirmação
botao_confirmar_ativado = st.session_state.botao_confirmar_ativo and codigo_formatado and quantidade and codigo_responsavel and st.session_state.record_exists


def salvar_dados_google_sheet(codigo_formatado, quantidade, codigo_responsavel, ordem, ordem_nome, lugar,
                              last_done_record, material, pagamento, peso):
    dados = st.session_state.google_sheet_data
    nome_aba = datetime.now(jst).strftime("%Y%m%d")
    codigo_reformatado = f"{codigo_formatado}-{ordem}"
    cost_price = float(df.loc[df[t("order")] == int(ordem), t("cumulative_cost")].values[0]) if 'df' in globals() else 0

    columns = ["時間", "移行票№", "数量", "担当者コード", "品目", "工程", "順序", "作業場所", "累積単価", "材料", "支払",
               "重量"] if st.session_state.language == "ja" else ["Time", "Production Order", "Quantity",
                                                                  "Responsible Code", "Item", "Process", "Order",
                                                                  "Workplace", "Cumulative Cost", "Material", "Payment",
                                                                  "Weight"]
    nova_linha = pd.DataFrame([[datetime.now(jst).strftime("%Y-%m-%d %H:%M:%S"), codigo_reformatado, int(quantidade),
                                int(codigo_responsavel), item_name, ordem_nome, int(ordem), lugar, cost_price, material,
                                pagamento, peso]],
                              columns=columns)

    if dados["df_todos"].empty:
        dados["df_todos"] = nova_linha
    else:
        dados["df_todos"] = pd.concat([dados["df_todos"], nova_linha], ignore_index=True)

    dados["valores_coluna"] = dados["df_todos"]["移行票№" if st.session_state.language == "ja" else "Production Order"]
    mask = dados["df_todos"]['時間2'].isna() if '時間2' in dados["df_todos"].columns else pd.Series(
        [True] * len(dados["df_todos"]), index=dados["df_todos"].index)
    mask |= (dados["df_todos"]['時間2'] == '') if '時間2' in dados["df_todos"].columns else pd.Series(
        [False] * len(dados["df_todos"]), index=dados["df_todos"].index)
    dados["df_filtrado"] = dados["df_todos"][mask]
    dados["total_prodorder"] = len(dados["df_todos"])
    dados["total_prodorder_check"] = len(dados["df_filtrado"])
    st.session_state.google_sheet_data = dados


if st.button(t("register_button"), disabled=not botao_confirmar_ativado, type="primary"):
    try:
        ordem, ordem_nome, ordem_local = selecionado.split(":")
        salvar_dados_google_sheet(codigo_formatado, quantidade, codigo_responsavel, ordem, ordem_nome, ordem_local,
                                  last_done_record, material, pagamento, peso)
        st.success(t("success_message"))
        st.write(t("details_label", code=codigo_formatado, item=item_name))
        st.write(t("quantity_responsible", quantity=quantidade, responsible=codigo_responsavel))
        st.session_state.botao_confirmar_ativo = False
        st.session_state.codigo_input = ""
        st.session_state.quantidade_input = ""
        st.session_state.record_exists = True  # Reseta para True após sucesso
    except Exception as e:
        st.write(t("not_started", code=codigo_formatado))

# Exibição dos dados
col1, col2, col3 = st.columns(3)
dados = st.session_state.google_sheet_data
st.warning(t("pending_label", total=dados['total_prodorder'], pending=dados['total_prodorder_check']))

with col2:
    with st.popover(t("pending_popover")):
        if not dados["df_filtrado"].empty:
            st.dataframe(dados["df_filtrado"].iloc[:, :9])
        else:
            st.warning(t("empty_warning"))

with col3:
    with st.popover(t("details_popover")):
        if not dados["df_todos"].empty:
            st.dataframe(dados["df_todos"])
        else:
            st.warning(t("empty_warning"))

with col1:
    if st.button(t("save_button")):
        spreadsheet = client.open("棚卸_記録")
        nome_aba = datetime.now(jst).strftime("%Y%m%d")
        try:
            worksheet = spreadsheet.worksheet(nome_aba)
            if not dados["df_todos"].empty:
                dados_existentes = carregar_dados_existentes_google_sheet()
                novos_dados = dados["df_todos"]
                if not dados_existentes.empty:
                    novos_dados = novos_dados[
                        ~novos_dados["移行票№" if st.session_state.language == "ja" else "Production Order"].isin(
                            dados_existentes["移行票№" if st.session_state.language == "ja" else "Production Order"])]
                if not novos_dados.empty:
                    worksheet.append_rows(novos_dados.values.tolist())
                    st.success(t("save_success"))
                else:
                    st.warning(t("already_saved"))
                st.session_state.google_sheet_data = {
                    "df_todos": pd.DataFrame(),
                    "valores_coluna": pd.Series(),
                    "df_filtrado": pd.DataFrame(),
                    "total_prodorder": 0,
                    "total_prodorder_check": 0
                }
            else:
                st.warning(t("no_data_to_save"))
        except gspread.exceptions.WorksheetNotFound:
            try:
                total_cells = sum(sheet.row_count * sheet.col_count for sheet in spreadsheet.worksheets())
                max_new_cells = 10_000_000 - total_cells
                if max_new_cells < 1000:
                    st.error(t("cell_limit_exceeded"))
                elif not dados["df_todos"].empty:
                    rows = min(1000, max_new_cells // 12)
                    spreadsheet.add_worksheet(title=nome_aba, rows=rows, cols=12)
                    worksheet = spreadsheet.worksheet(nome_aba)
                    worksheet.append_rows([dados["df_todos"].columns.tolist()] + dados["df_todos"].values.tolist())
                    st.success(t("new_sheet_success", rows=rows))
                    st.session_state.google_sheet_data = {
                        "df_todos": pd.DataFrame(),
                        "valores_coluna": pd.Series(),
                        "df_filtrado": pd.DataFrame(),
                        "total_prodorder": 0,
                        "total_prodorder_check": 0
                    }
                else:
                    st.warning(t("no_data_to_save"))
            except Exception as e:
                st.error(t("new_sheet_error", error=str(e)))
        except Exception as e:
            st.error(t("save_error", error=str(e)))

if not st.session_state.botao_confirmar_ativo:
    st.session_state.botao_confirmar_ativo = True
