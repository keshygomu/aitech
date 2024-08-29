import streamlit as st
from streamlit_qrcode_scanner import qrcode_scanner

st.title("QR Code Scanner")

# Função para ler QR code
qr_code = qrcode_scanner(key="qrcode_scanner")

if qr_code:
    st.write(f"QR Code detected: {qr_code}")
else:
    st.write("Nenhum QR Code detectado.")