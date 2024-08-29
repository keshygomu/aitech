import streamlit as st
import cv2
from streamlit_webrtc import webrtc_streamer, VideoProcessorBase
import numpy as np
from pyzbar.pyzbar import decode

# Classe para processar o vídeo
class QRCodeScanner(VideoProcessorBase):
    def __init__(self):
        self.qr_code = None

    def recv(self, frame):
        img = frame.to_ndarray(format="bgr24")

        # Decodifica o QR Code na imagem capturada
        decoded_objs = decode(img)
        for obj in decoded_objs:
            self.qr_code = obj.data.decode("utf-8")
            # Desenhar um retângulo ao redor do QR Code
            points = obj.polygon
            if len(points) == 4:
                pts = np.array(points, dtype=np.int32)
                pts = pts.reshape((-1, 1, 2))
                cv2.polylines(img, [pts], isClosed=True, color=(0, 255, 0), thickness=3)

        return frame.from_ndarray(img, format="bgr24")

# Função principal do Streamlit
def main():
    st.title("QRCode Scanner com Streamlit")

    # Inicializa o WebRTC
    ctx = webrtc_streamer(key="qrscanner", video_processor_factory=QRCodeScanner)

    # Exibe o QR Code detectado
    if ctx.video_processor:
        qr_code = ctx.video_processor.qr_code
        if qr_code:
            st.success(f"QR Code detectado: {qr_code}")

if __name__ == "__main__":
    main()
