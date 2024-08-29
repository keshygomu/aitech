import cv2
import numpy as np
import streamlit as st
from streamlit_webrtc import webrtc_streamer, VideoProcessorBase, RTCConfiguration

# Configuração do RTC (WebRTC)
RTC_CONFIGURATION = RTCConfiguration({"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]})

# Classe para processar vídeo
class VideoProcessor(VideoProcessorBase):
    def __init__(self):
        self.result_text = ""

    def recv(self, frame):
        img = frame.to_ndarray(format="bgr24")
        
        # Detecta e decodifica o QR Code
        qr_decoder = cv2.QRCodeDetector()
        data, points, _ = qr_decoder.detectAndDecode(img)

        if points is not None:
            self.result_text = f"QR Code detected: {data}"
            # Desenha um quadrado ao redor do QR Code detectado
            points = np.int32(points).reshape(-1, 2)
            for i in range(len(points)):
                cv2.line(img, tuple(points[i]), tuple(points[(i + 1) % len(points)]), color=(0, 255, 0), thickness=2)
        else:
            self.result_text = "No QR Code detected"

        return av.VideoFrame.from_ndarray(img, format="bgr24")

    def get_result_text(self):
        return self.result_text

# Interface do Streamlit
st.title("QR Code Detector")

# Inicializa o WebRTC
ctx = webrtc_streamer(
    key="example",
    video_processor_factory=VideoProcessor,
    rtc_configuration=RTC_CONFIGURATION,
    media_stream_constraints={"video": True, "audio": False},
    async_processing=True,
)

# Exibe o resultado do QR Code
if ctx.video_processor:
    result = ctx.video_processor.get_result_text()
    st.write(result)
