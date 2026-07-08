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

# ==========================================
# 1. POŁĄCZENIE I INICJALIZACJA BAZY (NEON)
# ==========================================
def pobierz_polaczenie_db():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def inicjalizuj_baze_danych():
    conn = pobierz_polaczenie_db()
    cur = conn.cursor()
    
    # Tabela użytkowników
    cur.execute('''
        CREATE TABLE IF NOT EXISTS uzytkownicy (
            id SERIAL PRIMARY KEY,
            login TEXT UNIQUE NOT NULL,
            haslo_hash TEXT NOT NULL,
            rola TEXT NOT NULL
        )
    ''')
    
    # Tabela historii czatów przypisana do użytkownika
    cur.execute('''
        CREATE TABLE IF NOT EXISTS historia_czatow (
            id SERIAL PRIMARY KEY,
            uzytkownik_id INTEGER REFERENCES uzytkownicy(id) ON DELETE CASCADE,
            rola TEXT NOT NULL,
            tresc TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    
    # Tworzenie domyślnego admina z Secrets, jeśli baza jest pusta
    cur.execute("SELECT COUNT(*) FROM uzytkownicy WHERE rola = 'admin'")
    if cur.fetchone()[0] == 0:
        login_admina = st.secrets["ADMIN_LOGIN"]
        haslo_admina = st.secrets["ADMIN_PASSWORD"]
        hash_hasla = hashlib.sha256(haslo_admina.encode()).hexdigest()
        try:
            cur.execute(
                "INSERT INTO uzytkownicy (login, haslo_hash, rola) VALUES (%s, %s, %s)",
                (login_admina, hash_hasla, 'admin')
            )
            conn.commit()
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            
    cur.close()
    conn.close()

# Uruchomienie struktury bazy danych
try:
    inicjalizuj_baze_danych()
except Exception as e:
    st.error(f"Błąd krytyczny połączenia z bazą Neon: {e}")
    st.stop()

# ==========================================
# 2. MECHANIZMY AUTORYZACJI I ZAPISU
# ==========================================
def weryfikuj_uzytkownika(login, haslo):
    hash_hasla = hashlib.sha256(haslo.encode()).hexdigest()
    conn = pobierz_polaczenie_db()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT id, login, rola FROM uzytkownicy WHERE login = %s AND haslo_hash = %s", (login, hash_hasla))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user

def zapisz_wiadomosc_db(user_id, rola, tresc):
    conn = pobierz_polaczenie_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO historia_czatow (uzytkownik_id, rola, tresc) VALUES (%s, %s, %s)", (user_id, rola, tresc))
    conn.commit()
    cur.close()
    conn.close()

def pobierz_historie_db(user_id):
    conn = pobierz_polaczenie_db()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT rola, tresc FROM historia_czatow WHERE uzytkownik_id = %s ORDER BY timestamp ASC", (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"role": r["rola"], "content": r["tresc"]} for r in rows]

def wyczysc_historie_db(user_id):
    conn = pobierz_polaczenie_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM historia_czatow WHERE uzytkownik_id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()

# ==========================================
# 3. INTERFEJS LOGOWANIA
# ==========================================
if "user_auth" not in st.session_state:
    st.session_state.user_auth = None

if not st.session_state.user_auth:
    st.title("🔒 Wielodostępny System AI")
    st.markdown("Wprowadź swoje indywidualne dane dostępowe.")
    
    input_login = st.text_input("Login")
    input_haslo = st.text_input("Hasło", type="password")
    
    if st.button("ZALOGUJ SIĘ", type="primary"):
        uzytkownik = weryfikuj_uzytkownika(input_login, input_haslo)
        if uzytkownik:
            st.session_state.user_auth = {
                "id": uzytkownik["id"],
                "login": uzytkownik["login"],
                "rola": uzytkownik["rola"]
            }
            st.rerun()
        else:
            st.error("Nieprawidłowy login lub hasło!")
    st.stop()

# Skróty zalogowanego profilu
USER_ID = st.session_state.user_auth["id"]
USER_LOGIN = st.session_state.user_auth["login"]
USER_ROLA = st.session_state.user_auth["rola"]

# ==========================================
# 4. POMOCNICZY MIKROSILNIK SIECIOWY
# ==========================================
def bezpieczne_wyszukiwanie(zapytanie):
    wynik = ""
    if "pogod" in zapytanie.lower():
        try:
            miasta = re.findall(r'\b[A-Z][a-ząćęłńóśźż]+\b', zapytanie)
            miasto = miasta[0] if miasta else zapytanie.split()[-1]
            url = f"https://wttr.in/{urllib.parse.quote(miasto)}?format=3"
            req = urllib.request.Request(url, headers={'User-Agent': 'curl'})
            with urllib.request.urlopen(req, timeout=3) as res:
                wynik += f"POGODA NA ŻYWO: {res.read().decode('utf-8')}\n\n"
        except: pass
            
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(zapytanie)}"
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=4) as res:
            html = res.read().decode('utf-8')
            snippets = re.findall(r'class="result__snippet[^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL)
            if snippets:
                wynik += "FAKTY Z INTERNETU:\n"
                for snip in snippets[:3]:
                    wynik += f"- {re.sub(r'<[^>]+>', '', snip).strip()}\n"
    except: pass
    
    return wynik if wynik else "Brak dostępu do sieci."
# ==========================================
# 5. PANEL ADMINISTRATORA I PANEL BOCZNY
# ==========================================
st.sidebar.title(f"Zalogowany: {USER_LOGIN} ({USER_ROLA})")
if st.sidebar.button("Wyloguj", type="secondary"):
    st.session_state.user_auth = None
    st.rerun()

# PANEL ADMINISTRATORA
if USER_ROLA == "admin":
    st.sidebar.markdown("---")
    with st.sidebar.expander("🛠️ PANEL ADMINISTRATORA", expanded=False):
        st.subheader("Zarządzanie użytkownikami")
        
        # Opcja 1: Dodawanie profilu
        st.markdown("**Dodaj nowego użytkownika:**")
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
                    st.success(f"Konto {nowy_user} stworzone!")
                except psycopg2.errors.UniqueViolation:
                    st.error("Taki użytkownik już istnieje.")
                    conn.rollback()
                cur.close()
                conn.close()
                
        st.markdown("---")
        # Opcja 2: Usuwanie i edycja innych kont
        st.markdown("**Zarządzaj istniejącymi kontami użytkowników:**")
        conn = pobierz_polaczenie_db()
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("SELECT login, rola FROM uzytkownicy WHERE login != %s", (USER_LOGIN,))
        lista_uzytkownikow = cur.fetchall()
        cur.close()
        conn.close()
        
        if lista_uzytkownikow:
            wybrany_uzytkownik = st.selectbox("Wybierz konto do modyfikacji", [u["login"] for u in lista_uzytkownikow])
            
            col1, col2 = st.columns(2)
            with col1:
                zmien_haslo = st.text_input("Nowe hasło użytkownika", type="password")
                if st.button("ZAKODUJ NOWE HASŁO"):
                    if zmien_haslo:
                        h_hash = hashlib.sha256(zmien_haslo.encode()).hexdigest()
                        conn = pobierz_polaczenie_db()
                        cur = conn.cursor()
                        cur.execute("UPDATE uzytkownicy SET haslo_hash = %s WHERE login = %s", (h_hash, wybrany_uzytkownik))
                        conn.commit()
                        cur.close()
                        conn.close()
                        st.success("Hasło użytkownika zmienione!")
            with col2:
                if st.button("❌ USUŃ KONTO", type="primary"):
                    conn = pobierz_polaczenie_db()
                    cur = conn.cursor()
                    cur.execute("DELETE FROM uzytkownicy WHERE login = %s", (wybrany_uzytkownik,))
                    conn.commit()
                    cur.close()
                    conn.close()
                    st.success("Konto skasowane z bazy!")
                    st.rerun()

        st.markdown("---")
        # Opcja 3: Kompleksowa zmiana własnych danych (Administratora)
        st.markdown("**Twoje własne konto (Administrator):**")
        moj_nowy_login = st.text_input("Twój nowy login admina", value=USER_LOGIN, key="admin_login_new")
        moje_nowe_haslo = st.text_input("Twoje nowe hasło admina (zostaw puste, aby nie zmieniać)", type="password", key="admin_pass")
        
        if st.button("ZAKTUALIZUJ MOJE DANE DOSTĘPOWE"):
            if moj_nowy_login:
                conn = pobierz_polaczenie_db()
                cur = conn.cursor()
                try:
                    if moje_nowe_haslo:
                        # Zmiana loginu i hasła jednocześnie
                        h_hash = hashlib.sha256(moje_nowe_haslo.encode()).hexdigest()
                        cur.execute(
                            "UPDATE uzytkownicy SET login = %s, haslo_hash = %s WHERE id = %s",
                            (moj_nowy_login, h_hash, USER_ID)
                        )
                    else:
                        # Zmiana tylko samego loginu
                        cur.execute(
                            "UPDATE uzytkownicy SET login = %s WHERE id = %s",
                            (moj_nowy_login, USER_ID)
                        )
                    
                    conn.commit()
                    
                    # Aktualizacja pamięci podręcznej Streamlit w locie
                    st.session_state.user_auth["login"] = moj_nowy_login
                    st.success("Dane administratora zostały pomyślnie zaktualizowane!")
                    st.rerun()
                    
                except psycopg2.errors.UniqueViolation:
                    st.error("Ten login jest już zajęty przez innego użytkownika!")
                    conn.rollback()
                finally:
                    cur.close()
                    conn.close()

# SEKCJA PLIKÓW I SYSTEMU
st.title("⚡ Agent V11: Multi-User System")
st.caption("Napędzany: Llama 3.3 Turbo | Baza Danych: Neon Cloud (PostgreSQL)")

if "doc_memory" not in st.session_state: st.session_state.doc_memory = ""
if "img_memory" not in st.session_state: st.session_state.img_memory = None

with st.sidebar:
    st.markdown("---")
    st.subheader("👁️ Załaduj dokumentację")
    uploaded_file = st.file_uploader("Dodaj PDF, TXT lub Zdjęcie (JPG/PNG)", type=['pdf', 'txt', 'png', 'jpg', 'jpeg'])
    if uploaded_file:
        if uploaded_file.type == "application/pdf":
            reader = PyPDF2.PdfReader(uploaded_file)
            st.session_state.doc_memory = "".join([page.extract_text() for page in reader.pages])
            st.session_state.img_memory = None
            st.success("Dokument wgrany!")
        elif uploaded_file.type.startswith('image'):
            st.session_state.img_memory = base64.b64encode(uploaded_file.read()).decode('utf-8')
            st.session_state.doc_memory = ""
            st.success("Obraz wgrany!")
        else:
            st.session_state.doc_memory = uploaded_file.read().decode("utf-8")
            st.session_state.img_memory = None
            st.success("Tekst wgrany!")

    if st.button("🗑️ Wyczyść pamięć podręczną pliku"):
        st.session_state.doc_memory = ""
        st.session_state.img_memory = None
        st.success("Wyczyszczono pamięć dokumentów.")

    if st.button("🧹 Resetuj moją historię rozmów"):
        wyczysc_historie_db(USER_ID)
        st.success("Historia wyczyszczona z bazy!")
        st.rerun()

# Ładowanie historii zalogowanego użytkownika bezpośrednio z PostgreSQL
historia_czatu = pobierz_historie_db(USER_ID)

# ==========================================
# 6. LOGIKA OBSŁUGI CZATU I PLIKÓW
# ==========================================
for msg in historia_czatu:
    if msg["role"] == "user" and ("KONTEKST DOKUMENTU:" in str(msg["content"]) or "Oto informacje pobrane z internetu" in str(msg["content"])):
        continue
    with st.chat_message(msg["role"]):
        text = str(msg["content"])
        if "GENERATE_" in text: text = text.split("GENERATE_")[0].strip()
        if text: st.markdown(text)

polecenie = st.chat_input("Zadaj pytanie Agentowi...")

if polecenie:
    # Zapisujemy czyste pytanie użytkownika w bazie danych
    zapisz_wiadomosc_db(USER_ID, "user", polecenie)
    with st.chat_message("user"): st.markdown(polecenie)
        
    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_response = ""
        
        # Przygotowanie pamięci kontekstowej dla API
        instrukcja_sys = (
            "Jesteś elitarnym Agentem AI. Zawsze używaj języka polskiego.\n"
            "1. Aktualności/Pogoda: Odpowiedz TYLKO 'SEARCH_WEB: [zapytanie]'.\n"
            "2. Obrazy: Na końcu wypowiedzi dodaj 'GENERATE_IMAGE: [prompt angielski]'.\n"
            "3. Excel: Jeśli użytkownik chce tabelę, dodaj 'GENERATE_EXCEL:' a pod nim czysty CSV rozdzielany średnikami.\n"
            "4. PDF: Jeśli użytkownik chce plik PDF, dodaj 'GENERATE_PDF:' a pod nim czysty tekst dokumentu."
        )
        api_messages = [{"role": "system", "content": instrukcja_sys}] + historia_czatu
        
        if st.session_state.img_memory:
            api_messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": polecenie},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{st.session_state.img_memory}"}}
                ]
            })
        elif st.session_state.doc_memory:
            api_messages.append({"role": "user", "content": f"KONTEKST DOKUMENTU:\n{st.session_state.doc_memory}\n\nPYTANIE: {polecenie}"})
        else:
            api_messages.append({"role": "user", "content": polecenie})

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
            
            # Trwały zapis odpowiedzi bota do bazy danych Neon
            zapisz_wiadomosc_db(USER_ID, "assistant", full_response)
            
            # WYZWALACZE MULTIMEDIALNE
            if "GENERATE_IMAGE:" in full_response:
                prompt = full_response.split("GENERATE_IMAGE:")[1].split("GENERATE_")[0].strip()
                st.image(f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}?width=1024&height=1024&nologo=true")
                
            if "GENERATE_EXCEL:" in full_response:
                dane_csv = full_response.split("GENERATE_EXCEL:")[1].split("GENERATE_")[0].strip()
                df = pd.read_csv(io.StringIO(dane_csv), sep=";")
                buffer = io.BytesIO()
                df.to_excel(buffer, index=False, engine='openpyxl')
                st.download_button(label="📊 Pobierz plik Excel", data=buffer.getvalue(), file_name="Arkusz_Agent.xlsx", mime="application/vnd.ms-excel")

            if "GENERATE_PDF:" in full_response:
                tekst_pdf = full_response.split("GENERATE_PDF:")[1].split("GENERATE_")[0].strip()
                czysty_tekst = unicodedata.normalize('NFKD', tekst_pdf).encode('ascii', 'ignore').decode('utf-8')
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Arial", size=12)
                pdf.multi_cell(0, 10, txt=czysty_tekst)
                st.download_button(label="📄 Pobierz plik PDF", data=pdf.output(dest='S').encode('latin1'), file_name="Dokument_Agent.pdf", mime="application/pdf")
                
        except Exception as e:
            st.error(f"Problem operacyjny: {e}")
