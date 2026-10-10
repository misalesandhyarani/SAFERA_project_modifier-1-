import html
import inspect
import os
import re
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests
import streamlit as st
from streamlit_js_eval import get_geolocation
import folium
from streamlit_folium import st_folium

# ==================================================
# PAGE CONFIGURATION (must be the first Streamlit call)
# ==================================================
st.set_page_config(
    page_title="SAFERA | Women's Safety",
    page_icon="🛡️",
    layout="wide",
)

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
HISTORY_FILE = DATA_DIR / "safety_history.csv"
SOS_FILE = DATA_DIR / "sos_history.csv"
EMAIL_LOG_FILE = DATA_DIR / "email_history.csv"
DATA_DIR.mkdir(exist_ok=True)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# --------------------------------------------------
# Compatibility: newer Streamlit removed use_container_width
# in favour of width="stretch". Pick whichever works.
# --------------------------------------------------
try:
    _NEW_WIDTH_API = "width" in inspect.signature(st.button).parameters
except (TypeError, ValueError):
    _NEW_WIDTH_API = False

STRETCH = {"width": "stretch"} if _NEW_WIDTH_API else {"use_container_width": True}


def read_csv_safe(path):
    if not Path(path).exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except (pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.DataFrame()


def append_csv(path, record):
    df = read_csv_safe(path)
    df = pd.concat([df, pd.DataFrame([record])], ignore_index=True)
    df.to_csv(path, index=False)


# ==================================================
# EMAIL FEATURE
# ==================================================
# Configure SMTP in  .streamlit/secrets.toml  like this:
#
#   [email]
#   host = "smtp.gmail.com"
#   port = 465
#   username = "youraddress@gmail.com"
#   password = "your-16-char-app-password"
#   sender_name = "SAFERA Alerts"
#
# Or use environment variables:
#   SAFERA_SMTP_HOST, SAFERA_SMTP_PORT, SAFERA_SMTP_USER,
#   SAFERA_SMTP_PASSWORD, SAFERA_SMTP_SENDER_NAME
# ==================================================
def is_valid_email(address):
    return bool(address) and bool(EMAIL_PATTERN.match(str(address).strip()))


def get_smtp_config():
    """Return SMTP settings dict, or None if email is not configured."""
    config = {}

    try:
        if "email" in st.secrets:
            section = st.secrets["email"]
            config = {
                "host": section.get("host"),
                "port": section.get("port", 465),
                "username": section.get("username"),
                "password": section.get("password"),
                "sender_name": section.get("sender_name", "SAFERA Alerts"),
            }
    except Exception:
        config = {}

    if not config.get("host"):
        config = {
            "host": os.getenv("SAFERA_SMTP_HOST"),
            "port": os.getenv("SAFERA_SMTP_PORT", "465"),
            "username": os.getenv("SAFERA_SMTP_USER"),
            "password": os.getenv("SAFERA_SMTP_PASSWORD"),
            "sender_name": os.getenv("SAFERA_SMTP_SENDER_NAME", "SAFERA Alerts"),
        }

    if not (config.get("host") and config.get("username") and config.get("password")):
        return None

    try:
        config["port"] = int(config["port"])
    except (TypeError, ValueError):
        config["port"] = 465

    return config


def log_email(kind, recipients, subject, status):
    append_csv(EMAIL_LOG_FILE, {
        "Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Type": kind,
        "Recipients": ", ".join(recipients),
        "Subject": subject,
        "Status": status,
    })


def load_email_log():
    return read_csv_safe(EMAIL_LOG_FILE)


def send_email(recipients, subject, text_body, html_body=None, kind="General"):
    """Send an email through SMTP. Returns (success, message)."""
    recipients = [r.strip() for r in recipients if is_valid_email(r)]

    if not recipients:
        return False, "No valid recipient email address."

    config = get_smtp_config()
    if config is None:
        return False, (
            "Email is not configured. Add SMTP details in "
            ".streamlit/secrets.toml (see the Email Center page)."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{config['sender_name']} <{config['username']}>"
    msg["To"] = ", ".join(recipients)
    msg.set_content(text_body)

    if html_body:
        msg.add_alternative(html_body, subtype="html")

    try:
        context = ssl.create_default_context()

        if config["port"] == 465:
            with smtplib.SMTP_SSL(
                config["host"], config["port"], context=context, timeout=25
            ) as server:
                server.login(config["username"], config["password"])
                server.send_message(msg)
        else:
            with smtplib.SMTP(config["host"], config["port"], timeout=25) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(config["username"], config["password"])
                server.send_message(msg)

        log_email(kind, recipients, subject, "Sent")
        return True, f"Email sent to {', '.join(recipients)}"

    except smtplib.SMTPAuthenticationError:
        log_email(kind, recipients, subject, "Failed: authentication")
        return False, "Email login failed. Check username / app password."
    except (smtplib.SMTPException, OSError) as error:
        log_email(kind, recipients, subject, f"Failed: {error}")
        return False, f"Could not send email: {error}"


def build_sos_email(now, gmap_link, sender_label):
    subject = "🚨 SAFERA SOS ALERT - I need help"

    text_body = (
        "SAFERA SOS ALERT\n\n"
        f"{sender_label} has triggered an emergency SOS.\n"
        f"Time: {now}\n"
        f"Live location: {gmap_link}\n\n"
        "Please contact them immediately. If needed, call 112 "
        "(India emergency number).\n\n"
        "- Sent via SAFERA (student prototype)"
    )

    html_body = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f4f1fb;padding:20px;">
      <div style="max-width:560px;margin:auto;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #d9cdf5;">
        <div style="background:#5735a5;color:#fff;padding:18px 22px;">
          <h2 style="margin:0;">🚨 SAFERA SOS ALERT</h2>
        </div>
        <div style="padding:22px;color:#222;">
          <p><b>{html.escape(sender_label)}</b> has triggered an emergency SOS and needs help.</p>
          <p><b>Time:</b> {html.escape(now)}</p>
          <p><a href="{html.escape(gmap_link)}" style="background:#9333ea;color:#fff;padding:12px 20px;border-radius:10px;text-decoration:none;display:inline-block;">📍 Open Live Location</a></p>
          <p style="font-size:13px;color:#555;">Please contact them immediately. If needed, call <b>112</b>.</p>
        </div>
      </div>
    </body></html>
    """
    return subject, text_body, html_body


def build_route_email(origin, destination, result, travel_time, weather, familiarity):
    subject = f"SAFERA Route Report: {origin} → {destination} ({result['score']}/100)"

    factors_text = "\n".join(f"  - {f}" for f in result["factors"])
    text_body = (
        "SAFERA ROUTE RISK REPORT\n\n"
        f"From: {origin}\n"
        f"To: {destination}\n"
        f"Travel time: {travel_time}\n"
        f"Weather: {weather}\n"
        f"Route familiarity: {familiarity}\n\n"
        f"Estimated risk: {result['score']}/100 - {result['level']}\n"
        f"{result['summary']}\n\n"
        f"Factors used:\n{factors_text}\n\n"
        "Note: this is an illustrative heuristic estimate, not a "
        "validated prediction or a safety guarantee.\n"
    )

    factors_html = "".join(f"<li>{html.escape(f)}</li>" for f in result["factors"])
    html_body = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f4f1fb;padding:20px;">
      <div style="max-width:560px;margin:auto;background:#fff;border-radius:16px;overflow:hidden;border:1px solid #d9cdf5;">
        <div style="background:#5735a5;color:#fff;padding:18px 22px;">
          <h2 style="margin:0;">🛡️ SAFERA Route Report</h2>
        </div>
        <div style="padding:22px;color:#222;">
          <p><b>From:</b> {html.escape(origin)}<br>
             <b>To:</b> {html.escape(destination)}</p>
          <h1 style="color:#6d3bd1;margin:6px 0;">{result['score']}/100</h1>
          <h3 style="margin:0 0 10px;">{html.escape(result['level'])}</h3>
          <p>{html.escape(result['summary'])}</p>
          <p><b>Factors used</b></p>
          <ul>{factors_html}</ul>
          <p style="font-size:12px;color:#777;">This is an illustrative heuristic estimate, not a validated prediction or a safety guarantee.</p>
        </div>
      </div>
    </body></html>
    """
    return subject, text_body, html_body


# ==================================================
# ROUTE RISK CALCULATION
# ==================================================
def calculate_risk(travel_time, weather, familiarity):
    score = 20
    factors = []

    time_points = {"Daytime": 0, "Evening": 10, "Late night": 20}
    weather_points = {
        "Clear": 0, "Rain": 8, "Heavy rain": 15,
        "Extreme heat": 10, "Unknown": 5,
    }
    familiarity_points = {"Familiar": 0, "Somewhat familiar": 8, "Unfamiliar": 15}

    t = time_points[travel_time]
    w = weather_points[weather]
    f = familiarity_points[familiarity]

    score += t + w + f
    score = min(100, max(0, score))

    factors.append(f"Travel time: {travel_time} (+{t})")
    factors.append(f"Weather: {weather} (+{w})")
    factors.append(f"Route familiarity: {familiarity} (+{f})")

    if score < 35:
        level = "Lower estimated concern"
        summary = "Review your travel plans and stay aware."
    elif score < 60:
        level = "Moderate estimated concern"
        summary = "Consider sharing your travel plans with someone."
    else:
        level = "Higher estimated concern"
        summary = "Consider a well-lit public route and contacting someone you trust."

    return {"score": score, "level": level, "summary": summary, "factors": factors}


# ==================================================
# SAVE AND LOAD HISTORY
# ==================================================
def save_history(origin, destination, score, level, travel_time, weather):
    append_csv(HISTORY_FILE, {
        "Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Starting Point": origin,
        "Destination": destination,
        "Risk Score": score,
        "Risk Level": level,
        "Travel Time": travel_time,
        "Weather": weather,
    })


def load_history():
    return read_csv_safe(HISTORY_FILE)


# ==================================================
# EMERGENCY RESOURCE SEARCH
# ==================================================
def nearby_places(place, kind):
    headers = {"User-Agent": "SAFERA-Student-Project/1.0"}

    response = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": place, "format": "jsonv2", "limit": 1},
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()

    locations = response.json()
    if not locations:
        return []

    lat = float(locations[0]["lat"])
    lon = float(locations[0]["lon"])

    filters = {
        "Police": 'nwr["amenity"="police"]',
        "Hospital": 'nwr["amenity"="hospital"]',
        "Pharmacy": 'nwr["amenity"="pharmacy"]',
        "All": 'nwr["amenity"~"^(police|hospital|pharmacy)$"]',
    }
    selected_filter = filters.get(kind, filters["All"])

    query = f"""
    [out:json][timeout:25];
    (
      {selected_filter}(around:10000,{lat},{lon});
    );
    out center tags;
    """

    response = requests.post(
        "https://overpass-api.de/api/interpreter",
        data={"data": query},
        headers=headers,
        timeout=35,
    )
    response.raise_for_status()

    elements = response.json().get("elements", [])
    results = []

    for item in elements[:30]:
        tags = item.get("tags", {})

        name = tags.get("name", "Unnamed service")
        service_type = tags.get("amenity", "Service").title()

        address_parts = [
            tags.get("addr:housenumber", ""),
            tags.get("addr:street", ""),
            tags.get("addr:city", ""),
        ]
        address = ", ".join(p for p in address_parts if p) or "Address not listed"

        item_lat = item.get("lat", item.get("center", {}).get("lat"))
        item_lon = item.get("lon", item.get("center", {}).get("lon"))

        url = ""
        if item_lat is not None and item_lon is not None:
            url = f"https://www.openstreetmap.org/?mlat={item_lat}&mlon={item_lon}"

        results.append({
            "name": name,
            "type": service_type,
            "address": address,
            "url": url,
        })

    return results


# ==================================================
# DARK PURPLE THEME
# ==================================================
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');

    html, body, [class*="css"] {
        font-family: 'DM Sans', sans-serif;
    }

    .stApp {
        background: linear-gradient(135deg, #080d1a, #11152b 55%, #1b1030);
        color: #f1f5f9;
    }

    [data-testid="stAppViewContainer"] {
        background: transparent;
    }

    [data-testid="stHeader"] {
        background: rgba(8, 13, 26, 0.85);
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #11172b, #1b1230);
        border-right: 1px solid #30274b;
    }

    [data-testid="stSidebar"] * {
        color: #f1f5f9;
    }

    .hero {
        padding: 2rem;
        border-radius: 24px;
        background: linear-gradient(120deg, #21154f, #5735a5 62%, #8e5ad7);
        margin-bottom: 1.2rem;
        box-shadow: 0 10px 35px #00000040;
    }

    .hero h1 {
        font-family: 'Manrope', sans-serif;
        font-size: 2.6rem;
        margin: 0;
        color: white;
    }

    .hero p {
        font-size: 1.05rem;
        color: #f3e8ff;
    }

    .panel, .metric {
        background: #171d31;
        color: #f1f5f9;
        padding: 1.1rem;
        border-radius: 18px;
        border: 1px solid #303854;
        margin-bottom: .8rem;
    }

    .panel h3, .metric h3 {
        color: #c4b5fd;
    }

    .small {
        color: #b6bfd5;
        font-size: .9rem;
    }

    .stTextInput input,
    .stTextArea textarea {
        background: #111729 !important;
        color: white !important;
        border: 1px solid #424b68 !important;
        border-radius: 10px;
    }

    .stButton > button,
    .stFormSubmitButton > button {
        background: linear-gradient(120deg, #6d3bd1, #9333ea);
        color: white;
        border: 1px solid #8b5cf6;
        border-radius: 12px;
        font-weight: 700;
        min-height: 2.8rem;
    }

    .stButton > button:hover,
    .stFormSubmitButton > button:hover {
        background: #7c3aed;
        color: white;
        border-color: #c4b5fd;
    }

    .stCheckbox label, .stRadio label {
        color: #e2e8f0 !important;
    }

    .stProgress > div > div > div {
        background: linear-gradient(90deg, #7c3aed, #c084fc);
    }

    [data-testid="stForm"] {
        background: #111729;
        border: 1px solid #303854;
        border-radius: 16px;
        padding: 1rem;
    }
    </style>

    <div class="hero">
        <h1>🛡️ SAFERA</h1>
        <p>Move with confidence. Plan thoughtfully. Reach out when you need help.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ==================================================
# SESSION STATE
# ==================================================
if "trusted_contacts" not in st.session_state:
    st.session_state.trusted_contacts = []
if "sos_active" not in st.session_state:
    st.session_state.sos_active = False
if "user_name" not in st.session_state:
    st.session_state.user_name = ""

# ==================================================
# SIDEBAR NAVIGATION
# ==================================================
st.sidebar.markdown("## 🛡️ SAFERA")
st.sidebar.caption("Women's safety companion • Student prototype")

page = st.sidebar.radio(
    "Navigate",
    [
        "Safety dashboard",
        "Route planner",
        "Emergency resources",
        "Email center",
        "Safety history",
        "About & limitations",
    ],
)

st.sidebar.warning("Prototype only: estimates are not verified safety guarantees.")

if get_smtp_config():
    st.sidebar.success("📧 Email: configured")
else:
    st.sidebar.info("📧 Email: not configured (see Email center)")

# ==================================================
# SAFETY DASHBOARD AND SOS
# ==================================================
if page == "Safety dashboard":

    st.subheader("Your Safety Dashboard - Live SOS System")

    col1, col2, col3 = st.columns(3)
    col1.markdown('<div class="metric"><h3>🆘 SOS Alert</h3><p class="small">Live Location + WhatsApp + Email</p></div>', unsafe_allow_html=True)
    col2.markdown('<div class="metric"><h3>🗺️ Route Check</h3><p class="small">Review route factors</p></div>', unsafe_allow_html=True)
    col3.markdown('<div class="metric"><h3>🌦️ Weather</h3><p class="small">Consider travel conditions</p></div>', unsafe_allow_html=True)

    # Your name (used in SOS emails)
    st.session_state.user_name = st.text_input(
        "Your name (shown in SOS messages)",
        value=st.session_state.user_name,
        placeholder="e.g. Priya",
    )

    # Trusted Contacts
    st.markdown('<div class="panel"><h3>👥 Trusted Contacts</h3><p class="small">These contacts will get your SOS with live location link (WhatsApp, SMS and Email)</p></div>', unsafe_allow_html=True)

    with st.expander("➕ Add Trusted Contact"):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Name", key="c_name")
        phone = c2.text_input("WhatsApp Number (with +91)", placeholder="+919876543210", key="c_phone")
        email = c3.text_input("Email (optional)", placeholder="mom@example.com", key="c_email")
        if st.button("Save Contact"):
            if not name.strip() or not phone.strip():
                st.error("Name and WhatsApp number are required.")
            elif email.strip() and not is_valid_email(email):
                st.error("Please enter a valid email address.")
            else:
                st.session_state.trusted_contacts.append({
                    "name": name.strip(),
                    "phone": phone.strip(),
                    "email": email.strip(),
                })
                st.success(f"Added {name.strip()}")

    if st.session_state.trusted_contacts:
        for idx, contact in enumerate(st.session_state.trusted_contacts):
            email_text = contact.get("email") or "no email"
            row_a, row_b = st.columns([6, 1])
            row_a.write(f"{idx + 1}. {contact['name']} - {contact['phone']} - 📧 {email_text}")
            if row_b.button("🗑️", key=f"del_contact_{idx}"):
                st.session_state.trusted_contacts.pop(idx)
                st.rerun()

    # Live Location
    st.markdown('<div class="panel"><h3>📍 My Live Location</h3><p class="small">Allow location permission in browser for accurate location</p></div>', unsafe_allow_html=True)

    loc = get_geolocation()

    lat, lon, gmap_link = None, None, None
    coords = loc.get("coords") if isinstance(loc, dict) else None

    if coords and coords.get("latitude") is not None:
        lat = coords["latitude"]
        lon = coords["longitude"]
        gmap_link = f"https://www.google.com/maps?q={lat},{lon}"
        st.success(f"Location Locked: {lat:.6f}, {lon:.6f}")

        m = folium.Map(location=[lat, lon], zoom_start=17)
        folium.Marker(
            [lat, lon],
            popup="SOS LOCATION",
            icon=folium.Icon(color="red", icon="exclamation-sign"),
        ).add_to(m)
        st_folium(m, width=700, height=350, returned_objects=[])
        st.code(gmap_link)
    else:
        st.warning("Waiting for location... Please click Allow when browser asks for location.")
        st.info("Demo Location used if not allowed: Hyderabad")
        lat, lon = 17.3850, 78.4867
        gmap_link = f"https://www.google.com/maps?q={lat},{lon}"
        st.code(gmap_link)

    # SOS BUTTONS
    st.divider()
    st.markdown("### 🚨 EMERGENCY SOS SYSTEM")

    silent = st.checkbox("Enable Silent SOS (Fake Incoming Call Screen for safety)")
    email_sos = st.checkbox("📧 Also send SOS by Email to contacts who have an email", value=True)

    col_sos1, col_sos2 = st.columns(2)

    with col_sos1:
        if st.button("🚨 SEND SOS NOW", type="primary", **STRETCH):
            if not st.session_state.trusted_contacts:
                st.error("Add at least 1 trusted contact first!")
            else:
                st.session_state.sos_active = True
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # ---- Email SOS ----
                email_status = "Not requested"
                if email_sos:
                    recipients = [
                        c.get("email", "")
                        for c in st.session_state.trusted_contacts
                        if is_valid_email(c.get("email", ""))
                    ]
                    if recipients:
                        sender_label = st.session_state.user_name.strip() or "A SAFERA user"
                        subject, text_body, html_body = build_sos_email(now, gmap_link, sender_label)
                        ok, message = send_email(recipients, subject, text_body, html_body, kind="SOS")
                        email_status = "Email sent" if ok else "Email failed"
                        if ok:
                            st.success(f"📧 {message}")
                        else:
                            st.warning(f"📧 {message}")
                    else:
                        email_status = "No contact emails"
                        st.info("No trusted contact has an email address, so no email was sent.")

                # Save SOS history
                append_csv(SOS_FILE, {
                    "Time": now,
                    "Location": gmap_link,
                    "Lat": lat,
                    "Lon": lon,
                    "Status": f"SOS Sent ({email_status})",
                })

                st.error(f"🚨 SOS SENT at {now}")

                # WhatsApp Links
                for c in st.session_state.trusted_contacts:
                    msg = (
                        f"SAFERA SOS ALERT! I NEED HELP! Time:{now} "
                        f"My Live Location: {gmap_link} Please call 112 if needed. - Sent via SAFERA"
                    )
                    clean_phone = re.sub(r"[^\d]", "", c["phone"])
                    wa_link = f"https://wa.me/{clean_phone}?text={quote(msg)}"
                    st.markdown(f"[📲 Send WhatsApp to {html.escape(c['name'])}]({wa_link})")

                # SMS Fallback
                sms_msg = f"SAFERA SOS! Help me! Location: {gmap_link}"
                st.markdown(f"[📩 Send SMS (Works Without Internet)](sms:?body={quote(sms_msg)})")
                st.markdown("[📞 Call 112 Emergency](tel:112)")

                st.balloons()

                if silent:
                    st.markdown(
                        "<div style='background:#000;color:#fff;padding:40px;border-radius:24px;text-align:center;border:2px solid #9333ea'>"
                        "<h2 style='color:#fff'>📞 Mom is calling...</h2>"
                        "<p style='font-size:60px'>📱</p>"
                        "<p>Slide to answer</p>"
                        "<small style='color:#c4b5fd'>Your SOS is secretly active behind this screen</small>"
                        "</div>",
                        unsafe_allow_html=True,
                    )

    with col_sos2:
        if st.button("✅ I AM SAFE - Stop SOS", **STRETCH):
            st.session_state.sos_active = False
            st.success("You marked safe. SOS stopped.")

            safe_recipients = [
                c.get("email", "")
                for c in st.session_state.trusted_contacts
                if is_valid_email(c.get("email", ""))
            ]
            if email_sos and safe_recipients and get_smtp_config():
                sender_label = st.session_state.user_name.strip() or "A SAFERA user"
                safe_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ok, message = send_email(
                    safe_recipients,
                    "✅ SAFERA: I am safe now",
                    f"{sender_label} has marked themselves SAFE at {safe_time}.\n"
                    "The earlier SOS alert is cancelled.\n\n- Sent via SAFERA",
                    kind="Safe notice",
                )
                if ok:
                    st.success("📧 'I am safe' email sent.")
                else:
                    st.warning(f"📧 {message}")
            st.snow()

    if st.session_state.sos_active:
        st.warning("🔴 SOS IS ACTIVE - Keep this tab open for live tracking. Your location link keeps updating on refresh.")

    st.markdown("### Safety Checklist")
    checklist = [
        ("📍", "Share Location", "Tell someone your expected arrival time"),
        ("🔋", "Charge Phone", "Carry a power bank if possible"),
        ("📞", "Emergency Contacts", "Keep trusted contacts ready"),
        ("🚶", "Public Routes", "Prefer well-lit, populated areas"),
    ]
    cols = st.columns(4)
    for col, (emoji, title, description) in zip(cols, checklist):
        col.markdown(
            f'<div class="panel"><h3>{emoji} {html.escape(title)}</h3>'
            f'<p class="small">{html.escape(description)}</p></div>',
            unsafe_allow_html=True,
        )

    st.info("In India, call 112 for emergency assistance when needed. Do not rely on this prototype for emergency dispatch.")

# ==================================================
# ROUTE PLANNER
# ==================================================
elif page == "Route planner":

    st.subheader("🗺️ Route Safety Planner")
    st.write("This is an illustrative heuristic estimate, not a trained AI model or verified crime-risk prediction.")

    with st.form("route_form"):
        col1, col2 = st.columns(2)
        origin = col1.text_input("Starting point", placeholder="e.g. MGBS, Hyderabad")
        destination = col2.text_input("Destination", placeholder="e.g. Charminar, Hyderabad")
        travel_time = st.selectbox("Travel time", ["Daytime", "Evening", "Late night"])
        weather = st.selectbox("Weather", ["Clear", "Rain", "Heavy rain", "Extreme heat", "Unknown"])
        familiarity = st.selectbox("Route familiarity", ["Familiar", "Somewhat familiar", "Unfamiliar"])
        report_email = st.text_input(
            "📧 Email this report to (optional)",
            placeholder="you@example.com or a trusted contact",
        )
        calculate = st.form_submit_button("Estimate Route Risk", type="primary", **STRETCH)

    if calculate:
        if not origin.strip() or not destination.strip():
            st.error("Enter both starting point and destination.")
        elif report_email.strip() and not is_valid_email(report_email):
            st.error("Please enter a valid email address for the report.")
        else:
            try:
                result = calculate_risk(travel_time, weather, familiarity)
                save_history(origin.strip(), destination.strip(), result["score"], result["level"], travel_time, weather)
                st.markdown(
                    f'<div class="panel"><div class="small">ESTIMATED ROUTE RISK</div>'
                    f'<h1>{result["score"]}/100</h1><h3>{html.escape(result["level"])}</h3>'
                    f'<p>{html.escape(result["summary"])}</p></div>',
                    unsafe_allow_html=True,
                )
                st.progress(result["score"] / 100)
                st.markdown("#### Factors Used")
                for factor in result["factors"]:
                    st.write("• " + factor)
                st.warning("This is an illustrative score only. It is not a validated AI prediction or a safety guarantee.")
                route_query = quote(f"{origin} to {destination}")
                st.markdown(f"[Search route on OpenStreetMap ↗](https://www.openstreetmap.org/search?query={route_query})")
                st.caption("Use a live navigation app to confirm your route and current conditions.")

                if report_email.strip():
                    subject, text_body, html_body = build_route_email(
                        origin.strip(), destination.strip(), result,
                        travel_time, weather, familiarity,
                    )
                    with st.spinner("Sending email..."):
                        ok, message = send_email(
                            [report_email.strip()], subject,
                            text_body, html_body, kind="Route report",
                        )
                    if ok:
                        st.success(f"📧 {message}")
                    else:
                        st.warning(f"📧 {message}")
            except Exception as error:
                st.error(f"Could not calculate route risk: {error}")

# ==================================================
# EMERGENCY RESOURCES
# ==================================================
elif page == "Emergency resources":

    st.subheader("📍 Emergency Resources")
    st.write("Search OpenStreetMap for nearby services. An internet connection is required, and results may be incomplete.")
    place = st.text_input("Area or city", "Hyderabad, Telangana")
    kind = st.selectbox("Resource type", ["Police", "Hospital", "Pharmacy", "All"])
    if st.button("Find Resources", type="primary"):
        if not place.strip():
            st.error("Enter an area or city.")
        else:
            with st.spinner("Searching OpenStreetMap..."):
                try:
                    results = nearby_places(place.strip(), kind)
                    if results:
                        for item in results:
                            name = html.escape(str(item["name"]))
                            service_type = html.escape(str(item["type"]))
                            address = html.escape(str(item["address"]))
                            st.markdown(
                                f'<div class="panel"><h3>📍 {name}</h3>'
                                f'<p class="small">{service_type}</p><p>{address}</p></div>',
                                unsafe_allow_html=True,
                            )
                            if item.get("url"):
                                st.markdown(f"[Open in OpenStreetMap ↗]({item['url']})")
                            st.divider()
                    else:
                        st.info("No results found. Try a nearby landmark or a broader area.")
                except requests.RequestException:
                    st.error("Could not fetch results. Check your internet connection and try again later.")
                except (ValueError, KeyError) as error:
                    st.error(f"Could not read map results: {error}")

    st.markdown("### Emergency Numbers in India")
    st.markdown(
        "- **112** — National emergency response number\n"
        "- **181** — Women's helpline in many states; availability varies"
    )
    st.warning("If you are in immediate danger, contact emergency services directly. Do not rely on this prototype.")

# ==================================================
# EMAIL CENTER
# ==================================================
elif page == "Email center":

    st.subheader("📧 Email Center")
    st.write("Send safety messages by email, test your email setup, and review sent-email history.")

    config = get_smtp_config()

    if config:
        st.success(f"Email is configured. Sending as: {config['username']} via {config['host']}:{config['port']}")
    else:
        st.warning("Email is not configured yet. Follow the setup steps below.")

    with st.expander("⚙️ How to set up email (SMTP)", expanded=not config):
        st.markdown(
            "1. Create a folder named `.streamlit` next to this file.\n"
            "2. Inside it, create a file named `secrets.toml`.\n"
            "3. Paste this and fill in your details:"
        )
        st.code(
            '[email]\n'
            'host = "smtp.gmail.com"\n'
            'port = 465\n'
            'username = "youraddress@gmail.com"\n'
            'password = "your-16-char-app-password"\n'
            'sender_name = "SAFERA Alerts"',
            language="toml",
        )
        st.markdown(
            "- **Gmail:** turn on 2-Step Verification, then create an **App Password** "
            "(Google Account → Security → App passwords). Use that, not your normal password.\n"
            "- **Port 465** uses SSL; **port 587** uses STARTTLS. Both are supported.\n"
            "- Never upload `secrets.toml` to GitHub. Add it to `.gitignore`.\n"
            "- On Streamlit Cloud, paste the same text into **App settings → Secrets**."
        )

    tab_test, tab_send, tab_log = st.tabs(["✅ Test email", "✉️ Send message", "🕘 Email log"])

    with tab_test:
        test_to = st.text_input("Send a test email to", placeholder="you@example.com", key="test_to")
        if st.button("Send Test Email"):
            if not is_valid_email(test_to):
                st.error("Enter a valid email address.")
            else:
                with st.spinner("Sending..."):
                    ok, message = send_email(
                        [test_to.strip()],
                        "SAFERA test email",
                        "This is a test email from SAFERA. Your email setup works! 🎉",
                        kind="Test",
                    )
                if ok:
                    st.success(message)
                else:
                    st.error(message)

    with tab_send:
        st.caption("Write a custom safety update, e.g. 'I reached home safely'.")

        # de-duplicate (duplicates crash st.multiselect)
        contact_emails = list(dict.fromkeys(
            c["email"].strip()
            for c in st.session_state.trusted_contacts
            if is_valid_email(c.get("email", ""))
        ))
        chosen = st.multiselect(
            "Trusted contacts with email",
            options=contact_emails,
            default=contact_emails,
        )
        extra = st.text_input(
            "Other recipients (comma separated, optional)",
            placeholder="friend@example.com, sister@example.com",
        )
        subject = st.text_input("Subject", value="SAFERA safety update")
        body = st.text_area("Message", value="I have reached my destination safely.", height=140)
        attach_location = st.checkbox("Include my demo/current location link (Hyderabad demo if location is off)")

        if st.button("Send Email", type="primary"):
            extra_list = [e.strip() for e in extra.split(",") if e.strip()]
            invalid = [e for e in extra_list if not is_valid_email(e)]
            recipients = list(dict.fromkeys(chosen + extra_list))

            if invalid:
                st.error(f"Invalid email(s): {', '.join(invalid)}")
            elif not recipients:
                st.error("Choose or enter at least one recipient.")
            elif not subject.strip() or not body.strip():
                st.error("Subject and message cannot be empty.")
            else:
                final_body = body.strip()
                if attach_location:
                    final_body += "\n\nLocation: https://www.google.com/maps?q=17.3850,78.4867"
                final_body += "\n\n- Sent via SAFERA"

                with st.spinner("Sending..."):
                    ok, message = send_email(
                        recipients, subject.strip(), final_body,
                        kind="Custom message",
                    )
                if ok:
                    st.success(message)
                else:
                    st.error(message)

    with tab_log:
        log_df = load_email_log()
        if not log_df.empty:
            st.dataframe(log_df, hide_index=True, **STRETCH)
            st.caption("Stored locally in data/email_history.csv. Passwords are never stored.")
            if st.button("Clear Email Log"):
                EMAIL_LOG_FILE.unlink(missing_ok=True)
                st.success("Email log cleared.")
                st.rerun()
        else:
            st.info("No emails sent yet.")

    st.warning("Email is not instant like a call. In an emergency, call 112 directly.")

# ==================================================
# SAFETY HISTORY
# ==================================================
elif page == "Safety history":

    st.subheader("📚 Route Risk History")
    try:
        history = load_history()
        if not history.empty:
            st.dataframe(history, hide_index=True, **STRETCH)
            st.caption("Stored locally in data/safety_history.csv.")
            if st.button("Clear Local History"):
                HISTORY_FILE.unlink(missing_ok=True)
                st.success("Local history cleared.")
                st.rerun()
        else:
            st.info("No routes saved yet. Use the Route Planner to calculate and save a route estimate.")
    except Exception as error:
        st.error(f"Could not load safety history: {error}")

    st.divider()
    st.subheader("🚨 SOS History")
    try:
        df_sos_hist = read_csv_safe(SOS_FILE)
        if not df_sos_hist.empty:
            st.dataframe(df_sos_hist, hide_index=True, **STRETCH)
            if st.button("Clear SOS History"):
                SOS_FILE.unlink(missing_ok=True)
                st.success("SOS history cleared.")
                st.rerun()
        else:
            st.info("No SOS alerts sent yet. SOS alerts will appear here.")
    except Exception as e:
        st.error(f"Could not load SOS history: {e}")

    st.divider()
    st.subheader("📧 Email an Export of Your History")
    export_to = st.text_input("Send history summary to", placeholder="you@example.com", key="export_to")
    if st.button("Email Route History"):
        hist_df = load_history()
        if hist_df.empty:
            st.info("No route history to send yet.")
        elif not is_valid_email(export_to):
            st.error("Enter a valid email address.")
        else:
            summary_text = "SAFERA ROUTE HISTORY\n\n" + hist_df.tail(20).to_string(index=False)
            ok, message = send_email(
                [export_to.strip()],
                "SAFERA route history (last 20)",
                summary_text,
                kind="History export",
            )
            if ok:
                st.success(message)
            else:
                st.error(message)

# ==================================================
# ABOUT AND LIMITATIONS
# ==================================================
else:

    st.subheader("About SAFERA")
    st.markdown(
        '<div class="panel"><h3>🛡️ About the Project</h3><p>SAFERA is a student prototype designed to '
        'support thoughtful travel planning and access to emergency-resource information with Live SOS '
        'and Email alerts.</p></div>',
        unsafe_allow_html=True,
    )
    st.markdown("### Included Features")
    st.markdown(
        "- 🌙 Dark navy and purple interface\n"
        "- 🆘 Live SOS with GPS + Folium Map + WhatsApp Share + SMS Fallback + Fake Call Screen\n"
        "- 📧 Email: automatic SOS emails, \"I am safe\" email, route reports, custom messages, test email and email log\n"
        "- 🗺️ Heuristic route-risk estimation\n"
        "- 📍 OpenStreetMap emergency-resource search\n"
        "- 📚 Local route-risk + SOS history\n"
        "- 🔴 Silent SOS mode"
    )
    st.markdown("### Limitations")
    st.warning(
        "- Website cannot detect hardware power button 3 times - needs native Android app for that.\n"
        "- WhatsApp links need user to click send - not fully automatic without Twilio API.\n"
        "- Email needs SMTP credentials in secrets.toml; delivery is not instant or guaranteed and may land in spam.\n"
        "- Risk score is not a trained AI prediction."
    )
    st.info("SAFERA is a student prototype, not a replacement for emergency services or live navigation.")

# ==================================================
# SIDEBAR FOOTER
# ==================================================
st.sidebar.divider()
st.sidebar.caption("SAFERA • Student Project • Live SOS + Email • Dark Mode")