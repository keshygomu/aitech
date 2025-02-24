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

st.image('aitech_logo_B.png', use_container_width=True)

# Gera uma chave única para cada campo
def get_key(base):
    return f"{base}_{st.session_state.botao_confirmar_ativo}"

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

# Mapeamento dos status
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
        st.error(f"Erro ao carregar dados existentes do Google Sheets: {str(e)}")
        return pd.DataFrame()

# Leitura do QR code
qr_code = qrcode_scanner(key="qr_scanner")
if qr_code is None:
    st.info("Se a câmera não funcionar, tente usar o Safari ou recarregar a página.")

# Campo de entrada manual com valor inicial do QR code, se disponível
codigo_input_id = get_key("codigo_input")
if qr_code:
    if qr_code.startswith("PO-") and qr_code[3:].isdigit() and len(qr_code) == 9:
        st.session_state.codigo_input = qr_code[3:]  # Extrai apenas os dígitos para entrada manual
    else:
        st.warning("QR code inválido. Use o formato PO-000000.")

codigo_input = st.text_input(
    "移行票の数値部分のみを入力してください (ou escaneie o QR code):",
    value=st.session_state.codigo_input,
    key=codigo_input_id
)

# Formata o código para "PO-000000"
if qr_code and qr_code.startswith("PO-") and qr_code[3:].isdigit() and len(qr_code) == 9:
    # Se veio do QR code e está no formato correto, usa diretamente
    codigo_formatado = qr_code
elif codigo_input.isdigit() and 0 <= int(codigo_input) <= 999999:
    # Se é entrada manual, formata o número inteiro
    codigo_formatado = f"PO-{int(codigo_input):06d}"
else:
    codigo_formatado = None
    if codigo_input and not qr_code:
        st.warning("Digite um número válido entre 0 e 999999.")

# Verifica se o código existe nos dados já salvos
def verificar_codigo_existente(codigo_formatado):
    dados_existentes = carregar_dados_existentes_google_sheet()
    return any(dados_existentes["移行票№"].str.slice(0, 9) == codigo_formatado) if not dados_existentes.empty else False

# Carrega dados apenas se o código mudou
if codigo_formatado and codigo_formatado != st.session_state.last_codigo:
    st.session_state.last_codigo = codigo_formatado
    if verificar_codigo_existente(codigo_formatado):
        st.warning("登録済")
    else:
        dados = st.session_state.google_sheet_data
        dados["total_prodorder"] = len(dados["df_todos"])
        dados["total_prodorder_check"] = len(dados["df_filtrado"])

# Consulta ao Salesforce
if codigo_formatado:
    try:
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
                    pagamento = "有償支給" if procura_shikyu2['records'][0]['snps_um__PaidProvideDiv__c'] == "Paid" else "無償支給"

        lista_kotei = []
        if result['totalSize'] > 0:
            first_record = result['records'][0]
            prod_order_no = first_record['snps_um__ProdOrder__r']['Name']
            item_name = first_record['snps_um__Item__r']['Name']
            rank = first_record['snps_um__Item__r']['AITC_ItemRank__c']
            original_order = first_record['AITC_OrderQt__c']

            table_data = []
            price = 0
            headers = ["作業オーダー", "工程", "順序", "数量", "ステータス", "作業場所", "工程単価", "累積単価", "最後完了日"]
            for record in result['records']:
                process_name = record['snps_um__ProcessName__c']
                process_order_no = int(record['snps_um__ProcessOrderNo__c'])
                status = status_mapping.get(record['snps_um__Status__c'], record['snps_um__Status__c'])
                actual_qty = int(record['snps_um__ActualQt__c'])
                work_place_name = record['snps_um__WorkPlace__r']['Name']
                cost_price = record['snps_um__Process__r']['Process_cost__c'] or 0
                price += cost_price
                done_date = record['snps_um__EndDateTime__c']
                done_date = datetime.strptime(done_date, "%Y-%m-%dT%H:%M:%S.%f%z").strftime("%y/%m/%d") if done_date else "0"

                lista_kotei.append(f"{process_order_no}:{process_name}:{work_place_name}")
                table_data.append([record['Name'], process_name, process_order_no, actual_qty, status, work_place_name, round(cost_price, 2), round(price, 2), done_date])

            df = pd.DataFrame(table_data, columns=headers)
            last_done_record = df[df['ステータス'] == "作業完了"].iloc[-1] if not df[df['ステータス'] == "作業完了"].empty else None

            st.write(f"**移行票№**: {prod_order_no}　ー　{original_order}　ー　**最後完了日**: {last_done_record['最後完了日'] if last_done_record is not None else '0'}")
            st.write(f"**品目**: {item_name}　**ランク**: {rank}　**完了工程**: {last_done_record['工程'] if last_done_record is not None else '(0)'}")

            def highlight_zero_quantity(row):
                return ['background-color: green' if row['数量'] != 0 else '' for _ in row]

            styled_df = df.iloc[:, :-2].style.apply(highlight_zero_quantity, axis=1)
            with st.popover("製造オーダー明細"):
                st.dataframe(styled_df.data)

            selecionado = st.selectbox('工程選択:', lista_kotei, index=len(lista_kotei)-1 if last_done_record is None else df.index[df['順序'] == last_done_record['順序']].tolist()[0])
        else:
            st.warning("入力されたコードに対して、レコードが見つかりませんでした。")
            last_done_record = None
    except Exception as e:
        st.error(f"Salesforceへの問い合わせでエラーが発生しました: {str(e)}")
        last_done_record = None
else:
    last_done_record = None

# Campos de entrada
quantidade_input_id = get_key("quantidade_input")
quantidade = st.text_input("数量:", max_chars=10, value=str(last_done_record['数量']) if last_done_record is not None else "0", key=quantidade_input_id)

codigo_responsavel_input_id = get_key("codigo_responsavel_input")
codigo_responsavel = st.text_input("担当者コード", key=codigo_responsavel_input_id)

# Botão de confirmação
botao_confirmar_ativado = st.session_state.botao_confirmar_ativo and codigo_formatado and quantidade and codigo_responsavel

def salvar_dados_google_sheet(codigo_formatado, quantidade, codigo_responsavel, ordem, ordem_nome, lugar, last_done_record, material, pagamento, peso):
    dados = st.session_state.google_sheet_data
    nome_aba = datetime.now(jst).strftime("%Y%m%d")
    codigo_reformatado = f"{codigo_formatado}-{ordem}"
    cost_price = float(df.loc[df['順序'] == int(ordem), '累積単価'].values[0]) if 'df' in globals() else 0

    nova_linha = pd.DataFrame([[datetime.now(jst).strftime("%Y-%m-%d %H:%M:%S"), codigo_reformatado, int(quantidade), int(codigo_responsavel), item_name, ordem_nome, int(ordem), lugar, cost_price, material, pagamento, peso]], 
                              columns=["時間", "移行票№", "数量", "担当者コード", "品目", "工程", "順序", "作業場所", "累積単価", "材料", "支払", "重量"])
    
    if dados["df_todos"].empty:
        dados["df_todos"] = nova_linha
    else:
        dados["df_todos"] = pd.concat([dados["df_todos"], nova_linha], ignore_index=True)
    
    dados["valores_coluna"] = dados["df_todos"]["移行票№"]
    mask = dados["df_todos"]['時間2'].isna() if '時間2' in dados["df_todos"].columns else pd.Series([True] * len(dados["df_todos"]), index=dados["df_todos"].index)
    mask |= (dados["df_todos"]['時間2'] == '') if '時間2' in dados["df_todos"].columns else pd.Series([False] * len(dados["df_todos"]), index=dados["df_todos"].index)
    dados["df_filtrado"] = dados["df_todos"][mask]
    dados["total_prodorder"] = len(dados["df_todos"])
    dados["total_prodorder_check"] = len(dados["df_filtrado"])
    st.session_state.google_sheet_data = dados

if st.button("データ登録", disabled=not botao_confirmar_ativado, type="primary"):
    try:
        ordem, ordem_nome, ordem_local = selecionado.split(":")
        salvar_dados_google_sheet(codigo_formatado, quantidade, codigo_responsavel, ordem, ordem_nome, ordem_local, last_done_record, material, pagamento, peso)
        st.success("データが正常に確認されました！")
        st.write(f"移行票№: {codigo_formatado} / {item_name}")
        st.write(f"数量: {quantidade}     担当者コード: {codigo_responsavel}")
        st.session_state.botao_confirmar_ativo = False
        st.session_state.codigo_input = ""  # Limpa o campo de entrada do código
        # Limpa o campo quantidade resetando o valor padrão para "0" no próximo ciclo
        # Como quantidade é controlado pelo widget, o reset será refletido no próximo rerender
        st.session_state[quantidade_input_id] = "0"  # Reinicia o valor do quantidade no session_state
    except Exception as e:
        st.write(f"生産が開始されていないため。移行票№: {codigo_formatado}　は登録されません。")

# Exibição dos dados
col1, col2, col3 = st.columns(3)
dados = st.session_state.google_sheet_data
st.warning(f"移行票 {dados['total_prodorder']}件(登録済み)　再確認待ち {dados['total_prodorder_check']}件")

with col2:
    with st.popover("再確認待ち"):
        if not dados["df_filtrado"].empty:
            st.dataframe(dados["df_filtrado"].iloc[:, :9])
        else:
            st.warning("空")

with col3:
    with st.popover("現在棚卸詳細"):
        if not dados["df_todos"].empty:
            st.dataframe(dados["df_todos"])
        else:
            st.warning("空")

with col1:
    if st.button("Google Sheet 保存"):
        spreadsheet = client.open("棚卸_記録")
        nome_aba = datetime.now(jst).strftime("%Y%m%d")
        try:
            worksheet = spreadsheet.worksheet(nome_aba)
            # Se a aba existe, apenas adiciona os dados sem limpar
            if not dados["df_todos"].empty:
                # Verificar duplicatas antes de salvar
                dados_existentes = carregar_dados_existentes_google_sheet()
                novos_dados = dados["df_todos"]
                if not dados_existentes.empty:
                    novos_dados = novos_dados[~novos_dados["移行票№"].isin(dados_existentes["移行票№"])]
                if not novos_dados.empty:
                    worksheet.append_rows(novos_dados.values.tolist())
                    st.success("Dados adicionados ao Google Sheets!")
                else:
                    st.warning("Todos os dados já estão salvos no Google Sheets.")
                # Zerar os dados após salvar
                st.session_state.google_sheet_data = {
                    "df_todos": pd.DataFrame(),
                    "valores_coluna": pd.Series(),
                    "df_filtrado": pd.DataFrame(),
                    "total_prodorder": 0,
                    "total_prodorder_check": 0
                }
            else:
                st.warning("Nenhum dado para salvar.")
        except gspread.exceptions.WorksheetNotFound:
            # Se a aba não existe, cria e adiciona os dados com cabeçalhos
            try:
                total_cells = sum(sheet.row_count * sheet.col_count for sheet in spreadsheet.worksheets())
                max_new_cells = 10_000_000 - total_cells
                if max_new_cells < 1000:
                    st.error("Limite de células excedido. Não é possível adicionar uma nova aba. Por favor, limpe ou remova abas existentes.")
                elif not dados["df_todos"].empty:
                    rows = min(1000, max_new_cells // 12)
                    spreadsheet.add_worksheet(title=nome_aba, rows=rows, cols=12)
                    worksheet = spreadsheet.worksheet(nome_aba)
                    worksheet.append_rows([dados["df_todos"].columns.tolist()] + dados["df_todos"].values.tolist())
                    st.success(f"Nova aba criada e dados salvos com {rows} linhas!")
                    # Zerar os dados após salvar
                    st.session_state.google_sheet_data = {
                        "df_todos": pd.DataFrame(),
                        "valores_coluna": pd.Series(),
                        "df_filtrado": pd.DataFrame(),
                        "total_prodorder": 0,
                        "total_prodorder_check": 0
                    }
                else:
                    st.warning("Nenhum dado para salvar.")
            except Exception as e:
                st.error(f"Erro ao criar nova aba: {str(e)}")
        except Exception as e:
            st.error(f"Erro ao salvar no Google Sheets: {str(e)}")

if not st.session_state.botao_confirmar_ativo:
    st.session_state.botao_confirmar_ativo = True


