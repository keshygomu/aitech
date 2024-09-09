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
    st.image('aitech_logo.png', use_column_width=True)

# Inicializar o estado da sessão, se necessário
if "lista_produtos_iguais" not in st.session_state:
    st.session_state["lista_produtos_iguais"] = []

if "codigo_processado" not in st.session_state:
    st.session_state["codigo_processado"] = False


# Função para processar o primeiro código inserido e armazenar os resultados
def processar_codigo(produto_code):
    lista_produtos_iguais = []
    try:
        # Fazer a busca no Salesforce
        result = procura_produto(produto_code)

        if result['totalSize'] > 0:
            Result_Product = result['records'][0]['snps_um__Item__r']['Name']
            result = procura_produto(Result_Product)
            Internal_Product = result['records'][0]['snps_um__Item__r']['Name']
            lista_produtos_iguais.append(Internal_Product)

            # Adicionar os produtos retornados à lista
            for record in result['records']:
                Customer_Product = record['Name']
                lista_produtos_iguais.append(Customer_Product)

            # Salvar a lista de produtos na sessão
            st.session_state["lista_produtos_iguais"] = lista_produtos_iguais

            with main_container:
                st.write("Produtos encontrados:")
                st.write(produto_code)
                for produtos in lista_produtos_iguais:
                    st.write(f"{produtos}")

        else:
            with main_container:
                st.write(f"{produto_code} não consta na lista de produtos, Contacte o Administrador")

    except Exception as e:
        with main_container:
            st.write("Erro: ", e)


# Função para verificar se o código está na lista após a busca
def verificar_codigo(codigo_inserido):
    if codigo_inserido in st.session_state["lista_produtos_iguais"]:
        with main_container:
            st.success("Código inserido está na lista de produtos.")
    else:
        with main_container:
            st.error("Código não encontrado na lista de produtos!")
            # Aqui está o código JS diretamente
            st.markdown("""
                <script>
                navigator.vibrate(200);  // Vibração por 200ms
                var audio = new Audio('https://www.soundjay.com/button/sounds/beep-07.mp3');
                audio.play();
                </script>
                """, unsafe_allow_html=True)


# Função principal para lidar com o código inserido
def handle_input():
    produto_code = st.session_state["Codigo_barras_temp"]

    if not st.session_state["codigo_processado"]:
        # Processar o primeiro código e armazenar a lista de produtos
        processar_codigo(produto_code)
        st.session_state["codigo_processado"] = True  # Marcar como processado
    else:
        # Verificar se o código inserido já existe na lista de produtos
        verificar_codigo(produto_code)

    # Limpar o campo de texto após o processamento
    st.session_state["Codigo_barras_temp"] = ""


# Função para reiniciar o processo
def reiniciar_processo():
    st.session_state["lista_produtos_iguais"] = []  # Limpar a lista de produtos
    st.session_state["codigo_processado"] = False  # Resetar a flag de processamento
    st.write("Processo reiniciado. Insira uma nova série de códigos de barras.")


# Exibir o campo de texto para inserir código
st.text_input("Insira o Codigo de Barras", key="Codigo_barras_temp", on_change=handle_input)

# Botão para reiniciar o processo
if st.button("Reiniciar"):
    reiniciar_processo()
