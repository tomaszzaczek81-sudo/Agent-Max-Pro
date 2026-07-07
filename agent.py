import streamlit as st
import urllib.parse
import urllib.request
import PyPDF2
import re
import base64
import pandas as pd
import io
import unicodedata
from fpdf import FPDF
from groq import Groq

# ==========================================
# 1. BEZPIECZNE LOGOWANIE
# ==========================================
st.set_page_config(page_title="Agent AI Max Pro", layout="wide", page_icon="⚡")

if "zalogowany" not in st.session_state:
    st.session_state.zalogowany = False

if not st.session_state.zalogowany:
    st.title("🔒 Logowanie do Systemu AI")
    login = st.text_input("Login")
    haslo = st.text_input("Hasło", type="password")
    if st.button("ZALOGUJ", type="primary"):
        if login == "szef" and haslo == "taniec123":
            st.session_state.zalogowany = True
            st.rerun()
        else:
            st.error("Błędny login lub hasło!")
    st.stop()

# ==========================================
# 2. MIKROSILNIK WYSZUKIWANIA
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
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept-Language': 'pl-PL,pl;q=0.9'
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=4) as res:
            html = res.read().decode('utf-8')
            snippets = re.findall(r'class="result__snippet[^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL)
            if snippets:
                wynik += "FAKTY Z INTERNETU:\n"
                for snip in snippets[:3]:
                    czysty_tekst = re.sub(r'<[^>]+>', '', snip)
                    wynik += f"- {czysty_tekst.strip()}\n"
    except: pass
    if not wynik: return "Brak dostępu do sieci."
    return wynik

# ==========================================
# 3. KONFIGURACJA MÓZGU AI
# ==========================================
client = Groq(api_key=st.secrets["GROQ_API_KEY"])
MODEL_TEXT = "llama-3.3-70b-versatile"
MODEL_VISION = "llama-3.2-11b-vision-preview"

instrukcja = (
    "Jesteś elitarnym Agentem AI. Zawsze używaj języka polskiego.\n"
    "1. Aktualności/Pogoda: Odpowiedz TYLKO 'SEARCH_WEB: [zapytanie]'.\n"
    "2. Obrazy: Na końcu wypowiedzi dodaj 'GENERATE_IMAGE: [prompt angielski]'.\n"
    "3. Excel: Jeśli użytkownik chce tabelę do pobrania, dodaj na końcu znacznik 'GENERATE_EXCEL:' a pod nim czyste dane w formacie CSV (kolumny oddzielone średnikiem, bez formatowania markdown).\n"
    "4. PDF: Jeśli użytkownik chce wygenerować plik PDF, dodaj na końcu 'GENERATE_PDF:' a pod nim czysty tekst dokumentu."
)

# ==========================================
# 4. INTERFEJS I PAMIĘĆ WIELOMODALNA
# ==========================================
st.sidebar.title("Witaj, Szefie! 👑")
if st.sidebar.button("Wyloguj", type="secondary"):
    st.session_state.zalogowany = False
    st.rerun()

st.title("⚡ Agent V10: AI, Vision & Pliki")

if "doc_memory" not in st.session_state: st.session_state.doc_memory = ""
if "img_memory" not in st.session_state: st.session_state.img_memory = None

with st.sidebar:
    st.markdown("---")
    st.subheader("👁️ Zmysły Agenta (Wgraj plik)")
    uploaded_file = st.file_uploader("Dodaj PDF, TXT lub Zdjęcie (JPG/PNG)", type=['pdf', 'txt', 'png', 'jpg', 'jpeg'])
    
    if uploaded_file:
        try:
            if uploaded_file.type == "application/pdf":
                reader = PyPDF2.PdfReader(uploaded_file)
                st.session_state.doc_memory = "".join([page.extract_text() for page in reader.pages])
                st.session_state.img_memory = None
                st.success("Dokument wczytany!")
            elif uploaded_file.type.startswith('image'):
                img_bytes = uploaded_file.read()
                st.session_state.img_memory = base64.b64encode(img_bytes).decode('utf-8')
                st.session_state.doc_memory = ""
                st.success("Obraz przeanalizowany, Agent go widzi!")
            else:
                st.session_state.doc_memory = uploaded_file.read().decode("utf-8")
                st.session_state.img_memory = None
                st.success("Tekst wczytany!")
        except:
            st.error("Błąd przetwarzania pliku.")

if "chat_session" not in st.session_state:
    st.session_state.chat_session = [{"role": "system", "content": instrukcja}]

# ==========================================
# 5. LOGIKA CZATU I GENEROWANIE PLIKÓW
# ==========================================
for msg in st.session_state.chat_session:
    if msg["role"] == "system": continue
    if "KONTEKST Z WGRANEGO PLIKU:" in str(msg["content"]): continue
    
    with st.chat_message(msg["role"]):
        text = str(msg["content"])
        if "GENERATE_" in text:
            text = text.split("GENERATE_IMAGE:")[0].split("GENERATE_EXCEL:")[0].split("GENERATE_PDF:")[0].strip()
        if text: st.markdown(text)

polecenie = st.chat_input("Napisz polecenie, wgraj zdjęcie z zadaniem lub każ stworzyć plik...")

if polecenie:
    st.session_state.chat_session.append({"role": "user", "content": polecenie})
    with st.chat_message("user"): st.markdown(polecenie)
        
    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_response = ""
        
        # Tworzenie tymczasowej wiadomości API (żeby nie zapychać RAMu wielkim base64 na stałe)
        api_messages = st.session_state.chat_session.copy()
        model_to_use = MODEL_TEXT
        
        if st.session_state.img_memory:
            model_to_use = MODEL_VISION
            api_messages[-1] = {
                "role": "user",
                "content": [
                    {"type": "text", "text": polecenie},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{st.session_state.img_memory}"}}
                ]
            }
        elif st.session_state.doc_memory:
            api_messages[-1]["content"] = f"KONTEKST DOKUMENTU:\n{st.session_state.doc_memory}\n\nPYTANIE: {polecenie}"

        try:
            stream = client.chat.completions.create(
                model=model_to_use,
                messages=api_messages,
                stream=True
            )
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    full_response += chunk.choices[0].delta.content
                    widoczny = full_response.split("GENERATE_")[0]
                    placeholder.markdown(widoczny + "▌")
            
            widoczny = full_response.split("GENERATE_")[0].strip()
            placeholder.markdown(widoczny)
            st.session_state.chat_session.append({"role": "assistant", "content": full_response})
            
            # WYZWALACZ: Grafika
            if "GENERATE_IMAGE:" in full_response:
                prompt = full_response.split("GENERATE_IMAGE:")[1].split("GENERATE_")[0].strip()
                st.image(f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}?width=1024&height=1024&nologo=true")
                
            # WYZWALACZ: Tworzenie Excela
            if "GENERATE_EXCEL:" in full_response:
                dane_csv = full_response.split("GENERATE_EXCEL:")[1].split("GENERATE_")[0].strip()
                df = pd.read_csv(io.StringIO(dane_csv), sep=";")
                buffer = io.BytesIO()
                df.to_excel(buffer, index=False, engine='openpyxl')
                st.download_button(label="📊 Pobierz plik Excel", data=buffer.getvalue(), file_name="Arkusz_Agent.xlsx", mime="application/vnd.ms-excel")

            # WYZWALACZ: Tworzenie PDF
            if "GENERATE_PDF:" in full_response:
                tekst_pdf = full_response.split("GENERATE_PDF:")[1].split("GENERATE_")[0].strip()
                # Zabezpieczenie przed polskimi znakami (standardowa czcionka PDF ich nie czyta)
                czysty_tekst = unicodedata.normalize('NFKD', tekst_pdf).encode('ascii', 'ignore').decode('utf-8')
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Arial", size=12)
                pdf.multi_cell(0, 10, txt=czysty_tekst)
                st.download_button(label="📄 Pobierz plik PDF", data=pdf.output(dest='S').encode('latin1'), file_name="Dokument_Agent.pdf", mime="application/pdf")
                
        except Exception as e:
            st.error(f"Błąd operacji: {e}")
