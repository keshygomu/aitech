import streamlit as st
from streamlit_qrcode_scanner import qrcode_scanner
import pandas as pd
from simple_salesforce import Salesforce
import os
import pytz
from datetime import datetime
import requests
import gspread
from google.oauth2.service_account import Credentials
from gspread_dataframe import set_with_dataframe
import toml

st.image('aitech_logo.png', use_column_width=True)

# Inicializa as variáveis no session_state para controlar os valores dos inputs
if "botao_confirmar_ativo" not in st.session_state:
    st.session_state.botao_confirmar_ativo = True

if "webrtc_initialized" not in st.session_state:
    st.session_state.webrtc_initialized = False

# Gera uma chave única para cada campo
def get_key(base):
    return f"{base}_{st.session_state.botao_confirmar_ativo}"

# Campo de entrada para o código (texto)
codigo_input_id = get_key("codigo_input")
codigo_input = st.text_input(
    "移行票番号を入力してください:",  # Label alterado
    key=codigo_input_id
)

codigo_formatado = f"PO-{int(codigo_input):06d}" if codigo_input.isdigit() else None

# Verificação para inicializar o WebRTC apenas uma vez
if not st.session_state.webrtc_initialized:
    qr_code = qrcode_scanner(key="qrcode_scanner")
    st.session_state.webrtc_initialized = True
else:
    qr_code = None

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

# Restante do código permanece o mesmo...
# (Não modificado para foco no aspecto relevante)

# Reativa o botão de confirmação quando o usuário começar a digitar em qualquer campo
if not st.session_state.botao_confirmar_ativo:
    st.session_state.botao_confirmar_ativo = True
