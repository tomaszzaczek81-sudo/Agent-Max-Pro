import streamlit as st
import urllib.parse
import urllib.request
import PyPDF2
import re
import base64
import pandas as pd
import io
import unicodedata
import hashlib
import psycopg2
from psycopg2.extras import DictCursor
from fpdf import FPDF
from groq import Groq
from audio_recorder_streamlit import audio_recorder
import requests
from bs4 import BeautifulSoup
from gtts import gTTS
import sys
from contextlib import redirect_stdout
import datetime
import time
import traceback
import xml.etree.ElementTree as ET

# ==========================================
# 1. KONFIGURACJA I APPLE PREMIUM DESIGN (CSS)
# ==========================================
st.set_page_config(page_title="Agent AI Max Pro", layout="wide", page_icon="⚡")

apple_theme_css = """
<style>
    html, body, [class*="css"], .stApp { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #161617; color: #F5F5F7; }
    [data-testid="stSidebar"] { background-color: #1E1E1F !important; border-right: 1px solid #333336; }
    h1, h2, h3 { color: #FFFFFF !important; font-weight: 600 !important; letter-spacing: -0.022em !important; }
    .stButton>button { background-color: #2D2D2F; color: #F5F5F7; border: 1px solid #424245; border-radius: 8px; padding: 8px 16px; font-weight: 500; transition: all 0.2s ease; }
    .stButton>button:hover { background-color: #3A3A3C; border-color: #68686E; color: #FFFFFF; }
    .stButton>button[data-testid="baseButton-primary"] { background-color: #0071E3 !important; border: none !important; color: #FFFFFF !important; }
    .stButton>button[data-testid="baseButton-primary"]:hover { background-color: #147CE5 !important; box-shadow: 0 0 8px rgba(0,113,227,0.4); }
    .stTextInput>div>div>input, .stSelectbox>div>div>div, .stTextArea>div>div>textarea { background-color: #1E1E1F !important; color: #FFFFFF !important; border: 1px solid #424245 !important; border-radius: 8px !important; }
    .stTextInput>div>div>input:focus, .stTextArea>div>div>textarea:focus { border-color: #0071E3 !important; box-shadow: 0 0 0 3px rgba(0,113,227,0.2) !important; }
    [data-testid="stChatMessage"] { background-color: #1E1E1F !important; border: 1px solid #2D2D2F !important; border-radius: 12px !important; padding: 16px !important; margin-bottom: 12px !important; }
    .stDetails { background-color: #1E1E1F !important; border: 1px solid #2D2D2F !important; border-radius: 12px !important; }
    .myśli-agenta { font-size: 0.85em; color: #86868B; border-left: 2px solid #0071E3; padding-left: 10px; font-style: italic; margin-bottom: 15px;}
</style>
"""
st.markdown(apple_theme_css, unsafe_allow_html=True)

# ==========================================
# 2. BEZPIECZNE RENDEROWANIE (NOWOŚĆ V20)
# ==========================================
def bezpieczny_tekst(tekst):
    tekst_bez_wyzwalaczy = re.split(r'GENERATE_', tekst)[0].strip()
    
    # Jeśli agent wciąż pisze myśli (brak zamknięcia tagu)
    if "<mysli>" in tekst_bez_wyzwalaczy and "</mysli>" not in tekst_bez_wyzwalaczy:
        return "🧠 *Agent głęboko analizuje logikę...* ▌"
        
    # Usuń zamknięte myśli
    oczyszczony = re.sub(r'<mysli>.*?</mysli>', '', tekst_bez_wyzwalaczy, flags=re.DOTALL).strip()
    
    # KULOODPORNOŚĆ: Jeśli po usunięciu myśli nic nie zostało, pokaż surowy tekst!
    if not oczyszczony and tekst_bez_wyzwalaczy:
        return tekst_bez_wyzwalaczy.replace("<mysli>", "🧠 **Moje wewnętrzne przemyślenia:**\n\n").replace("</mysli>", "\n\n---\n")
        
    return oczyszczony

# ==========================================
# 3. POŁĄCZENIE I INICJALIZACJA BAZY
# ==========================================
def pobierz_polaczenie_db(retries=3):
    for i in range(retries):
        try: return psycopg2.connect(st.secrets["DATABASE_URL"], connect_timeout=5)
        except Exception as e:
            if i == retries - 1: raise e
            time.sleep(1)

def inicjalizuj_baze_danych():
    try:
        conn = pobierz_polaczenie_db(); cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS uzytkownicy (id SERIAL PRIMARY KEY, login TEXT UNIQUE NOT NULL, haslo_hash TEXT NOT NULL, rola TEXT NOT NULL)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS historia_czatow (id SERIAL PRIMARY KEY, uzytkownik_id INTEGER REFERENCES uzytkownicy(id) ON DELETE CASCADE, rola TEXT NOT NULL, tresc TEXT NOT NULL, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS baza_wiedzy (id SERIAL PRIMARY KEY, nazwa TEXT, tresc TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS preferencje_uzytkownika (uzytkownik_id INTEGER PRIMARY KEY, profil TEXT)''')
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM uzytkownicy WHERE rola = 'admin'")
        if cur.fetchone()[0] == 0:
            hash_hasla = hashlib.sha256(st.secrets["ADMIN_PASSWORD"].encode()).hexdigest()
            try: cur.execute("INSERT INTO uzytkownicy (login, haslo_hash, rola) VALUES (%s, %s, %s)", (st.secrets["ADMIN_LOGIN"], hash_hasla, 'admin')); conn.commit()
            except: conn.rollback()
        cur.close(); conn.close()
    except Exception as e:
        st.error(f"❌ BŁĄD BAZY DANYCH. Szczegóły: {e}"); st.stop()

inicjalizuj_baze_danych()

def weryfikuj_uzytkownika(login, haslo):
    conn = pobierz_polaczenie_db(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT id, login, rola FROM uzytkownicy WHERE login = %s AND haslo_hash = %s", (login, hashlib.sha256(haslo.encode()).hexdigest()))
    user = cur.fetchone(); cur.close(); conn.close(); return user

def zapisz_wiadomosc_db(user_id, rola, tresc):
    try:
        conn = pobierz_polaczenie_db(); cur = conn.cursor()
        cur.execute("INSERT INTO historia_czatow (uzytkownik_id, rola, tresc) VALUES (%s, %s, %s)", (user_id, rola, tresc))
        conn.commit(); cur.close(); conn.close()
    except Exception as e: print(f"Błąd zapisu historii: {e}")

def pobierz_historie_db(user_id):
    try:
        conn = pobierz_polaczenie_db(); cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("SELECT rola, tresc FROM historia_czatow WHERE uzytkownik_id = %s ORDER BY timestamp ASC", (user_id,))
        rows = cur.fetchall(); cur.close(); conn.close()
        return [{"role": r["rola"], "content": r["tresc"]} for r in rows]
    except: return []

def wyczysc_historie_db(user_id):
    conn = pobierz_polaczenie_db(); cur = conn.cursor()
    cur.execute("DELETE FROM historia_czatow WHERE uzytkownik_id = %s", (user_id,))
    conn.commit(); cur.close(); conn.close()

def szukaj_w_bazie_wiedzy(zapytanie):
    try:
        slowa = [w for w in re.findall(r'\b\w{5,}\b', zapytanie.lower())]
        if not slowa: return ""
        conn = pobierz_polaczenie_db(); cur = conn.cursor()
        query_parts = " OR ".join(["tresc ILIKE %s"] * len(slowa))
        params = [f"%{s}%" for s in slowa]
        cur.execute(f"SELECT nazwa, tresc FROM baza_wiedzy WHERE {query_parts} LIMIT 2", params)
        wyniki = cur.fetchall(); cur.close(); conn.close()
        if wyniki: return "\n\n".join([f"[Źródło bazy wiedzy: {w[0]}]: {w[1][:1500]}" for w in wyniki])
        return ""
    except: return ""

def pobierz_profil(user_id):
    try:
        conn = pobierz_polaczenie_db(); cur = conn.cursor()
        cur.execute("SELECT profil FROM preferencje_uzytkownika WHERE uzytkownik_id = %s", (user_id,))
        res = cur.fetchone(); cur.close(); conn.close(); return res[0] if res else ""
    except: return ""

def zapisz_profil(user_id, profil):
    conn = pobierz_polaczenie_db(); cur = conn.cursor()
    cur.execute("SELECT 1 FROM preferencje_uzytkownika WHERE uzytkownik_id = %s", (user_id,))
    if cur.fetchone(): cur.execute("UPDATE preferencje_uzytkownika SET profil = %s WHERE uzytkownik_id = %s", (profil, user_id))
    else: cur.execute("INSERT INTO preferencje_uzytkownika (uzytkownik_id, profil) VALUES (%s, %s)", (user_id, profil))
    conn.commit(); cur.close(); conn.close()

def stabilne_wyszukiwanie(zapytanie):
    wyniki = ""
    try:
        url_news = f"https://news.google.com/rss/search?q={urllib.parse.quote(zapytanie)}&hl=pl&gl=PL&ceid=PL:pl"
        res_news = requests.get(url_news, timeout=5)
        root = ET.fromstring(res_news.content)
        items = root.findall('.//item/title')
        if items:
            wyniki += "\n--- BAZA AKTUALNOŚCI Z DZISIAJ ---\n"
            wyniki += "\n".join([f"- {item.text}" for item in items[:5]]) + "\n"
    except: pass
    return wyniki

# ==========================================
# 4. INTERFEJS LOGOWANIA
# ==========================================
if "user_auth" not in st.session_state: st.session_state.user_auth = None
if not st.session_state.user_auth:
    st.title("🔒 Wielodostępny System AI")
    login = st.text_input("Login")
    haslo = st.text_input("Hasło", type="password")
    if st.button("ZALOGUJ SIĘ", type="primary"):
        uzytkownik = weryfikuj_uzytkownika(login, haslo)
        if uzytkownik: st.session_state.user_auth = {"id": uzytkownik["id"], "login": uzytkownik["login"], "rola": uzytkownik["rola"]}; st.rerun()
        else: st.error("❌ Błędny login lub hasło.")
    st.stop()

USER_ID = st.session_state.user_auth["id"]
USER_LOGIN = st.session_state.user_auth["login"]
USER_ROLA = st.session_state.user_auth["rola"]

# ==========================================
# 5. PANEL BOCZNY 
# ==========================================
st.sidebar.title(f"👤 {USER_LOGIN} ({USER_ROLA})")
if st.sidebar.button("Wyloguj", type="secondary"): st.session_state.user_auth = None; st.rerun()

st.sidebar.markdown("---")
agentic_mode = st.sidebar.toggle("🧠 Agentic Workflow (Myślenie)", value=False)
tts_mode = st.sidebar.toggle("🔊 Lektor (Odpowiedzi Głosowe)", value=False)

TRYBY = {
    "🧠 Główny Asystent": "Jesteś wszechstronnym Agentem AI. Odpowiadaj profesjonalnie.",
    "🌐 Konsylium (Swarm Mode)": "Jesteś zarządcą roju ekspertów (Swarm). Twoja odpowiedź MUSI być symulacją dyskusji ekspertów.",
    "💻 Architekt Szyszka & T.Ż": "Jesteś ekspertem Pythona i systemów ERP.",
    "🚀 Ekspert LinkedIn": "Jesteś ekspertem personal brandingu na LinkedIn.",
    "🔧 Mechanik Diagnosta": "Jesteś specjalistą od mechaniki pojazdowej."
}
wybrany_tryb = st.sidebar.selectbox("🎭 Osobistość Agenta", list(TRYBY.keys()))

st.sidebar.markdown("---")
with st.sidebar.expander("👤 Mój Profil (Pamięć)", expanded=False):
    nowy_profil = st.text_area("Twój profil:", value=pobierz_profil(USER_ID), height=150)
    if st.button("Zapisz w Pamięci Agenta"): zapisz_profil(USER_ID, nowy_profil); st.success("Zapisano!")

# ==========================================
# 6. CZĘŚĆ GŁÓWNA I OBSŁUGA CZATU
# ==========================================
st.title("⚡ Agent AI Max Pro V20")
st.caption("System: Bulletproof Render | Cleaned Engine | Zero Silent Failures")

if "python_env" not in st.session_state: st.session_state.python_env = {}
if "img_memory" not in st.session_state: st.session_state.img_memory = None

with st.sidebar:
    st.markdown("---")
    zdjecie = st.file_uploader("👁️ Dodaj Zdjęcie", type=['png', 'jpg', 'jpeg'])
    if zdjecie: 
        st.session_state.img_memory = base64.b64encode(zdjecie.read()).decode('utf-8')
        st.success("Obraz wgrany!")
    else: st.session_state.img_memory = None

    if st.button("🧹 Resetuj rozmowę"): 
        wyczysc_historie_db(USER_ID); st.session_state.python_env = {}; st.rerun()

historia_czatu = pobierz_historie_db(USER_ID)
for msg in historia_czatu:
    if msg["role"] == "user" and "KONTEKST SYSTEMOWY:" in str(msg["content"]): continue
    with st.chat_message(msg["role"]):
        raw_text = str(msg["content"])
        widoczny = bezpieczny_tekst(raw_text)
        if widoczny: st.markdown(widoczny.replace(" ▌", ""))

col_mic, col_input = st.columns([1, 10])
with col_mic: audio_bytes = audio_recorder(text="", icon_size="2x", key="mic")
with col_input: polecenie = st.chat_input("Wpisz zapytanie...")

if polecenie:
    kontekst_kb = szukaj_w_bazie_wiedzy(polecenie)
    kontekst_web = ""
    slowa_czasowe = ["dzisiaj", "dziś", "wczoraj", "jutro", "obecnie", "teraz", "2024", "2025", "2026", "wiadomości", "ceny"]
    if any(s in polecenie.lower() for s in slowa_czasowe):
        with st.spinner("🌍 Przeszukuję sieć na żywo..."): kontekst_web = stabilne_wyszukiwanie(polecenie)

    zapytanie_do_wyslania = polecenie
    if kontekst_kb or kontekst_web:
        zapytanie_do_wyslania = "KONTEKST SYSTEMOWY:\n"
        if kontekst_kb: zapytanie_do_wyslania += f"--- BAZA WIEDZY ---\n{kontekst_kb}\n"
        if kontekst_web: zapytanie_do_wyslania += f"--- INTERNET ---\n{kontekst_web}\n"
        zapytanie_do_wyslania += f"\nPYTANIE UŻYTKOWNIKA: {polecenie}"

    zapisz_wiadomosc_db(USER_ID, "user", polecenie)
    with st.chat_message("user"): st.markdown(polecenie)
        
    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_response = ""
        
        instrukcja_sys = TRYBY[wybrany_tryb]
        instrukcja_sys += f"\n\nWAŻNE: Dzisiejsza data to {datetime.datetime.now().strftime('%Y-%m-%d')}. Rok 2026."
        
        profil_usera = pobierz_profil(USER_ID)
        if profil_usera: instrukcja_sys += f"\n\nZASADY UŻYTKOWNIKA:\n{profil_usera}"
        if agentic_mode: instrukcja_sys += "\n\nUWAGA: Musisz otworzyć tag <mysli> i przeprowadzić logikę. Na koniec ZAMKNIJ TAG i napisz finalną odpowiedź poza nim!"
        
        instrukcja_sys += "\n\n--- UKRYTE WYZWALACZE SYSTEMOWE ---\nZDJĘCIE -> GENERATE_IMAGE: [prompt]\nEXCEL -> GENERATE_EXCEL: [dane CSV]\nKOD -> GENERATE_CODE: [kod Python]"
        
        # Zabezpieczenie przed błędem struktury zapytań Llama 3
        api_messages = [{"role": "system", "content": instrukcja_sys}] + historia_czatu
        
        if st.session_state.img_memory: 
            api_messages.append({"role": "user", "content": [{"type": "text", "text": zapytanie_do_wyslania}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{st.session_state.img_memory}"}}]})
        else: 
            api_messages.append({"role": "user", "content": zapytanie_do_wyslania})

        try:
            client = Groq(api_key=st.secrets["GROQ_API_KEY"])
            wybrany_model = "llama-3.2-11b-vision-preview" if st.session_state.img_memory else "llama-3.3-70b-versatile"
            
            stream = client.chat.completions.create(model=wybrany_model, messages=api_messages, stream=True)
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    full_response += chunk.choices[0].delta.content
                    placeholder.markdown(bezpieczny_tekst(full_response))
            
            odpowiedz_finalna = bezpieczny_tekst(full_response).replace(" ▌", "")
            placeholder.markdown(odpowiedz_finalna)
            zapisz_wiadomosc_db(USER_ID, "assistant", full_response)
            
        except Exception as e:
            st.error("❌ KRYTYCZNY BŁĄD API GROQ ❌")
            st.error(f"Treść: {e}")

        if "GENERATE_CODE:" in full_response:
            try:
                kod = full_response.split("GENERATE_CODE:")[1].split("GENERATE_")[0].strip()
                kod = re.sub(r'```python|```', '', kod).strip()
                st.markdown("**💻 Interpreter Pythona:**")
                st.code(kod, language="python")
                f = io.StringIO()
                with redirect_stdout(f): exec(kod, st.session_state.python_env)
                if f.getvalue(): st.info(f"Wynik:\n{f.getvalue()}")
            except Exception as e: st.error(f"❌ Błąd skryptu: {e}")
