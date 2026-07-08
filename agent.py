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
from duckduckgo_search import DDGS

# ==========================================
# 1. KONFIGURACJA I APPLE PREMIUM DESIGN (CSS)
# ==========================================
st.set_page_config(page_title="Agent AI Max Pro", layout="wide", page_icon="⚡")

apple_theme_css = """
<style>
    html, body, [class*="css"], .stApp {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background-color: #161617;
        color: #F5F5F7;
    }
    [data-testid="stSidebar"] {
        background-color: #1E1E1F !important;
        border-right: 1px solid #333336;
    }
    h1, h2, h3 { color: #FFFFFF !important; font-weight: 600 !important; letter-spacing: -0.022em !important; }
    .stButton>button {
        background-color: #2D2D2F; color: #F5F5F7; border: 1px solid #424245; border-radius: 8px;
        padding: 8px 16px; font-weight: 500; transition: all 0.2s ease;
    }
    .stButton>button:hover { background-color: #3A3A3C; border-color: #68686E; color: #FFFFFF; }
    .stButton>button[data-testid="baseButton-primary"] { background-color: #0071E3 !important; border: none !important; color: #FFFFFF !important; }
    .stButton>button[data-testid="baseButton-primary"]:hover { background-color: #147CE5 !important; box-shadow: 0 0 8px rgba(0,113,227,0.4); }
    .stTextInput>div>div>input, .stSelectbox>div>div>div, .stTextArea>div>div>textarea {
        background-color: #1E1E1F !important; color: #FFFFFF !important; border: 1px solid #424245 !important; border-radius: 8px !important;
    }
    .stTextInput>div>div>input:focus, .stTextArea>div>div>textarea:focus { border-color: #0071E3 !important; box-shadow: 0 0 0 3px rgba(0,113,227,0.2) !important; }
    [data-testid="stChatMessage"] { background-color: #1E1E1F !important; border: 1px solid #2D2D2F !important; border-radius: 12px !important; padding: 16px !important; margin-bottom: 12px !important; }
    .stDetails { background-color: #1E1E1F !important; border: 1px solid #2D2D2F !important; border-radius: 12px !important; }
    .myśli-agenta { font-size: 0.85em; color: #86868B; border-left: 2px solid #0071E3; padding-left: 10px; font-style: italic; margin-bottom: 15px;}
</style>
"""
st.markdown(apple_theme_css, unsafe_allow_html=True)

# ==========================================
# 2. POŁĄCZENIE I INICJALIZACJA BAZY (W TYM NOWE FUNKCJE V15)
# ==========================================
def pobierz_polaczenie_db():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def inicjalizuj_baze_danych():
    conn = pobierz_polaczenie_db()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS uzytkownicy (id SERIAL PRIMARY KEY, login TEXT UNIQUE NOT NULL, haslo_hash TEXT NOT NULL, rola TEXT NOT NULL)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS historia_czatow (id SERIAL PRIMARY KEY, uzytkownik_id INTEGER REFERENCES uzytkownicy(id) ON DELETE CASCADE, rola TEXT NOT NULL, tresc TEXT NOT NULL, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS baza_wiedzy (id SERIAL PRIMARY KEY, nazwa TEXT, tresc TEXT)''')
    # NOWE TABELE V15: Preferencje i Harmonogram
    cur.execute('''CREATE TABLE IF NOT EXISTS preferencje_uzytkownika (uzytkownik_id INTEGER PRIMARY KEY, profil TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS zadania_cykliczne (id SERIAL PRIMARY KEY, uzytkownik_id INTEGER, url TEXT)''')
    conn.commit()
    
    cur.execute("SELECT COUNT(*) FROM uzytkownicy WHERE rola = 'admin'")
    if cur.fetchone()[0] == 0:
        hash_hasla = hashlib.sha256(st.secrets["ADMIN_PASSWORD"].encode()).hexdigest()
        try:
            cur.execute("INSERT INTO uzytkownicy (login, haslo_hash, rola) VALUES (%s, %s, %s)", (st.secrets["ADMIN_LOGIN"], hash_hasla, 'admin'))
            conn.commit()
        except: conn.rollback()
    cur.close(); conn.close()

try: inicjalizuj_baze_danych()
except Exception as e: st.error(f"Błąd bazy: {e}"); st.stop()

# ==========================================
# 3. MECHANIZMY SYSTEMOWE (AUTORYZACJA, RAG, WEB SCRAPING)
# ==========================================
def weryfikuj_uzytkownika(login, haslo):
    conn = pobierz_polaczenie_db()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT id, login, rola FROM uzytkownicy WHERE login = %s AND haslo_hash = %s", (login, hashlib.sha256(haslo.encode()).hexdigest()))
    user = cur.fetchone()
    cur.close(); conn.close()
    return user

def zapisz_wiadomosc_db(user_id, rola, tresc):
    conn = pobierz_polaczenie_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO historia_czatow (uzytkownik_id, rola, tresc) VALUES (%s, %s, %s)", (user_id, rola, tresc))
    conn.commit(); cur.close(); conn.close()

def pobierz_historie_db(user_id):
    conn = pobierz_polaczenie_db()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT rola, tresc FROM historia_czatow WHERE uzytkownik_id = %s ORDER BY timestamp ASC", (user_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [{"role": r["rola"], "content": r["tresc"]} for r in rows]

def wyczysc_historie_db(user_id):
    conn = pobierz_polaczenie_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM historia_czatow WHERE uzytkownik_id = %s", (user_id,))
    conn.commit(); cur.close(); conn.close()

def dodaj_do_bazy_wiedzy(nazwa, tresc):
    conn = pobierz_polaczenie_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO baza_wiedzy (nazwa, tresc) VALUES (%s, %s)", (nazwa, tresc))
    conn.commit(); cur.close(); conn.close()

def szukaj_w_bazie_wiedzy(zapytanie):
    slowa = [w for w in re.findall(r'\b\w{5,}\b', zapytanie.lower())]
    if not slowa: return ""
    conn = pobierz_polaczenie_db()
    cur = conn.cursor()
    query_parts = " OR ".join(["tresc ILIKE %s"] * len(slowa))
    params = [f"%{s}%" for s in slowa]
    cur.execute(f"SELECT nazwa, tresc FROM baza_wiedzy WHERE {query_parts} LIMIT 2", params)
    wyniki = cur.fetchall()
    cur.close(); conn.close()
    if wyniki: return "\n\n".join([f"[Źródło bazy wiedzy: {w[0]}]: {w[1][:1500]}" for w in wyniki])
    return ""

def pobierz_tekst_z_url(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        for script in soup(["script", "style", "nav", "footer"]): script.extract()
        return soup.get_text(separator=' ', strip=True)
    except Exception as e: return f"BŁĄD: {e}"

# FUNKCJE DLA PAMIĘCI EPIZODYCZNEJ
def pobierz_profil(user_id):
    conn = pobierz_polaczenie_db()
    cur = conn.cursor()
    cur.execute("SELECT profil FROM preferencje_uzytkownika WHERE uzytkownik_id = %s", (user_id,))
    res = cur.fetchone()
    cur.close(); conn.close()
    return res[0] if res else ""

def zapisz_profil(user_id, profil):
    conn = pobierz_polaczenie_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM preferencje_uzytkownika WHERE uzytkownik_id = %s", (user_id,))
    if cur.fetchone(): cur.execute("UPDATE preferencje_uzytkownika SET profil = %s WHERE uzytkownik_id = %s", (profil, user_id))
    else: cur.execute("INSERT INTO preferencje_uzytkownika (uzytkownik_id, profil) VALUES (%s, %s)", (user_id, profil))
    conn.commit(); cur.close(); conn.close()

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
        if uzytkownik:
            st.session_state.user_auth = {"id": uzytkownik["id"], "login": uzytkownik["login"], "rola": uzytkownik["rola"]}
            st.rerun()
        else: st.error("Błąd logowania!")
    st.stop()

USER_ID = st.session_state.user_auth["id"]
USER_LOGIN = st.session_state.user_auth["login"]
USER_ROLA = st.session_state.user_auth["rola"]

# ==========================================
# 5. PANEL BOCZNY (WSZYSTKIE MODUŁY V15)
# ==========================================
st.sidebar.title(f"👤 {USER_LOGIN} ({USER_ROLA})")
if st.sidebar.button("Wyloguj", type="secondary"): st.session_state.user_auth = None; st.rerun()

# PANEL ADMINISTRATORA (Ukryty dla zwykłych użytkowników)
if USER_ROLA == "admin":
    st.sidebar.markdown("---")
    with st.sidebar.expander("🛠️ PANEL ADMINISTRATORA", expanded=False):
        nowy_user = st.text_input("Nowy login", key="n_user")
        nowe_haslo = st.text_input("Nowe hasło", type="password", key="n_pass")
        nowa_rola = st.selectbox("Rola", ["user", "admin"], key="n_role")
        if st.button("UTWÓRZ KONTO"):
            if nowy_user and nowe_haslo:
                h_hash = hashlib.sha256(nowe_haslo.encode()).hexdigest()
                conn = pobierz_polaczenie_db()
                cur = conn.cursor()
                try:
                    cur.execute("INSERT INTO uzytkownicy (login, haslo_hash, rola) VALUES (%s, %s, %s)", (nowy_user, h_hash, nowa_rola))
                    conn.commit()
                    st.success("Konto stworzone!")
                except: st.error("Taki użytkownik już istnieje.")
                cur.close(); conn.close()
        st.markdown("---")
        conn = pobierz_polaczenie_db()
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("SELECT login FROM uzytkownicy WHERE login != %s", (USER_LOGIN,))
        lista_uzytkownikow = cur.fetchall()
        cur.close(); conn.close()
        if lista_uzytkownikow:
            wybrany_uzytkownik = st.selectbox("Zarządzaj kontem", [u["login"] for u in lista_uzytkownikow])
            zmien_haslo = st.text_input("Nowe hasło użytkownika", type="password")
            if st.button("ZMIEŃ HASŁO"):
                h_hash = hashlib.sha256(zmien_haslo.encode()).hexdigest()
                conn = pobierz_polaczenie_db(); cur = conn.cursor()
                cur.execute("UPDATE uzytkownicy SET haslo_hash = %s WHERE login = %s", (h_hash, wybrany_uzytkownik))
                conn.commit(); cur.close(); conn.close(); st.success("Hasło zmienione!")
            if st.button("❌ USUŃ KONTO", type="primary"):
                conn = pobierz_polaczenie_db(); cur = conn.cursor()
                cur.execute("DELETE FROM uzytkownicy WHERE login = %s", (wybrany_uzytkownik,))
                conn.commit(); cur.close(); conn.close(); st.rerun()

st.sidebar.markdown("---")
# WŁĄCZNIK AGENTIC WORKFLOW (Opcja 1)
agentic_mode = st.sidebar.toggle("🧠 Agentic Workflow (Samoweryfikacja)", value=False, help="Agent będzie analizował swoje błędy przed podaniem odpowiedzi.")

# OSOBISTOŚCI
TRYBY = {
    "🧠 Główny Asystent": "Jesteś wszechstronnym Agentem AI. Odpowiadaj profesjonalnie.",
    "🚀 Ekspert LinkedIn": "Jesteś ekspertem personal brandingu na LinkedIn. Używaj emoji, hashtagów i formatowania pod social media.",
    "✍️ Inżynier Promptów": "Jesteś światowej klasy Inżynierem Promptów. Twórz precyzyjne struktury promptów (PL/ENG).",
    "💻 Architekt Szyszka & T.Ż": "Jesteś ekspertem Pythona i systemów ERP.",
    "🏀 Trener Koszykówki": "Jesteś analitykiem koszykówki.",
    "🔧 Mechanik Diagnosta": "Jesteś specjalistą od mechaniki pojazdowej (grupa VAG)."
}
wybrany_tryb = st.sidebar.selectbox("🎭 Osobistość Agenta", list(TRYBY.keys()))

st.sidebar.markdown("---")
# PAMIĘĆ EPIZODYCZNA (Opcja 2)
with st.sidebar.expander("👤 Mój Profil (Pamięć Epizodyczna)", expanded=False):
    st.caption("Napisz, jak Agent ma się do Ciebie zwracać i jakie zasady ma zawsze pamiętać.")
    aktualny_profil = pobierz_profil(USER_ID)
    nowy_profil = st.text_area("Twój unikalny profil:", value=aktualny_profil, height=150)
    if st.button("Zapisz w Pamięci Agenta"):
        zapisz_profil(USER_ID, nowy_profil)
        st.success("Profil zaktualizowany!")

# BAZA WIEDZY I SCHEDULER (Opcja 3)
with st.sidebar.expander("📚 Wiedza i Zadania w Tle", expanded=False):
    plik_kb = st.file_uploader("Wgraj plik (PDF/TXT)", type=['pdf', 'txt'])
    if plik_kb and st.button("💾 Zapisz Plik"):
        tresc = "".join([page.extract_text() for page in PyPDF2.PdfReader(plik_kb).pages]) if plik_kb.type == "application/pdf" else plik_kb.read().decode("utf-8")
        dodaj_do_bazy_wiedzy(plik_kb.name, tresc)
        st.success("Plik zapisany!")
    
    st.markdown("---")
    st.markdown("**Dodaj Auto-Skanowanie URL:**")
    url_do_zadania = st.text_input("Link do śledzenia (https://...)")
    if st.button("Dodaj do kolejki zadań"):
        conn = pobierz_polaczenie_db(); cur = conn.cursor()
        cur.execute("INSERT INTO zadania_cykliczne (uzytkownik_id, url) VALUES (%s, %s)", (USER_ID, url_do_zadania))
        conn.commit(); cur.close(); conn.close(); st.success("Dodano do kolejki!")
    
    if st.button("▶️ Uruchom zadania z kolejki"):
        with st.spinner("Agent skanuje zaplanowane strony w tle..."):
            conn = pobierz_polaczenie_db(); cur = conn.cursor()
            cur.execute("SELECT id, url FROM zadania_cykliczne WHERE uzytkownik_id = %s", (USER_ID,))
            zadania = cur.fetchall()
            for z in zadania:
                tekst = pobierz_tekst_z_url(z[1])
                if not tekst.startswith("BŁĄD"): dodaj_do_bazy_wiedzy(z[1], tekst)
                cur.execute("DELETE FROM zadania_cykliczne WHERE id = %s", (z[0],)) # Usuwa zadanie po wykonaniu
            conn.commit(); cur.close(); conn.close()
            st.success("Wszystkie zadania z kolejki wykonane!")

# ==========================================
# 6. CZĘŚĆ GŁÓWNA I OBSŁUGA CZATU
# ==========================================
st.title("⚡ Agent AI Max Pro V15")
st.caption("System: Ultimate Autonomous Edition | Apple Design | Live Web Search")

if "img_memory" not in st.session_state: st.session_state.img_memory = None
with st.sidebar:
    st.markdown("---")
    zdjecie = st.file_uploader("👁️ Dodaj Zdjęcie", type=['png', 'jpg', 'jpeg'])
    if zdjecie:
        st.session_state.img_memory = base64.b64encode(zdjecie.read()).decode('utf-8')
        st.success("Obraz wgrany!")
    if st.button("🧹 Resetuj rozmowę"): wyczysc_historie_db(USER_ID); st.rerun()

historia_czatu = pobierz_historie_db(USER_ID)
for msg in historia_czatu:
    if msg["role"] == "user" and "KONTEKST SYSTEMOWY:" in str(msg["content"]): continue
    with st.chat_message(msg["role"]):
        text = str(msg["content"])
        if "GENERATE_" in text: text = text.split("GENERATE_")[0].strip()
        
        # Wyświetlanie formatowanego bloku przemyśleń (Agentic Workflow)
        if "<mysli>" in text and "</mysli>" in text:
            mysli = text.split("<mysli>")[1].split("</mysli>")[0].strip()
            odpowiedz = text.split("</mysli>")[1].strip()
            with st.expander("Zobacz proces myślowy Agenta", expanded=False):
                st.markdown(f"<div class='myśli-agenta'>{mysli}</div>", unsafe_allow_html=True)
            st.markdown(odpowiedz)
        else:
            st.markdown(text)

col_mic, col_input = st.columns([1, 10])
with col_mic:
    audio_bytes = audio_recorder(text="", icon_size="2x", key="mic")
with col_input:
    polecenie = st.chat_input("Zadaj pytanie (zapytaj o dzisiejsze wydarzenia), wygeneruj plik...")

if audio_bytes and st.session_state.get('last_audio') != audio_bytes:
    st.session_state.last_audio = audio_bytes
    with st.spinner("🎧 Transkrybuję..."):
        try:
            polecenie = Groq(api_key=st.secrets["GROQ_API_KEY"]).audio.transcriptions.create(file=("audio.wav", audio_bytes), model="whisper-large-v3", response_format="text")
        except Exception: st.error("Błąd mikrofonu.")

if polecenie:
    kontekst_kb = szukaj_w_bazie_wiedzy(polecenie)
    kontekst_web = ""
    
    # NAPRAWA BŁĘDU ZE SCREENA: Moduł Inteligencji Czasu Rzeczywistego (DuckDuckGo)
    slowa_czasowe = ["dzisiaj", "dziś", "wczoraj", "jutro", "obecnie", "teraz", "2024", "2025", "2026", "wiadomości", "aktualności"]
    if any(s in polecenie.lower() for s in slowa_czasowe):
        with st.spinner("🌍 Przeszukuję internet w czasie rzeczywistym..."):
            try:
                wyniki_ddgs = DDGS().text(polecenie, region='pl-pl', max_results=3)
                if wyniki_ddgs:
                    kontekst_web = "\n".join([f"- Tytuł: {r['title']} | Treść: {r['body']}" for r in wyniki_ddgs])
            except: pass

    zapytanie_do_wyslania = polecenie
    if kontekst_kb or kontekst_web:
        zapytanie_do_wyslania = "KONTEKST SYSTEMOWY (Użyj tych danych do odpowiedzi):\n"
        if kontekst_kb: zapytanie_do_wyslania += f"--- DANE Z TWOJEJ BAZY WIEDZY ---\n{kontekst_kb}\n"
        if kontekst_web: zapytanie_do_wyslania += f"--- AKTUALNE WYNIKI Z INTERNETU (Omijają limit wiedzy) ---\n{kontekst_web}\n"
        zapytanie_do_wyslania += f"\nPYTANIE UŻYTKOWNIKA: {polecenie}"
        
        if kontekst_web: st.toast("Połączono z internetem na żywo!", icon="🌍")

    zapisz_wiadomosc_db(USER_ID, "user", polecenie) # Zapisujemy czyste pytanie bez kontekstu do historii
    with st.chat_message("user"): st.markdown(polecenie)
        
    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_response = ""
        
        # Budowa Instrukcji Systemowej z włączonymi opcjami
        instrukcja_sys = TRYBY[wybrany_tryb]
        
        # Aplikowanie Opcji 2: Pamięci Epizodycznej
        profil_usera = pobierz_profil(USER_ID)
        if profil_usera:
            instrukcja_sys += f"\n\nWAŻNE INFORMACJE O UŻYTKOWNIKU:\n{profil_usera}\nBezwzględnie stosuj się do tych zasad podczas całej rozmowy."
            
        # Aplikowanie Opcji 1: Agentic Workflow
        if agentic_mode:
            instrukcja_sys += (
                "\n\nUWAGA (TRYB AGENTIC WORKFLOW): Jesteś w trybie zaawansowanej analizy logicznej. Zanim wygenerujesz ostateczną odpowiedź, "
                "MUSISZ najpierw otworzyć tag <mysli>, przeprowadzić w nim dogłębną samokrytykę, zaplanować kroki odpowiedzi i wyłapać własne błędy. "
                "Dopiero po zamknięciu tagu </mysli> możesz podać ostateczną, gotową odpowiedź do użytkownika."
            )
            
        instrukcja_sys += "\nUKRYTE KOMENDY MEDIALNE: Jeśli zapytany, dodaj GENERATE_IMAGE: [prompt angielski], GENERATE_VIDEO: [prompt], GENERATE_EXCEL: [csv], GENERATE_PDF: [tekst]."
        
        api_messages = [{"role": "system", "content": instrukcja_sys}] + historia_czatu
        if st.session_state.img_memory: api_messages.append({"role": "user", "content": [{"type": "text", "text": zapytanie_do_wyslania}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{st.session_state.img_memory}"}}]})
        else: api_messages.append({"role": "user", "content": zapytanie_do_wyslania})

        try:
            client = Groq(api_key=st.secrets["GROQ_API_KEY"])
            stream = client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct" if st.session_state.img_memory else "llama-3.3-70b-versatile",
                messages=api_messages, stream=True
            )
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    full_response += chunk.choices[0].delta.content
                    # Wizualizacja na żywo z maskowaniem ukrytych komend i tagów myślowych
                    widoczny_stream = full_response.split("GENERATE_")[0]
                    if "<mysli>" in widoczny_stream and "</mysli>" not in widoczny_stream:
                        placeholder.markdown("🧠 *Agent przetwarza dane i weryfikuje logikę...* ▌")
                    elif "<mysli>" in widoczny_stream and "</mysli>" in widoczny_stream:
                        placeholder.markdown(widoczny_stream.split("</mysli>")[1].strip() + " ▌")
                    else:
                        placeholder.markdown(widoczny_stream + " ▌")
            
            # Finalne formatowanie po odebraniu całej wiadomości
            widoczny_koniec = full_response.split("GENERATE_")[0].strip()
            if "<mysli>" in widoczny_koniec and "</mysli>" in widoczny_koniec:
                mysli_finalne = widoczny_koniec.split("<mysli>")[1].split("</mysli>")[0].strip()
                odpowiedz_finalna = widoczny_koniec.split("</mysli>")[1].strip()
                with st.expander("Zobacz proces myślowy Agenta", expanded=False):
                    st.markdown(f"<div class='myśli-agenta'>{mysli_finalne}</div>", unsafe_allow_html=True)
                placeholder.markdown(odpowiedz_finalna)
            else:
                placeholder.markdown(widoczny_koniec)
                
            zapisz_wiadomosc_db(USER_ID, "assistant", full_response)
            
            # WYKONYWANIE KOMEND MEDIALNYCH (Grafiki, Wideo, Dokumenty)
            if "GENERATE_IMAGE:" in full_response: st.image(f"https://image.pollinations.ai/prompt/{urllib.parse.quote(full_response.split('GENERATE_IMAGE:')[1].split('GENERATE_')[0].strip())}?width=1024&height=1024&nologo=true&enhance=true", caption="🖼️ Render AI HD")
            if "GENERATE_VIDEO:" in full_response: st.image(f"https://image.pollinations.ai/prompt/{urllib.parse.quote(full_response.split('GENERATE_VIDEO:')[1].split('GENERATE_')[0].strip())}?width=512&height=512&nologo=true&model=flux", caption="🎬 Kadr Animacji")
            if "GENERATE_EXCEL:" in full_response:
                buffer = io.BytesIO(); pd.read_csv(io.StringIO(full_response.split("GENERATE_EXCEL:")[1].split("GENERATE_")[0].strip()), sep=";").to_excel(buffer, index=False, engine='openpyxl')
                st.download_button("📊 Pobierz Excel", data=buffer.getvalue(), file_name="Arkusz.xlsx", mime="application/vnd.ms-excel")
            if "GENERATE_PDF:" in full_response:
                pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", size=12); pdf.multi_cell(0, 10, txt=unicodedata.normalize('NFKD', full_response.split("GENERATE_PDF:")[1].split("GENERATE_")[0].strip()).encode('ascii', 'ignore').decode('utf-8'))
                st.download_button("📄 Pobierz PDF", data=pdf.output(dest='S').encode('latin1'), file_name="Dokument.pdf", mime="application/pdf")
                
        except Exception as e: st.error(f"Problem operacyjny: {e}")
