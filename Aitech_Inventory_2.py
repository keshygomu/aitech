"""
在庫登録アプリ — Streamlit + Salesforce + Firebase
Optimized: single SF auth per run, dept field added, form submit logic fixed.
Updated: when today's record already exists, display the latest Firebase quantity
instead of Salesforce actual quantity.
Updated: also save snps_um__StockPlace__r.Name into Firebase.
"""

import os
import pytz
import requests
import streamlit as st
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime
from streamlit_qrcode_scanner import qrcode_scanner

# ── Constants ────────────────────────────────────────────────────────────────

JST = pytz.timezone("Asia/Tokyo")
FIREBASE_DB_URL = "https://uminventory-4a2a8-default-rtdb.asia-southeast1.firebasedatabase.app/"


def now_jst() -> datetime:
    return datetime.now(JST)


def inventory_key() -> str:
    """Firebase root node = today's date in JST (YYYYMMDD)."""
    return now_jst().strftime("%Y%m%d")


# ── Secrets ──────────────────────────────────────────────────────────────────

def load_secrets() -> dict:
    try:
        if os.path.exists(".streamlit/secrets.toml"):
            import toml
            return toml.load(".streamlit/secrets.toml")
        return dict(st.secrets)
    except Exception as e:
        st.error(f"認証情報の読み込みエラー: {e}")
        st.stop()


secrets = load_secrets()


# ── Firebase init (once per process) ─────────────────────────────────────────

def init_firebase():
    if firebase_admin._apps:
        return
    if "firebase" not in secrets:
        st.error("secretsに「firebase」キーが見つかりません！")
        st.stop()

    fb = dict(secrets["firebase"])
    required = [
        "type", "project_id", "private_key_id", "private_key",
        "client_email", "client_id", "auth_uri", "token_uri",
        "auth_provider_x509_cert_url", "client_x509_cert_url",
    ]
    missing = [k for k in required if not fb.get(k)]
    if missing:
        st.error(f"firebase_secretsに必須キーが欠けています: {missing}")
        st.stop()

    if isinstance(fb["private_key"], str):
        fb["private_key"] = fb["private_key"].replace("\\n", "\n")
    else:
        st.error("「private_key」は有効な文字列ではありません！")
        st.stop()

    cred = credentials.Certificate(fb)
    firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_URL})


init_firebase()


# ── Salesforce auth (cached per session) ─────────────────────────────────────

@st.cache_resource(ttl=3500)
def get_sf_session():
    """
    Authenticates once and caches the access token for ~1 hour.
    Returns (access_token, instance_url).
    """
    auth_url = f"{secrets['DOMAIN']}/services/oauth2/token"
    payload = {
        "grant_type": "password",
        "client_id": secrets["CONSUMER_KEY"],
        "client_secret": secrets["CONSUMER_SECRET"],
        "username": secrets["USERNAME"],
        "password": secrets["PASSWORD"],
    }
    try:
        r = requests.post(auth_url, data=payload, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data["access_token"], data["instance_url"]
    except Exception as e:
        st.error(f"Salesforce認証エラー: {e}")
        st.stop()


def sf_query(soql: str) -> list:
    """Execute a SOQL query and return the records list."""
    token, instance_url = get_sf_session()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = f"{instance_url}/services/data/v59.0/query"
    try:
        r = requests.get(url, headers=headers, params={"q": soql}, timeout=15)
        r.raise_for_status()
        return r.json().get("records", [])
    except Exception as e:
        st.error(f"Salesforceクエリエラー: {e}")
        return []


# ── Salesforce queries ───────────────────────────────────────────────────────

def fetch_work_orders(production_order: str, process_order: int | None = None) -> list:
    """
    Fetch WorkOrders for a given ProdOrder name.
    Includes 部門名 (snps_um__Dept__r.Name) directly from WorkOrder.
    """
    soql = f"""
        SELECT Id, Name,
               snps_um__ProcessName__c,
               snps_um__ActualQt__c,
               snps_um__Item__r.Id,
               snps_um__Item__r.Name,
               snps_um__ProcessOrderNo__c,
               snps_um__ProdOrder__r.Id,
               snps_um__ProdOrder__r.Name,
               snps_um__Status__c,
               snps_um__WorkPlace__r.Id,
               snps_um__WorkPlace__r.Name,
               snps_um__StockPlace__r.Name,
               snps_um__Item__c,
               snps_um__Process__r.AITC_Acumulated_Price__c,
               snps_um__Dept__r.Name,
               AITC_OrderQt__c,
               snps_um__EndDateTime__c
        FROM snps_um__WorkOrder__c
        WHERE snps_um__ProdOrder__r.Name = '{production_order}'
    """
    if process_order is not None:
        soql += f" AND snps_um__ProcessOrderNo__c = {process_order}"
    soql += " ORDER BY snps_um__ProcessOrderNo__c DESC"
    return sf_query(soql)


def fetch_materials(item_id: str) -> dict:
    """
    Returns dict with keys: material, weight, payment_type.
    Returns empty dict if no material found.
    """
    records = sf_query(f"""
        SELECT snps_um__ChildItem__r.Name,
               snps_um__AddQt__c,
               snps_um__ChildItem__r.AITC_ProcessPattern__c
        FROM snps_um__Composition2__c
        WHERE snps_um__ParentItem2__c = '{item_id}'
    """)
    if not records:
        return {}

    first = records[0]
    material_name = first["snps_um__ChildItem__r"]["Name"]
    weight = first["snps_um__AddQt__c"]
    pattern = first["snps_um__ChildItem__r"]["AITC_ProcessPattern__c"]

    payment_type = ""
    if pattern:
        pay_records = sf_query(f"""
            SELECT snps_um__PaidProvideDiv__c
            FROM snps_um__Process__c
            WHERE snps_um__ProcessPattern__c = '{pattern}'
        """)
        if pay_records:
            raw = pay_records[0].get("snps_um__PaidProvideDiv__c", "")
            payment_type = "有償支給" if raw == "Paid" else "無償支給"

    return {"material": material_name, "weight": weight, "payment_type": payment_type}


def extract_work_order_fields(record: dict) -> dict:
    """Normalize a WorkOrder record into a flat dict."""
    return {
        "actual_qty": int(record.get("snps_um__ActualQt__c") or 0),
        "process_order_no": int(record.get("snps_um__ProcessOrderNo__c") or 0),
        "work_place": (record.get("snps_um__WorkPlace__r") or {}).get("Name", ""),
        "stock_place": (record.get("snps_um__StockPlace__r") or {}).get("Name", ""),
        "cumulative_cost": float(
            (record.get("snps_um__Process__r") or {}).get("AITC_Acumulated_Price__c") or 0.0
        ),
        "process_name": record.get("snps_um__ProcessName__c", ""),
        "product_code": (record.get("snps_um__Item__r") or {}).get("Name", "N/A"),
        "item_id": record.get("snps_um__Item__c", ""),
        "dept_name": (record.get("snps_um__Dept__r") or {}).get("Name", ""),
    }


# ── Firebase helpers ─────────────────────────────────────────────────────────

def firebase_ref(path: str = ""):
    root = inventory_key()
    return db.reference(f"{root}/{path}" if path else root)


def find_record_for_today(production_order: str) -> tuple[str | None, dict | None]:
    """
    Returns (firebase_key, record_data) if a record exists today for this PO.
    Returns (None, None) otherwise.
    """
    today = now_jst().strftime("%Y-%m-%d")
    records = firebase_ref().order_by_child("production_order").equal_to(production_order).get()
    if not records:
        return None, None
    for key, value in records.items():
        record_date = value.get("datetime", "").split()[0]
        if record_date == today:
            return key, value
    return None, None


def firebase_push(data: dict) -> str:
    new_record = firebase_ref().push(data)
    return new_record.key


def firebase_update(record_key: str, data: dict):
    firebase_ref(record_key).update(data)


def firebase_append(record_key: str, new_data: dict):
    """
    Appends a new numbered entry to an existing record
    (datetime01, owner01, quantity01, process_order01, etc.)
    """
    current = firebase_ref(record_key).get() or {}
    existing_count = sum(
        1 for k in current if k.startswith("datetime") and k != "datetime"
    )
    idx = str(existing_count + 1).zfill(2)
    firebase_ref(record_key).update({
        f"datetime{idx}": new_data["datetime"],
        f"owner{idx}": new_data["owner"],
        f"quantity{idx}": new_data["quantity"],
        f"process_order{idx}": new_data["process_order"],
    })


def get_latest_firebase_quantity(record: dict | None) -> int:
    """
    Returns the latest quantity recorded in Firebase.
    Priority:
      highest quantityNN
      fallback to quantity
    """
    if not record:
        return 0

    latest_idx = -1
    latest_qty = None

    for k, v in record.items():
        if k == "quantity":
            continue
        if k.startswith("quantity"):
            suffix = k.replace("quantity", "")
            if suffix.isdigit():
                idx = int(suffix)
                if idx > latest_idx:
                    latest_idx = idx
                    latest_qty = v

    if latest_qty is not None:
        try:
            return int(latest_qty or 0)
        except Exception:
            return 0

    try:
        return int(record.get("quantity", 0) or 0)
    except Exception:
        return 0


# ── Session state init ───────────────────────────────────────────────────────

def init_session():
    defaults = {
        "owner": "",
        "reset_form": False,
        "registered": False,
        "was_update": False,
        "show_success": False,
        "success_data": {},
        "current_process_order": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_session()

# ── UI ───────────────────────────────────────────────────────────────────────








# ─────────────────────────────────────────────────────────────────────────────
# QR SCANNER — Streamlit Components V2 + ZXing
# Compatível com iPhone / Safari
# ─────────────────────────────────────────────────────────────────────────────

QR_SCANNER_HTML = """
<div class="qr-wrapper">

    <div class="qr-title">
        📷 移行票 QRコード
    </div>

    <div class="video-container">

        <video
            id="qr-video"
            autoplay
            muted
            playsinline
        ></video>

        <div class="scan-frame">
            <div class="corner tl"></div>
            <div class="corner tr"></div>
            <div class="corner bl"></div>
            <div class="corner br"></div>

            <div class="scan-line"></div>
        </div>

    </div>

    <div id="qr-status" class="status">
        カメラを起動しています...
    </div>

    <div class="button-row">

        <button id="start-camera" type="button">
            📷 カメラ開始
        </button>

        <button id="stop-camera" type="button">
            ⏹ カメラ停止
        </button>

    </div>

</div>
"""


QR_SCANNER_CSS = """
.qr-wrapper {
    width: 100%;
    font-family: var(--st-font);
}


/* ─────────────────────────────────────────────
   TITLE
───────────────────────────────────────────── */

.qr-title {
    font-size: 18px;
    font-weight: 700;
    text-align: center;
    margin-bottom: 8px;
}


/* ─────────────────────────────────────────────
   VIDEO
───────────────────────────────────────────── */

.video-container {
    position: relative;

    width: 100%;

    overflow: hidden;

    border-radius: 14px;

    background: #000;
}


#qr-video {
    display: block;

    width: 100%;

    height: auto;

    min-height: 260px;

    max-height: 430px;

    object-fit: cover;

    background: #000;
}


/* ─────────────────────────────────────────────
   SCAN AREA
───────────────────────────────────────────── */

.scan-frame {

    position: absolute;

    width: 68%;

    aspect-ratio: 1 / 1;

    max-height: 80%;

    left: 50%;
    top: 50%;

    transform:
        translate(-50%, -50%);

    pointer-events: none;
}


.corner {

    position: absolute;

    width: 35px;
    height: 35px;
}


.tl {

    top: 0;
    left: 0;

    border-top:
        4px solid #00ff88;

    border-left:
        4px solid #00ff88;
}


.tr {

    top: 0;
    right: 0;

    border-top:
        4px solid #00ff88;

    border-right:
        4px solid #00ff88;
}


.bl {

    bottom: 0;
    left: 0;

    border-bottom:
        4px solid #00ff88;

    border-left:
        4px solid #00ff88;
}


.br {

    bottom: 0;
    right: 0;

    border-bottom:
        4px solid #00ff88;

    border-right:
        4px solid #00ff88;
}


/* ─────────────────────────────────────────────
   ANIMATED SCAN LINE
───────────────────────────────────────────── */

.scan-line {

    position: absolute;

    width: 100%;

    height: 2px;

    background: #00ff88;

    box-shadow:
        0 0 8px #00ff88;

    animation:
        scan-animation
        2s
        linear
        infinite;
}


@keyframes scan-animation {

    0% {
        top: 0%;
    }

    50% {
        top: 100%;
    }

    100% {
        top: 0%;
    }
}


/* ─────────────────────────────────────────────
   STATUS
───────────────────────────────────────────── */

.status {

    margin-top: 8px;

    padding: 9px;

    text-align: center;

    border-radius: 8px;

    background:
        rgba(128,128,128,0.15);

    font-size: 14px;
}


/* ─────────────────────────────────────────────
   BUTTONS
───────────────────────────────────────────── */

.button-row {

    display: flex;

    gap: 8px;

    margin-top: 8px;
}


.button-row button {

    flex: 1;

    min-height: 46px;

    border: none;

    border-radius: 9px;

    font-size: 15px;

    font-weight: 600;

    cursor: pointer;
}


#start-camera {

    background: #00875a;

    color: white;
}


#stop-camera {

    background: #555;

    color: white;
}
"""


QR_SCANNER_JS = """
export default async function(component) {

    const {
        parentElement,
        setTriggerValue
    } = component;


    const video =
        parentElement.querySelector("#qr-video");

    const status =
        parentElement.querySelector("#qr-status");

    const startButton =
        parentElement.querySelector("#start-camera");

    const stopButton =
        parentElement.querySelector("#stop-camera");


    // ============================================================
    // Prevent duplicate initialization
    // ============================================================

    if (video._scannerInitialized) {
        return;
    }

    video._scannerInitialized = true;


    video._controls = null;
    video._reader = null;

    video._lastCode = "";
    video._lastReadTime = 0;

    video._running = false;


    function setStatus(message) {

        status.textContent = message;
    }


    // ============================================================
    // Load ZXing
    // ============================================================

    async function loadZXing() {

        setStatus(
            "QRライブラリを読み込んでいます..."
        );


        try {

            const ZXing =
                await import(
                    "https://cdn.jsdelivr.net/npm/@zxing/browser@0.2.1/+esm"
                );


            return ZXing;

        }

        catch (error) {

            console.error(
                "ZXing load error:",
                error
            );


            setStatus(
                "QRライブラリの読み込みに失敗しました"
            );


            throw error;
        }
    }


    // ============================================================
    // Stop camera
    // ============================================================

    function stopCamera() {

        video._running = false;


        // Stop ZXing scanner

        if (video._controls) {

            try {

                video._controls.stop();

            }

            catch (error) {

                console.log(
                    "ZXing stop:",
                    error
                );
            }

            video._controls = null;
        }


        // Stop camera tracks as extra safety

        if (video.srcObject) {

            try {

                const tracks =
                    video.srcObject.getTracks();

                tracks.forEach(
                    track => track.stop()
                );

            }

            catch (error) {

                console.log(
                    "Camera stop:",
                    error
                );
            }

        }


        video.srcObject = null;


        setStatus(
            "カメラ停止中"
        );
    }


    // ============================================================
    // QR detected
    // ============================================================

    function qrDetected(text) {

        if (!text) {
            return;
        }


        const value =
            String(text).trim();


        if (!value) {
            return;
        }


        const now =
            Date.now();


        // --------------------------------------------------------
        // Prevent the same QR from being sent repeatedly
        // --------------------------------------------------------

        if (
            value === video._lastCode &&
            now - video._lastReadTime < 4000
        ) {

            return;
        }


        video._lastCode =
            value;

        video._lastReadTime =
            now;


        // --------------------------------------------------------
        // Visual feedback
        // --------------------------------------------------------

        setStatus(
            "✓ 読み取り成功: " + value
        );


        // --------------------------------------------------------
        // Vibration
        // --------------------------------------------------------

        if (
            navigator.vibrate
        ) {

            try {

                navigator.vibrate(100);

            }

            catch (error) {

                // Safari may ignore vibration.
            }
        }


        // --------------------------------------------------------
        // Send QR to Streamlit / Python
        // --------------------------------------------------------

        setTriggerValue(
            "qr_code",
            value
        );
    }


    // ============================================================
    // Start camera + ZXing
    // ============================================================

    async function startCamera() {

        if (video._running) {

            return;
        }


        video._running = true;


        setStatus(
            "カメラを起動しています..."
        );


        try {

            // ----------------------------------------------------
            // Load ZXing
            // ----------------------------------------------------

            const ZXing =
                await loadZXing();


            // ----------------------------------------------------
            // QR-only reader
            // ----------------------------------------------------

            const reader =
                new ZXing.BrowserQRCodeReader(
                    undefined,
                    {
                        delayBetweenScanAttempts: 200,
                        delayBetweenScanSuccess: 800
                    }
                );


            video._reader =
                reader;


            // ----------------------------------------------------
            // Camera constraints
            //
            // facingMode environment asks iPhone for rear camera.
            // ----------------------------------------------------

            const constraints = {

                audio: false,

                video: {

                    facingMode: {
                        ideal: "environment"
                    },

                    width: {
                        ideal: 1280
                    },

                    height: {
                        ideal: 720
                    }
                }
            };


            setStatus(
                "カメラを準備しています..."
            );


            // ----------------------------------------------------
            // Continuous QR scanning
            // ----------------------------------------------------

            const controls =
                await reader.decodeFromConstraints(

                    constraints,

                    video,

                    (result, error, controls) => {

                        if (!video._running) {

                            return;
                        }


                        // QR FOUND

                        if (result) {

                            const text =
                                result.getText();

                            qrDetected(
                                text
                            );
                        }


                        // Most ZXing errors simply mean:
                        // "QR not found in this frame".
                        //
                        // Therefore we intentionally don't
                        // display them to the operator.
                    }
                );


            video._controls =
                controls;


            setStatus(
                "QRコードを枠内に合わせてください"
            );


        }

        catch (error) {

            console.error(
                "Camera / ZXing error:",
                error
            );


            video._running =
                false;


            // ----------------------------------------------------
            // Permission error
            // ----------------------------------------------------

            if (
                error &&
                error.name === "NotAllowedError"
            ) {

                setStatus(
                    "カメラの使用が許可されていません。Safariのカメラ設定を確認してください。"
                );

            }


            // ----------------------------------------------------
            // No camera
            // ----------------------------------------------------

            else if (
                error &&
                error.name === "NotFoundError"
            ) {

                setStatus(
                    "カメラが見つかりません"
                );

            }


            // ----------------------------------------------------
            // Generic error
            // ----------------------------------------------------

            else {

                const message =
                    error && error.message
                        ? error.message
                        : String(error);


                setStatus(
                    "カメラ起動エラー: " +
                    message
                );
            }
        }
    }


    // ============================================================
    // Buttons
    // ============================================================

    startButton.onclick =
        function() {

            startCamera();
        };


    stopButton.onclick =
        function() {

            stopCamera();
        };


    // ============================================================
    // Automatically start camera
    // ============================================================

    startCamera();
}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Register Streamlit V2 component
# ─────────────────────────────────────────────────────────────────────────────

qr_scanner_component = st.components.v2.component(

    name="aitech_qr_scanner_zxing",

    html=QR_SCANNER_HTML,

    css=QR_SCANNER_CSS,

    js=QR_SCANNER_JS,
)












st.image("aitech_logo_B.png", use_container_width=True)

# Step 1 — operator code
if not st.session_state["owner"]:
    st.session_state["owner"] = st.text_input(
        "担当者コードを入力してください:", key="owner_input"
    )
    if not st.session_state["owner"]:
        st.stop()

# Step 2 — success screen
if st.session_state["show_success"]:
    msg = "登録が正常に更新されました！" if st.session_state["was_update"] else "登録が正常に完了しました！"
    st.success(msg)
    d = st.session_state["success_data"]
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"担当者: {st.session_state['owner']}")
        st.write(f"移行票: {d.get('production_order', '')}")
        st.write(f"工程名: {d.get('process_name', '')}")
        st.write(f"部門名: {d.get('dept_name', '')}")
    with col2:
        st.write(f"作業場所: {d.get('work_place', '')}")
        st.write(f"在庫場所: {d.get('stock_place', '')}")
        st.write(f"報告数量: {d.get('quantity', 0)}")
        st.write(f"工程順序: {d.get('process_order', '')}")

    if st.button("新規登録", key="btn_new"):
        for k in ("reset_form", "registered", "was_update", "show_success",
                  "success_data", "current_process_order"):
            st.session_state[k] = False if isinstance(st.session_state[k], bool) else (
                None if k == "current_process_order" else {}
            )
        st.rerun()
    st.stop()





# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — QR / manual input
# ─────────────────────────────────────────────────────────────────────────────

col1, col2 = st.columns([1.4, 1])

with col1:

    qr_result = qr_scanner_component(
        key="qr_scanner_zxing",
        on_qr_code_change=lambda: None,
    )

    qr_code = qr_result.qr_code


with col2:

    st.subheader("手動入力")

    input_key = (
        "manual_reset"
        if st.session_state["reset_form"]
        else "manual_normal"
    )

    input_manual = st.text_input(
        "移行票番号を入力してください:",
        value="",
        key=input_key,
    )


production_order = ""
is_split = False


# ── QR ────────────────────────────────────────────────────────────────────────

if qr_code:

    scanned = str(qr_code).strip()

    if scanned.upper().startswith("PO-"):

        production_order = scanned.upper()

    else:

        numeric = "".join(
            c for c in scanned
            if c.isdigit()
        )

        if numeric:

            production_order = (
                f"PO-{numeric.zfill(6)}"
            )

        else:

            production_order = scanned

    st.session_state["reset_form"] = False


# ── Manual ────────────────────────────────────────────────────────────────────

elif input_manual:

    manual = input_manual.strip()

    if manual.upper().startswith("PO-"):

        production_order = manual.upper()

    else:

        production_order = (
            f"PO-{manual.zfill(6)}"
        )






# Step 4 — Main form
if production_order and not st.session_state["registered"]:

    work_orders = fetch_work_orders(production_order)
    if not work_orders:
        st.warning("この移行票に対応する記録が見つかりませんでした。")
        st.stop()

    done_orders = [r for r in work_orders if r.get("snps_um__Status__c") == "Done"]
    if not done_orders:
        st.warning("この移行票には完了済みの工程がありません。")
        st.stop()

    # Default to most recent Done record
    latest = done_orders[0]
    fields = extract_work_order_fields(latest)

    # Fetch material info once
    mat_info = {}
    if fields["item_id"]:
        try:
            mat_info = fetch_materials(fields["item_id"])
        except Exception as e:
            st.warning(f"材料情報の取得をスキップしました: {e}")

    # Check if a record already exists today
    today_key, today_record = find_record_for_today(production_order)
    already_registered = today_key is not None

    firebase_qty_today = (
        get_latest_firebase_quantity(today_record) if already_registered else None
    )
    display_qty = firebase_qty_today if already_registered else fields["actual_qty"]

    # ── Action buttons OUTSIDE the form (avoids Streamlit ambiguity) ─────────
    st.subheader(f"在庫登録 — {production_order}")
    st.subheader(fields["product_code"])

    if already_registered:
        st.markdown(
            '<p style="color:yellow;font-weight:bold;font-size:24px;text-align:center;">'
            "登　録　済　み　！！</p>",
            unsafe_allow_html=True,
        )
        st.info(f"本日のFirebase登録数量: {firebase_qty_today}")

    # ── Form (data entry only, no submit ambiguity) ──────────────────────────
    with st.form("form_inventory"):
        qty_input = st.number_input(
            "最後の完了工程の登録数",
            value=int(display_qty),
            step=1,
            key="qty_form",
        )
        process_order_input = st.number_input(
            "工程順序 (10〜999)",
            min_value=10,
            max_value=999,
            value=fields["process_order_no"],
            step=10,
            key="po_form",
        )

        # Re-fetch if process order changed
        if st.session_state["current_process_order"] != process_order_input:
            st.session_state["current_process_order"] = process_order_input
            if process_order_input != fields["process_order_no"]:
                updated = fetch_work_orders(production_order, process_order_input)
                if updated:
                    fields = extract_work_order_fields(updated[0])
                else:
                    st.warning(f"工程順序 {process_order_input} に対応する記録が見つかりませんでした。")
                    fields["work_place"] = ""
                    fields["stock_place"] = ""
                    fields["cumulative_cost"] = 0.0
                    fields["process_name"] = ""
                    fields["dept_name"] = ""

        col_a, col_b = st.columns(2)
        with col_a:
            st.write(f"作業場所: {fields['work_place']}")
            st.write(f"在庫場所: {fields['stock_place']}")
            st.write(f"部門名: {fields['dept_name']}")
            division_cb = st.checkbox("分割")
        with col_b:
            st.write(f"工程名: {fields['process_name']}")

        submit_btn = st.form_submit_button("登録")

    # ── Process submission ───────────────────────────────────────────────────
    action = None
    if submit_btn:
        action = "register"

    if action and fields["work_place"]:
        po_name = production_order + ("-1" if division_cb else "")
        dt_str = now_jst().strftime("%Y-%m-%d %H:%M:%S")

        data_to_save = {
            "datetime": dt_str,
            "production_order": po_name,
            "quantity": int(qty_input),
            "owner": st.session_state["owner"],
            "product_code": fields["product_code"],
            "process_name": fields["process_name"],
            "process_order": int(process_order_input),
            "work_place": fields["work_place"],
            "stock_place": fields["stock_place"],
            "dept_name": fields["dept_name"],
            "cumulative_cost": fields["cumulative_cost"],
            "material": mat_info.get("material", ""),
            "material_provision_type": mat_info.get("payment_type", ""),
            "material_weight": mat_info.get("weight", 0),
        }

        was_update = False
        existing_key, _ = find_record_for_today(po_name)

        if existing_key:
            firebase_append(existing_key, data_to_save)
            was_update = True
        else:
            firebase_push(data_to_save)

        st.session_state.update({
            "registered": True,
            "was_update": was_update,
            "show_success": True,
            "success_data": {
                "production_order": po_name,
                "product_code": fields["product_code"],
                "work_place": fields["work_place"],
                "stock_place": fields["stock_place"],
                "process_name": fields["process_name"],
                "dept_name": fields["dept_name"],
                "quantity": int(qty_input),
                "process_order": int(process_order_input),
            },
        })
        st.rerun()

    elif action and not fields["work_place"]:
        st.error("作業場所が取得できませんでした。工程順序を確認してください。")
