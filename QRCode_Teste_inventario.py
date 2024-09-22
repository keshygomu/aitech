import streamlit as st
from streamlit_qrcode_scanner import qrcode_scanner
import pandas as pd
from simple_salesforce import Salesforce
import os
import pytz
from datetime import datetime
import requests
#from openpyxl import load_workbook, Workbook
import gspread
from google.oauth2.service_account import Credentials
from gspread_dataframe import set_with_dataframe
import toml

st.image('aitech_logo_B.png', use_column_width=True)

# Inicializa as variáveis no session_state para controlar os valores dos inputs
if "botao_confirmar_ativo" not in st.session_state:
    st.session_state.botao_confirmar_ativo = True

# Gera uma chave única para cada campo
def get_key(base):
    return f"{base}_{st.session_state.botao_confirmar_ativo}"

qr_code = qrcode_scanner(key="qrcode_scanner")
if qr_code:
    st.write(f'**QR-コード**:{qr_code}')
    codigo_formatado = qr_code


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

# Formata o código no formato "PO-000000"
df_todos = []
df_filtrado = []
valores_coluna=[]
total_prodorder = 0
total_prodorder_check = 0

def lista_produtos():
    try:
        nome_aba = datetime.now(jst).strftime("%Y%m%d")
        worksheet = client.open("棚卸_記録").worksheet(nome_aba)
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
# Verifica se o arquivo Excel existe e faz a checagem

if qr_code:
    valores_coluna =lista_produtos()[2]
    existe = any(valores_coluna.str.slice(0,9) == qr_code)
    if existe:
        st.warning("登録済")
    else:
        total_prodorder = 0
        total_prodorder_check = 0

    # Realiza a consulta ao Salesforce ao inserir o código
if qr_code:
    try:
        sf = authenticate_salesforce()
        query = f"""
        SELECT Name, snps_um__ProcessName__c, snps_um__ActualQt__c, snps_um__Item__r.Name, 
               snps_um__Item__r.AITC_PrintItemName__c, snps_um__ProcessOrderNo__c, 
               snps_um__ProdOrder__r.Name, snps_um__Status__c, snps_um__WorkPlace__r.Name,
               snps_um__StockPlace__r.Name, snps_um__Item__c, snps_um__Process__r.Process_cost__c, 
               snps_um__Item__r.AITC_ItemRank__c, snps_um__Item__r.snps_um__Weight__c, 
               AITC_OrderQt__c,  snps_um__EndDateTime__c 
        FROM snps_um__WorkOrder__c 
        WHERE snps_um__ProdOrder__r.Name = '{codigo_formatado}'
        """
        result = sf.query(query)

        material = "-"
        pagamento = "-"
        peso = "-"

        if result['totalSize'] > 0:
            father_id = result['records'][0]['snps_um__Item__c']
            query = f"""
                    SELECT 
                    snps_um__ChildItem__c, 
                    snps_um__ChildItem__r.Name,
                    snps_um__AddQt__c, 
                    snps_um__ChildItem__r.AITC_ProcessPattern__c 
                    FROM snps_um__Composition2__c
                    WHERE snps_um__ParentItem2__c = '{father_id}'
                    """
            procura_shikyu1 = sf.query(query)

            if procura_shikyu1['totalSize'] > 0:
                peso = procura_shikyu1['records'][0]['snps_um__AddQt__c']
                kosei = procura_shikyu1['records'][0]['snps_um__ChildItem__r']['AITC_ProcessPattern__c']
                query = f"""
                        SELECT 
                        snps_um__ProvideDivision__c, snps_um__PaidProvideDiv__c,
                        snps_um__Account__r.Name 
                        FROM snps_um__Process__c
                        WHERE snps_um__ProcessPattern__c = '{kosei}'
                        """
                procura_shikyu2 = sf.query(query)
                if procura_shikyu2['totalSize'] > 0:
                    material = procura_shikyu1['records'][0]['snps_um__ChildItem__r']['Name']
                    if procura_shikyu2['records'][0]['snps_um__PaidProvideDiv__c'] == "Paid":
                        pagamento = "有償支給"
                    else:
                        pagamento = "無償支給"

        #print(procura_shikyu2['records'][0]['snps_um__ProvideDivision__c'])
        lista_kotei = []

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
            price = 0
            headers = ["作業オーダー", "工程", "順序", "数量", "ステータス", "作業場所", "工程単価","累積単価","最後完了日"]
            for record in result['records']:
                process_name = record['snps_um__ProcessName__c']
                process_order_no = int(record['snps_um__ProcessOrderNo__c'])
                status = status_mapping.get(record['snps_um__Status__c'], record['snps_um__Status__c'])
                actual_qty = int(record['snps_um__ActualQt__c'])
                work_place_name = record['snps_um__WorkPlace__r']['Name']  # Extraído de cada registro
                cost_price = record['snps_um__Process__r']['Process_cost__c']
                done_date = record['snps_um__EndDateTime__c']
                if cost_price is None:
                    cost_price = 0
                else:
                    price = cost_price + price
                    cost_price = str(round(cost_price, 2))

                if done_date is None:
                    done_date = 0
                else:
                    done_date = datetime.strptime(done_date, "%Y-%m-%dT%H:%M:%S.%f%z")
                    done_date = done_date.strftime("%y/%m/%d")

                lista_kotei.append(f"{process_order_no}:{process_name}:{work_place_name}")

                table_data.append([
                    record['Name'],  # 作業オーダー
                    process_name,  # 工程
                    process_order_no,  # 順序, sem casas decimais
                    actual_qty,  # 数量, sem casas decimais
                    status,  # ステータス traduzido
                    work_place_name,  # 作業場所
                    cost_price,  # 工程単価
                    str(round(price,2)),  #累積単価
                    done_date
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

            last_date_record = ""
            last_done_record = ""
            last_done_index = 0

            try:
                last_done_record = df[df['ステータス'] == "作業完了"].iloc[-1]
                last_done_index = int(last_done_record.name)
                last_date_record = last_done_record["最後完了日"]
                if last_done_record["順序"] != "999":
                    if df["数量"].iloc[last_done_index+1]>0:
                        last_inprod_record = df[df['ステータス'] == "製造中"].iloc[-1]
                        last_done_record["数量"] = str(int(last_done_record['数量'])-int(last_inprod_record["数量"]))
                        #print(last_done_record["数量"])

            except:
                last_done_record = df.iloc[0]

            st.write(f"**移行票№**: {prod_order_no}　ー　{original_order} 　ー　 **最後完了日**:{last_date_record}")

            if not last_done_record is None:
                ultimo_processo = last_done_record['工程']
                ultimo_processo_passo = last_done_record['順序']
                ultimo_processo_place = last_done_record['作業場所']
                st.write(
                    f"**品目**: {item_name}　**ランク**: {rank}　**完了工程**:({ultimo_processo_passo})　{ultimo_processo}　=>　{ultimo_processo_place}")
            else:
                st.write(f"**品目**: {item_name}　**ランク**: {rank}　**完了工程**:(0)")

            # Aplica formatação condicional
            def highlight_zero_quantity(row):
                return ['background-color: green' if row['数量'] != 0 else '' for _ in row]


            # Aplica a formatação ao DataFrame e exibe a tabela no Streamlit
            df_reduzido = df.iloc[:, :-2]
            styled_df = df.style.apply(highlight_zero_quantity, axis=1)
            with st.popover("製造オーダー明細"):
                st.dataframe(styled_df)

        else:
            st.warning("入力されたコードに対して、レコードが見つかりませんでした。")  # Aviso traduzido
            last_done_record = None  # Caso não encontre, não retorna uma linha

        if lista_kotei:
            selecionado = st.selectbox('工程選択:', lista_kotei, index=last_done_index)

    except Exception as e:
        st.error(f"Salesforceへの問い合わせでエラーが発生しました: {str(e)}")  # Erro traduzido
        last_done_record = None

else:
    last_done_record = None

# Campo de entrada para a quantidade (texto), preenchido com o último valor maior que 0
quantidade_input_id = get_key("quantidade_input")
quantidade = st.text_input(
    "数量:", max_chars=10,
    value=str(last_done_record['数量']) if last_done_record is not None else "0",
    key=quantidade_input_id
)

# Campo de entrada para o código do responsável (texto)
codigo_responsavel_input_id = get_key("codigo_responsavel_input")
codigo_responsavel = st.text_input(
    "担当者コード",  # Label alterado
    key=codigo_responsavel_input_id
)

# Verificação se todos os campos estão preenchidos
botao_confirmar_ativado = st.session_state.botao_confirmar_ativo and quantidade and codigo_responsavel and qr_code
# Função para salvar os dados em um arquivo Excel
def salvar_dados_excel(codigo_formatado, quantidade, codigo_responsavel, ordem, ordem_nome, lugar, last_done_record, material, pagamento,peso):
    # Formata o nome do arquivo com a data atual
    nome_aba = datetime.now(jst).strftime("%Y%m%d")
    spreadsheet = client.open("棚卸_記録")
    codigo_reformatado = codigo_formatado + "-" + str(ordem)
    cost_price = float(df.loc[df['順序'] == int(ordem), '累積単価'].values[0])

    try:
        worksheet = spreadsheet.worksheet(nome_aba)
        valores_coluna = worksheet.col_values(2)
        if codigo_reformatado in valores_coluna:
            worksheet = spreadsheet.worksheet(nome_aba)
            linha_index = valores_coluna.index(codigo_reformatado) + 1
            valores_linha = worksheet.row_values(linha_index)
            proxima_celula_index = len([cel for cel in valores_linha if cel.strip()]) + 1
            worksheet.update_cell(linha_index, proxima_celula_index,
                                  datetime.now(jst).strftime("%Y-%m-%d %H:%M:%S"))  # Horário
            worksheet.update_cell(linha_index, proxima_celula_index + 1, quantidade)  # Quantidade
            worksheet.update_cell(linha_index, proxima_celula_index + 2, codigo_responsavel)  # Código do Responsável

        else:
            print(codigo_reformatado, quantidade, codigo_responsavel, ordem, ordem_nome, ordem_local, last_done_record, cost_price,material, pagamento)
            worksheet.append_row([datetime.now(jst).strftime("%Y-%m-%d %H:%M:%S"),
                                  codigo_reformatado,
                                  int(quantidade),
                                  int(codigo_responsavel),
                                  item_name, ordem_nome,
                                  int(ordem),
                                  lugar,
                                  cost_price,
                                  material,
                                  pagamento,
                                  peso])
    except:
        worksheet1 = spreadsheet.worksheet("Sheet1")
        nova_aba = spreadsheet.add_worksheet(title=nome_aba, rows="10000", cols="100")
        worksheet2 = spreadsheet.worksheet(nome_aba)
        valores_linha1 = worksheet1.row_values(1)
        cell_list = worksheet2.range(1, 1, 1, len(valores_linha1))
        for i, cell in enumerate(cell_list):
            cell.value = valores_linha1[i]
        worksheet2.update_cells(cell_list)

        worksheet2.append_row([datetime.now(jst).strftime("%Y-%m-%d %H:%M:%S"),
                               codigo_reformatado,
                               int(quantidade),
                               int(codigo_responsavel),
                               item_name, ordem_nome,
                               int(ordem),
                               lugar,
                               cost_price,
                               material,
                               pagamento,
                               peso])

# Botão de confirmação da entrada de dados
if st.button("データ登録", disabled=not botao_confirmar_ativado, type="primary"):  # Texto do botão alterado
    try:
        botao_confirmar_ativado = True
        # Salva os dados no arquivo Excel
        ordem, ordem_nome, ordem_local = selecionado.split(":")
        salvar_dados_excel(codigo_formatado, quantidade, codigo_responsavel, ordem, ordem_nome, ordem_local,
                           last_done_record, material, pagamento, peso)
        st.success("データが正常に確認されました！")  # Mensagem de sucesso traduzida
        st.write(f"移行票№: {codigo_formatado} / {item_name}")  # Código formatado e label atualizado
        st.write(f"数量: {quantidade}     担当者コード: {codigo_responsavel}")  # Label atualizado

    except Exception as e:
        print("erro do botao apertar:", e)
        st.write(f"移行票№: {codigo_formatado}　は登録されません。")  # Nao ha valores maiores que 0

    # Desabilita o botão de confirmação até uma nova entrada ser feita
    st.session_state.botao_confirmar_ativo = False

google_sheet_state = True

col1, col2, col3 = st.columns(3)

try:
    lista_dados = lista_produtos()
    total_prodorder = lista_dados[3]
    total_prodorder_check = lista_dados[4]
    st.warning(f"移行票 {total_prodorder}件(登録済み)　再確認 {total_prodorder_check}件")

    with col2:
        with st.popover("再確認待ち"):
            if len(lista_dados[1]) > 0:
                st.dataframe(lista_dados[1].iloc[:, :9])
            else:
                st.warning("空")
    with col3:
        with st.popover("現在棚卸詳細"):
            st.dataframe(lista_dados[0])
except Exception as e:
    print(e)
    st.warning("現在、在庫記録はありません。")

with col1:
    if st.button("Google Sheet 保存", disabled=google_sheet_state):
        spreadsheet = client.open("アイテック_棚卸").sheet1
        set_with_dataframe(spreadsheet, lista_dados[0])

# Reativa o botão de confirmação quando o usuário começar a digitar em qualquer campo
if not st.session_state.botao_confirmar_ativo:
    st.session_state.botao_confirmar_ativo = True

