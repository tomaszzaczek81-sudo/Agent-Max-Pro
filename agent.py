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

# ==========================================
# 1. POŁĄCZENIE I INICJALIZACJA BAZY
# ==========================================
def pobierz_polaczenie_db():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def inicjalizuj_baze_danych():
    conn = pobierz_polaczenie_db()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS uzytkownicy (id SERIAL PRIMARY KEY, login TEXT UNIQUE NOT NULL, haslo_hash TEXT NOT NULL, rola TEXT NOT NULL)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS historia_czatow (id SERIAL PRIMARY KEY, uzytkownik_id INTEGER REFERENCES uzytkownicy(id) ON DELETE CASCADE, rola TEXT NOT NULL, tresc TEXT NOT NULL, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    # NOWOŚĆ: Tabela trwałej Bazy Wiedzy
    cur.execute('''CREATE TABLE IF NOT EXISTS baza_wiedzy (id SERIAL PRIMARY KEY, nazwa TEXT, tresc TEXT)''')
    conn.commit()
    
    cur.execute("SELECT COUNT(*) FROM uzytkownicy WHERE rola = 'admin'")
    if cur.fetchone()[0] == 0:
        hash_hasla = hashlib.sha256(st.secrets["ADMIN_PASSWORD"].encode()).hexdigest()
        try:
            cur.execute("INSERT INTO uzytkownicy (login, haslo_hash, rola) VALUES (%s, %s, %s)", (st.secrets["ADMIN_LOGIN"], hash_hasla, 'admin'))
            conn.commit()
        except: conn.rollback()
    cur.close()
    conn.close()

try: inicjalizuj_baze_danych()
except Exception as e: st.error(f"Błąd bazy: {e}"); st.stop()

# ==========================================
# 2. MECHANIZMY AUTORYZACJI I ZAPISU
# ==========================================
def weryfikuj_uzytkownika(login, haslo):
    conn = pobierz_polaczenie_db()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT id, login, rola FROM uzytkownicy WHERE login = %s AND haslo_hash = %s", (login, hashlib.sha256(haslo.encode()).hexdigest()))
    user = cur.fetchone()
    cur.close()
    conn.close()
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

# NOWOŚĆ: Funkcje Bazy Wiedzy
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
    if wyniki:
        return "\n\n".join([f"[Z pliku: {w[0]}]: {w[1][:1500]}" for w in wyniki])
    return ""

# ==========================================
# 3. INTERFEJS LOGOWANIA
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
# 4. NOWOŚĆ: TRYBY EKSPERCKIE I ZARZĄDZANIE WIEDZĄ
# ==========================================
st.sidebar.title(f"👤 {USER_LOGIN} ({USER_ROLA})")
if st.sidebar.button("Wyloguj", type="secondary"):
    st.session_state.user_auth = None; st.rerun()

TRYBY = {
    "🧠 Główny Asystent": "Jesteś wszechstronnym Agentem AI. Odpowiadaj profesjonalnie.",
    "💻 Architekt Szyszka & T.Ż": "Jesteś ekspertem Pythona, systemów ERP i logistyki. Pisz czysty kod, myśl strukturalnie i rozwiązuj problemy z architekturą oprogramowania.",
    "🏀 Trener Koszykówki": "Jesteś analitykiem i trenerem koszykówki. Skup się na dynamice, wydolności, mikrocyklach i technice rzutu zawodników.",
    "🔧 Mechanik Diagnosta": "Jesteś specjalistą od mechaniki pojazdowej, w szczególności silników grupy VAG (np. FSI). Podawaj precyzyjne diagnozy i kroki naprawcze."
}
wybrany_tryb = st.sidebar.selectbox("🎭 Wybierz Osobistość Agenta", list(TRYBY.keys()))

st.sidebar.markdown("---")
with st.sidebar.expander("📚 TRWAŁA BAZA WIEDZY (RAG)", expanded=False):
    st.caption("Pliki wgrane tutaj zostają w systemie na zawsze.")
    plik_kb = st.file_uploader("Wgraj do bazy (PDF/TXT)", type=['pdf', 'txt'], key="kb_upload")
    if plik_kb and st.button("💾 Zapisz w Bazie Wiedzy"):
        tresc = ""
        if plik_kb.type == "application/pdf":
            reader = PyPDF2.PdfReader(plik_kb)
            tresc = "".join([page.extract_text() for page in reader.pages])
        else:
            tresc = plik_kb.read().decode("utf-8")
        dodaj_do_bazy_wiedzy(plik_kb.name, tresc)
        st.success(f"Plik {plik_kb.name} dodany do pamięci trwałej!")

# ==========================================
# 5. CZĘŚĆ GŁÓWNA I OBSŁUGA CZATU
# ==========================================
st.title("⚡ Agent V12: Voice, RAG & Personas")

if "img_memory" not in st.session_state: st.session_state.img_memory = None
with st.sidebar:
    st.markdown("---")
    st.subheader("👁️ Zmysł Wzroku (Tymczasowy)")
    zdjecie = st.file_uploader("Dodaj Zdjęcie do analizy", type=['png', 'jpg', 'jpeg'])
    if zdjecie:
        st.session_state.img_memory = base64.b64encode(zdjecie.read()).decode('utf-8')
        st.success("Obraz wgrany!")
    if st.button("🧹 Resetuj rozmowę"):
        wyczysc_historie_db(USER_ID)
        st.rerun()

historia_czatu = pobierz_historie_db(USER_ID)
for msg in historia_czatu:
    if msg["role"] == "user" and "DODATKOWY KONTEKST Z BAZY WIEDZY:" in str(msg["content"]): continue
    with st.chat_message(msg["role"]):
        text = str(msg["content"])
        if "GENERATE_" in text: text = text.split("GENERATE_")[0].strip()
        if text: st.markdown(text)

# NOWOŚĆ: Interfejs Głosowy (Mikrofon)
col_mic, col_input = st.columns([1, 10])
with col_mic:
    audio_bytes = audio_recorder(text="", icon_size="2x", key="mic")
with col_input:
    polecenie_tekst = st.chat_input("Zadaj pytanie lub nagraj dźwięk...")

polecenie = polecenie_tekst

# Obsługa dźwięku z Whisper AI
if audio_bytes and st.session_state.get('last_audio') != audio_bytes:
    st.session_state.last_audio = audio_bytes
    with st.spinner("🎧 Nasłuchuję i transkrybuję..."):
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        try:
            transkrypcja = client.audio.transcriptions.create(
                file=("audio.wav", audio_bytes),
                model="whisper-large-v3",
                response_format="text"
            )
            polecenie = transkrypcja
        except Exception as e:
            st.error("Błąd mikrofonu: Upewnij się, że udzieliłeś uprawnień przeglądarce.")

if polecenie:
    # Krok 1: Automatyczne skanowanie Trwałej Bazy Wiedzy
    kontekst_kb = szukaj_w_bazie_wiedzy(polecenie)
    zapytanie_do_zapisu = polecenie
    zapytanie_do_wyslania = polecenie
    
    if kontekst_kb:
        zapytanie_do_wyslania = f"DODATKOWY KONTEKST Z BAZY WIEDZY:\n{kontekst_kb}\n\nPYTANIE: {polecenie}"
        st.toast("Wykryto powiązane dokumenty w Bazie Wiedzy!", icon="📚")

    zapisz_wiadomosc_db(USER_ID, "user", zapytanie_do_zapisu)
    with st.chat_message("user"): st.markdown(polecenie)
        
    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_response = ""
        
        instrukcja_sys = TRYBY[wybrany_tryb] + "\nOpcje ukryte: Jeśli zapytany, dodaj GENERATE_IMAGE: [prompt], GENERATE_EXCEL: [csv], GENERATE_PDF: [tekst]."
        api_messages = [{"role": "system", "content": instrukcja_sys}] + historia_czatu
        
        if st.session_state.img_memory:
            api_messages.append({"role": "user", "content": [{"type": "text", "text": zapytanie_do_wyslania}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{st.session_state.img_memory}"}}]})
        else:
            api_messages.append({"role": "user", "content": zapytanie_do_wyslania})

        try:
            client = Groq(api_key=st.secrets["GROQ_API_KEY"])
            stream = client.chat.completions.create(
                model="llama-3.2-11b-vision-preview" if st.session_state.img_memory else "llama-3.3-70b-versatile",
                messages=api_messages,
                stream=True
            )
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    full_response += chunk.choices[0].delta.content
                    placeholder.markdown(full_response.split("GENERATE_")[0] + "▌")
            
            widoczny = full_response.split("GENERATE_")[0].strip()
            placeholder.markdown(widoczny)
            zapisz_wiadomosc_db(USER_ID, "assistant", full_response)
            
            # WYZWALACZE PLIKÓW I OBRAZÓW (Zachowane z V11)
            if "GENERATE_IMAGE:" in full_response:
                st.image(f"https://image.pollinations.ai/prompt/{urllib.parse.quote(full_response.split('GENERATE_IMAGE:')[1].split('GENERATE_')[0].strip())}?width=1024&height=1024&nologo=true")
            if "GENERATE_EXCEL:" in full_response:
                df = pd.read_csv(io.StringIO(full_response.split("GENERATE_EXCEL:")[1].split("GENERATE_")[0].strip()), sep=";")
                buffer = io.BytesIO(); df.to_excel(buffer, index=False, engine='openpyxl')
                st.download_button("📊 Pobierz Excel", data=buffer.getvalue(), file_name="Arkusz.xlsx", mime="application/vnd.ms-excel")
            if "GENERATE_PDF:" in full_response:
                czysty_tekst = unicodedata.normalize('NFKD', full_response.split("GENERATE_PDF:")[1].split("GENERATE_")[0].strip()).encode('ascii', 'ignore').decode('utf-8')
                pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", size=12); pdf.multi_cell(0, 10, txt=czysty_tekst)
                st.download_button("📄 Pobierz PDF", data=pdf.output(dest='S').encode('latin1'), file_name="Dokument.pdf", mime="application/pdf")
                
        except Exception as e:
            st.error(f"Problem operacyjny: {e}")
