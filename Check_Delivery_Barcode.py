import streamlit as st
from streamlit_qrcode_scanner import qrcode_scanner
import pandas as pd
from simple_salesforce import Salesforce
import os
import pytz
from datetime import datetime
import requests
import toml

# Definir o fuso horário do Japão (JST)
jst = pytz.timezone('Asia/Tokyo')

# Função para carregar credenciais
def carregar_credenciais():
    if os.path.exists('secrets.toml'):
        secrets = toml.load('secrets.toml')  # Executando localmente
    else:
        secrets = st.secrets  # Executando no Streamlit Cloud
    return secrets

# Função para autenticar Salesforce
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

# Função para procurar produtos no Salesforce
def procura_produto(produto_code):
    sf = authenticate_salesforce()
    query = f"""
    SELECT Name, snps_um__Item__r.Name,
    snps_um__Customer__c 
    FROM snps_um__CustomerItem__c 
    WHERE Name = '{produto_code}' or snps_um__Item__r.Name='{produto_code}'
    """
    result = sf.query(query)
    return result

# Carregar as credenciais
secrets = carregar_credenciais()

# Contêiner para imagem
top_container = st.container()
main_container = st.container()

# Fixar a imagem no topo
with top_container:
    st.image('aitech_logo_barcode.png', use_column_width=True)

# Inicializar o estado da sessão, se necessário
if "lista_produtos_iguais" not in st.session_state:
    st.session_state["lista_produtos_iguais"] = []

if "codigo_processado" not in st.session_state:
    st.session_state["codigo_processado"] = False

if "Codigo_barras_temp" not in st.session_state:
    st.session_state["Codigo_barras_temp"] = ""

# Função para processar o primeiro código inserido e armazenar os resultados
def processar_codigo(produto_code):
    lista_produtos_iguais = []
    try:
        result = procura_produto(produto_code)

        if result['totalSize'] > 0:
            Result_Product = result['records'][0]['snps_um__Item__r']['Name']
            result = procura_produto(Result_Product)
            Internal_Product = result['records'][0]['snps_um__Item__r']['Name']
            lista_produtos_iguais.append(Internal_Product)

            for record in result['records']:
                Customer_Product = record['Name']
                lista_produtos_iguais.append(Customer_Product)

            st.session_state["lista_produtos_iguais"] = lista_produtos_iguais

            with main_container:
                st.write(f"**バーコード**:   {produto_code}")

        else:
            with main_container:
                st.write(f"{produto_code} 品番リストにありません。管理者に連絡してください")

    except Exception as e:
        with main_container:
            st.write("Erro: ", e)

# Função para verificar se o código está na lista após a busca
def verificar_codigo(codigo_inserido):
    if codigo_inserido in st.session_state["lista_produtos_iguais"]:
        with main_container:
            st.image('OK.png', use_column_width=True)
    else:
        with main_container:
            st.image('NG.png', use_column_width=True)
            st.audio("mixkit-critical-alarm-1004.wav", format="audio/wav", autoplay=True)

# Função principal para lidar com o código inserido
def handle_input():
    produto_code = st.session_state["Codigo_barras_temp"]

    if not st.session_state["codigo_processado"]:
        processar_codigo(produto_code)
        st.session_state["codigo_processado"] = True
    else:
        verificar_codigo(produto_code)

    # Não modificar o session_state diretamente após o campo ser instanciado
    st.session_state["Codigo_barras_temp"] = ""  # Limpar o campo de entrada

# Função para reiniciar o processo
def reiniciar_processo():
    st.session_state["lista_produtos_iguais"] = []
    st.session_state["codigo_processado"] = False
    # Não tentar modificar o estado do campo instanciado
    st.session_state["Codigo_barras_temp"] = ""

# Exibir o campo de texto para inserir código
st.text_input("バーコードを入力してください", key="Codigo_barras_temp", on_change=handle_input)

# Botão para reiniciar o processo
if st.button("クリア"):
    reiniciar_processo()
