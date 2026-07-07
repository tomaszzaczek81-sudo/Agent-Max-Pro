import streamlit as st
import urllib.parse
import urllib.request
import PyPDF2
import re
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
# 2. MIKROSILNIK WYSZUKIWANIA (Anty-Bot)
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
            'Accept-Language': 'pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7'
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
        
    if not wynik:
        return "Brak dostępu do zewnętrznych serwisów."
    return wynik

# ==========================================
# 3. KONFIGURACJA MÓZGU AI (GROQ - Llama 3)
# ==========================================
client = Groq(api_key=st.secrets["GROQ_API_KEY"])
MODEL_NAME = "llama-3.3-70b-versatile"
instrukcja = (
    "Jesteś elitarnym Agentem AI. Zawsze odpowiadaj w języku polskim. "
    "1. Jeśli użytkownik pyta o aktualne wydarzenia, pogodę, fakty, odpowiedz TYLKO jednym znacznikiem w nowej linii: 'SEARCH_WEB: [zapytanie]'. "
    "2. Jeśli prosi o grafikę, dodaj na końcu: 'GENERATE_IMAGE: [prompt angielski]'. "
    "3. W innych przypadkach odpowiadaj normalnie, precyzyjnie i technicznie."
)

# ==========================================
# 4. INTERFEJS I PAMIĘĆ LOKALNA
# ==========================================
st.sidebar.title("Witaj, Szefie! 👑")
if st.sidebar.button("Wyloguj", type="secondary"):
    st.session_state.zalogowany = False
    st.rerun()

st.title("⚡ Wszechstronny Agent AI Max Pro (Groq V8)")
st.caption("Moduły: Llama 3 Turbo | Niezależna Wyszukiwarka | Generator Grafiki 4K")

if "doc_memory" not in st.session_state: st.session_state.doc_memory = ""
with st.sidebar:
    st.markdown("---")
    st.subheader("🧠 Pamięć długotrwała")
    uploaded_file = st.file_uploader("Wgraj plik (PDF/TXT)", type=['pdf', 'txt'])
    if uploaded_file:
        try:
            if uploaded_file.type == "application/pdf":
                reader = PyPDF2.PdfReader(uploaded_file)
                st.session_state.doc_memory = "".join([page.extract_text() for page in reader.pages])
            else:
                st.session_state.doc_memory = uploaded_file.read().decode("utf-8")
            st.success("Dokument wgrany do pamięci!")
        except:
            st.error("Błąd odczytu pliku.")

if "chat_session" not in st.session_state:
    st.session_state.chat_session = [{"role": "system", "content": instrukcja}]

# ==========================================
# 5. SILNIK LOGIKI I STREAMINGU GROQ
# ==========================================
for msg in st.session_state.chat_session:
    if msg["role"] == "system": continue
    if msg["role"] == "user" and ("Oto informacje pobrane z internetu" in msg["content"] or "KONTEKST Z WGRANEGO PLIKU" in msg["content"]): continue
    
    with st.chat_message(msg["role"]):
        text = msg["content"]
        if "GENERATE_IMAGE:" in text: text = text.split("GENERATE_IMAGE:")[0].strip()
        if "SEARCH_WEB:" in text: text = text.split("SEARCH_WEB:")[0].strip()
        if text: st.markdown(text)

polecenie = st.chat_input("Napisz polecenie, zapytaj o wiadomości lub stwórz grafikę...")

if polecenie:
    zapytanie_wysylane = polecenie
    if st.session_state.doc_memory:
        zapytanie_wysylane = f"KONTEKST Z WGRANEGO PLIKU: {st.session_state.doc_memory}\n\nPYTANIE UŻYTKOWNIKA: {polecenie}"
        
    st.session_state.chat_session.append({"role": "user", "content": zapytanie_wysylane})
    with st.chat_message("user"): st.markdown(polecenie)
        
    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_response = ""
        
        try:
            stream = client.chat.completions.create(
                model=MODEL_NAME,
                messages=st.session_state.chat_session,
                stream=True,
                temperature=0.5
            )
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    full_response += chunk.choices[0].delta.content
                    widoczny_tekst = full_response.split("GENERATE_IMAGE:")[0].split("SEARCH_WEB:")[0]
                    placeholder.markdown(widoczny_tekst + "▌")
            
            widoczny_tekst = full_response.split("GENERATE_IMAGE:")[0].split("SEARCH_WEB:")[0].strip()
            placeholder.markdown(widoczny_tekst)
            st.session_state.chat_session.append({"role": "assistant", "content": full_response})
            
            # Wyzwalacz Grafiki
            if "GENERATE_IMAGE:" in full_response:
                try:
                    prompt = full_response.split("GENERATE_IMAGE:")[1].strip()
                    with st.spinner("🎨 Renderowanie grafiki 4K..."):
                        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}?width=1920&height=1080&nologo=true&enhance=true"
                        st.image(url, caption=f"Prompt: {prompt}", use_column_width=True)
                except:
                    st.error("Błąd generowania obrazu.")
                    
            # Wyzwalacz Wyszukiwarki
            elif "SEARCH_WEB:" in full_response:
                haslo_szukane = full_response.split("SEARCH_WEB:")[1].strip()
                with st.spinner(f"🌐 Skanuję sieć błyskawicznie: '{haslo_szukane}'..."):
                    dane_z_sieci = bezpieczne_wyszukiwanie(haslo_szukane)
                    nowy_prompt = f"Oto informacje pobrane z internetu dla '{haslo_szukane}':\n\n{dane_z_sieci}\n\nOdpowiedz na moje pytanie bazując na tych danych."
                    st.session_state.chat_session.append({"role": "user", "content": nowy_prompt})
                    
                    odpowiedz_z_sieci = client.chat.completions.create(
                        model=MODEL_NAME,
                        messages=st.session_state.chat_session,
                        stream=True
                    )
                    pelna_odpowiedz_siec = ""
                    for chunk in odpowiedz_z_sieci:
                        if chunk.choices[0].delta.content:
                            pelna_odpowiedz_siec += chunk.choices[0].delta.content
                            placeholder.markdown(pelna_odpowiedz_siec + "▌")
                    placeholder.markdown(pelna_odpowiedz_siec)
                    st.session_state.chat_session.append({"role": "assistant", "content": pelna_odpowiedz_siec})
                    
        except Exception as e:
            st.error(f"System napotkał problem: {e}")
