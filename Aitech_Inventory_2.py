import streamlit as st
import pandas as pd
from simple_salesforce import Salesforce
import os
import pytz
from datetime import datetime
import requests
from openpyxl import load_workbook, Workbook
import gspread
from google.oauth2.service_account import Credentials
from gspread_dataframe import set_with_dataframe
import toml

# Função para carregar credenciais de acordo com o ambiente
def carregar_credenciais():
    if os.path.exists('secrets.toml'):
        # Executando localmente
        secrets = toml.load('secrets.toml')
    else:
        # Executando no Streamlit Cloud
        secrets = st.secrets
    return secrets

# Carrega as credenciais
secrets = carregar_credenciais()

# Definir o escopo
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# Acessar as credenciais do Streamlit secrets
credentials = secrets["google_service_account"]

# Converter as credenciais para um dicionário
credentials_dict = {
    "type": credentials["type"],
    "project_id": credentials["project_id"],
    "private_key_id": credentials["private_key_id"],
    "private_key": credentials["private_key"],
    "client_email": credentials["client_email"],
    "client_id": credentials["client_id"],
    "auth_uri": credentials["auth_uri"],
    "token_uri": credentials["token_uri"],
    "auth_provider_x509_cert_url": credentials["auth_provider_x509_cert_url"],
    "client_x509_cert_url": credentials["client_x509_cert_url"],
    "universe_domain": credentials["universe_domain"],
}

# Definir o fuso horário do Japão (JST)
jst = pytz.timezone('Asia/Tokyo')

# Fornecer o caminho para o arquivo JSON baixado
creds = Credentials.from_service_account_info(credentials_dict, scopes=scope)

# Autorizar e inicializar o cliente gspread
client = gspread.authorize(creds)

st.image('aitech_logo.png', use_column_width=True)

# Inicializa as variáveis no session_state para controlar os valores dos inputs
if "botao_confirmar_ativo" not in st.session_state:
    st.session_state.botao_confirmar_ativo = True


# Gera uma chave única para cada campo
def get_key(base):
    return f"{base}_{st.session_state.botao_confirmar_ativo}"


# Função para autenticar e criar uma instância do Salesforce
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
    access_token = response.json()['access_token']
    instance_url = response.json()['instance_url']
    return Salesforce(instance_url=instance_url, session_id=access_token)


# Mapeamento dos status
status_mapping = {
    "BeforeOrderConfirmation": "確定前",
    "OrderConfirmed": "確定",
    "InProduction": "製造中",
    "Done": "作業完了",
    "Cancelled": "キャンセル"
}

# Campo de entrada para o código (texto)
codigo_input_id = get_key("codigo_input")
codigo_input = st.text_input(
    "移行票番号を入力してください:",  # Label alterado
    key=codigo_input_id
)

# Formata o código no formato "PO-000000"
codigo_formatado = f"PO-{int(codigo_input):06d}" if codigo_input.isdigit() else None

df_todos = []
df_filtrado = []
codigo_existente = False
valores_coluna=[]
total_prodorder = 0
total_prodorder_check = 0

def lista_produtos():
    try:
        nome_aba = datetime.now(jst).strftime("%Y%m%d")
        spreadsheet = client.open("棚卸_記録")
        worksheet = spreadsheet.worksheet(nome_aba)
        df_todos = pd.DataFrame(worksheet.get_all_values())
        df_todos.columns = df_todos.iloc[0]
        df_todos = df_todos[1:]
        valores_coluna = df_todos["移行票№"]
        df_filtrado = df_todos[df_todos['時間2'].isna() | (df_todos['時間2'] == '')]
        total_prodorder = len(df_todos)
        total_prodorder_check = len(df_filtrado)
        return(df_todos,df_filtrado,valores_coluna,total_prodorder,total_prodorder_check)
    except Exception as e:
        print(f"Error{e}")
        pass
# Verifica se o arquivo Excel existe e faz a checagem

try:
    if codigo_formatado:
        valores_coluna =lista_produtos()[2]
        if codigo_formatado in valores_coluna.values:
            st.warning("登録済")  # Exibe a mensagem de alerta
except:
    total_prodorder = 0
    total_prodorder_check = 0



    # Realiza a consulta ao Salesforce ao inserir o código
if codigo_input:
    try:
        sf = authenticate_salesforce()
        query = f"""
        SELECT Name, snps_um__ProcessName__c, snps_um__ActualQt__c, snps_um__Item__r.Name, 
               snps_um__Item__r.AITC_PrintItemName__c, snps_um__ProcessOrderNo__c, 
               snps_um__ProdOrder__r.Name, snps_um__Status__c, snps_um__WorkPlace__r.Name,
               snps_um__StockPlace__r.Name, snps_um__Item__c, snps_um__Process__r.Process_cost__c, 
               snps_um__Item__r.AITC_ItemRank__c, snps_um__Item__r.snps_um__Weight__c, 
               AITC_OrderQt__c 
        FROM snps_um__WorkOrder__c 
        WHERE snps_um__ProdOrder__r.Name = '{codigo_formatado}'
        """
        result = sf.query(query)

        if result['totalSize'] > 0:
            # Exibe os itens que não se repetem no topo (considerando o primeiro registro)
            first_record = result['records'][0]
            prod_order_no = first_record['snps_um__ProdOrder__r']['Name']
            item_name = first_record['snps_um__Item__r']['Name']
            item_print_name = first_record['snps_um__Item__r']['AITC_PrintItemName__c']
            rank = first_record['snps_um__Item__r']['AITC_ItemRank__c']
            weight = first_record['snps_um__Item__r']['snps_um__Weight__c']
            original_order = first_record['AITC_OrderQt__c']

            # Cria a tabela para exibir os dados
            table_data = []
            headers = ["作業オーダー", "工程", "順序", "数量", "ステータス", "作業場所", "工程単価"]
            for record in result['records']:
                process_name = record['snps_um__ProcessName__c']
                process_order_no = int(record['snps_um__ProcessOrderNo__c'])
                status = status_mapping.get(record['snps_um__Status__c'], record['snps_um__Status__c'])
                actual_qty = int(record['snps_um__ActualQt__c'])
                work_place_name = record['snps_um__WorkPlace__r']['Name']  # Extraído de cada registro
                cost_price = record['snps_um__Process__r']['Process_cost__c']
                if cost_price is None:
                    cost_price = 0
                else:
                    cost_price = str(round(cost_price, 2))

                table_data.append([
                    record['Name'],  # 作業オーダー
                    process_name,  # 工程
                    process_order_no,  # 順序, sem casas decimais
                    actual_qty,  # 数量, sem casas decimais
                    status,  # ステータス traduzido
                    work_place_name,  # 作業場所
                    cost_price  # 工程単価
                ])

            # Cria o DataFrame
            df = pd.DataFrame(table_data, columns=headers)

            # Filtra o último valor maior que 0 da coluna "数量"
            try:
                last_non_zero_quantity = df[df['数量'] > 0].iloc[-1]  # Filtra e seleciona a última linha
                last_line = int(last_non_zero_quantity.name)
                acum_price = 0
                x = 0
                for record in result['records']:
                    if x <= last_line:
                        acum_price = acum_price + float(record['snps_um__Process__r']['Process_cost__c'])
                        x = x + 1
            except:
                last_non_zero_quantity = None
                acum_price = 0

            ultimo_processo = last_non_zero_quantity['工程']
            ultimo_processo_passo = last_non_zero_quantity['順序']
            ultimo_processo_place = last_non_zero_quantity['作業場所']

            st.write(f"**移行票№**: {prod_order_no}　ー　{original_order}")
            st.write(f"**品目**: {item_name}　**ランク**: {rank}　**完了工程**:({ultimo_processo_passo})　{ultimo_processo}　=>　{ultimo_processo_place}")

            # Aplica formatação condicional
            def highlight_zero_quantity(row):
                return ['background-color: lightgreen' if row['数量'] != 0 else '' for _ in row]


            # Aplica a formatação ao DataFrame e exibe a tabela no Streamlit
            styled_df = df.style.apply(highlight_zero_quantity, axis=1)
            with st.popover("製造オーダー明細"):
                st.dataframe(styled_df)
                st.text(f"工程終了までの単価:  　{str(round(acum_price, 3))}")

        else:
            st.warning("入力されたコードに対して、レコードが見つかりませんでした。")  # Aviso traduzido
            last_non_zero_quantity = None  # Caso não encontre, não retorna uma linha
    except Exception as e:
        st.error(f"Salesforceへの問い合わせでエラーが発生しました: {str(e)}")  # Erro traduzido
        last_non_zero_quantity = None
else:
    last_non_zero_quantity = None

# Campo de entrada para a quantidade (texto), preenchido com o último valor maior que 0
quantidade_input_id = get_key("quantidade_input")
quantidade = st.text_input(
    "数量:", max_chars=10,
    value=str(last_non_zero_quantity['数量']) if last_non_zero_quantity is not None else "0",
    key=quantidade_input_id
)

# Campo de entrada para o código do responsável (texto)
codigo_responsavel_input_id = get_key("codigo_responsavel_input")
codigo_responsavel = st.text_input(
    "担当者コード",  # Label alterado
    key=codigo_responsavel_input_id
)

# Verificação se todos os campos estão preenchidos
botao_confirmar_ativado = st.session_state.botao_confirmar_ativo and codigo_input and quantidade and codigo_responsavel

# Função para salvar os dados em um arquivo Excel
def salvar_dados_excel(codigo, quantidade, codigo_responsavel, last_non_zero_quantity, cost_price):
    # Formata o nome do arquivo com a data atual
    nome_aba  = datetime.now(jst).strftime("%Y%m%d")
    spreadsheet = client.open("棚卸_記録")
    try:
        worksheet = spreadsheet.worksheet(nome_aba)
        valores_coluna = worksheet.col_values(2)
        if codigo_formatado in valores_coluna:
            worksheet = spreadsheet.worksheet(nome_aba)
            linha_index = valores_coluna.index(codigo_formatado) + 1
            valores_linha = worksheet.row_values(linha_index)
            proxima_celula_index = len([cel for cel in valores_linha if cel.strip()]) + 1
            worksheet.update_cell(linha_index, proxima_celula_index,
                                datetime.now(jst).strftime("%Y-%m-%d %H:%M:%S"))  # Horário
            worksheet.update_cell(linha_index, proxima_celula_index + 1, quantidade)  # Quantidade
            worksheet.update_cell(linha_index, proxima_celula_index + 2, codigo_responsavel)  # Código do Responsável
        else:
            worksheet.append_row([datetime.now(jst).strftime("%Y-%m-%d %H:%M:%S"),
                                codigo_formatado,
                                int(quantidade),
                                int(codigo_responsavel),
                                item_name, last_non_zero_quantity.get('工程', ''),
                                int(last_non_zero_quantity.get('順序', '')),
                                last_non_zero_quantity.get('作業場所', ''),
                                cost_price])
    except:
        worksheet1 = spreadsheet.worksheet("Sheet1")
        nova_aba = spreadsheet.add_worksheet(title=nome_aba, rows="1000", cols="20")
        worksheet2 = spreadsheet.worksheet(nome_aba)
        valores_linha1 = worksheet1.row_values(1)
        cell_list = worksheet2.range(1, 1, 1, len(valores_linha1))
        for i, cell in enumerate(cell_list):
            cell.value = valores_linha1[i]
        worksheet2.update_cells(cell_list)

        worksheet2.append_row([datetime.now(jst).strftime("%Y-%m-%d %H:%M:%S"),
                              codigo_formatado,
                              int(quantidade),
                              int(codigo_responsavel),
                              item_name, last_non_zero_quantity.get('工程', ''),
                              int(last_non_zero_quantity.get('順序', '')),
                              last_non_zero_quantity.get('作業場所', ''),
                              cost_price])

# Botão de confirmação da entrada de dados
if st.button("データ登録", disabled=not botao_confirmar_ativado, type="primary"):  # Texto do botão alterado
    try:
        botao_confirmar_ativado = True
        # Salva os dados no arquivo Excel
        salvar_dados_excel(codigo_input, quantidade, codigo_responsavel, last_non_zero_quantity, acum_price)
        st.success("データが正常に確認されました！")  # Mensagem de sucesso traduzida
        st.write(f"移行票№: {codigo_formatado} / {item_name}")  # Código formatado e label atualizado
        st.write(f"数量: {quantidade}     担当者コード: {codigo_responsavel}")  # Label atualizado
    except:
        st.write(f"生産が開始されていないため。移行票№: {codigo_formatado}　は登録されません。")  # Nao ha valores maiores que 0

    # Desabilita o botão de confirmação até uma nova entrada ser feita
    st.session_state.botao_confirmar_ativo = False

google_sheet_state = True

lista_dados = lista_produtos()
total_prodorder = lista_dados[3]
total_prodorder_check = lista_dados[4]
st.warning(f"移行票 {total_prodorder}件(登録済み)　再確認 {total_prodorder_check}件")

col1, col2, col3 = st.columns(3)

with col2:
    with st.popover("再確認待ち"):
        if len(lista_dados[1]) > 0:
            st.dataframe(lista_dados[1].iloc[:, :9])
        else:
            st.warning("空")
with col3:
    with st.popover("現在棚卸詳細"):
        st.dataframe(lista_dados[0])

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("Google Sheet 保存", disabled=google_sheet_state):
        spreadsheet = client.open("アイテック_棚卸").sheet1
        set_with_dataframe(spreadsheet, lista_dados[0])

# Reativa o botão de confirmação quando o usuário começar a digitar em qualquer campo
if not st.session_state.botao_confirmar_ativo:
    st.session_state.botao_confirmar_ativo = True
