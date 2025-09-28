# app.py
"""
YouTube Transcript → English Notes + Q&A (Fixed)
"""

import os
import re
import shutil
import tempfile
import traceback
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen, Request
import streamlit as st
from dotenv import load_dotenv

# ===== Load ENV =====
load_dotenv()

HAS_TRANSCRIPT_API = HAS_YTDLP = HAS_WHISPER = HAS_GENAI = False
try:
    from youtube_transcript_api import YouTubeTranscriptApi; HAS_TRANSCRIPT_API = True
except: pass
try:
    import yt_dlp; HAS_YTDLP = True
except: pass
try:
    import whisper; HAS_WHISPER = True
except: pass
try:
    import google.generativeai as genai; HAS_GENAI = True
except: pass

# ===== Gemini =====
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GENAI_API_KEY")
if HAS_GENAI and GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

GENAI_MODEL = os.getenv("GENAI_MODEL", "gemini-1.5-flash-001")

PROMPT = """You are an expert multilingual video summarizer.
Translate transcript to English if needed and summarize in 200–250 words
highlighting the key points, tone, and insights.

Transcript:
"""

# ---------- Utilities ----------
def extract_video_id(url: str):
    if not url: return None
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()

    if "youtu.be" in netloc:
        return parsed.path.lstrip("/").split("?")[0]
    if "youtube.com" in netloc or "youtube-nocookie.com" in netloc:
        if parsed.path.startswith("/shorts/"):
            return parsed.path.split("/shorts/")[-1].strip("/")
        qs = parse_qs(parsed.query)
        if "v" in qs:
            return qs["v"][0]
        parts = parsed.path.strip("/").split("/")
        if parts:
            return parts[-1]

    import re
    m = re.search(r"([a-zA-Z0-9_-]{11})", url)
    return m.group(1) if m else None

def check_thumbnail_url(vid):
    thumbs = [
        f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg",
        f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
        f"https://i.ytimg.com/vi/{vid}/default.jpg",
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    from urllib.request import Request, urlopen
    for url in thumbs:
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=5) as resp:
                if getattr(resp, "status", 200) == 200:
                    return url
        except:
            continue
    return None

def ffmpeg_exists():
    return shutil.which("ffmpeg") is not None

# ---------- Transcript ----------
def extract_transcript_via_api(url):
    if not HAS_TRANSCRIPT_API: return None, None
    vid = extract_video_id(url)
    if not vid: return None, None
    try:
        t = YouTubeTranscriptApi.get_transcript(vid)
        txt = " ".join([seg.get("text", "") for seg in t]).strip()
        return txt, "en"
    except:
        return None, None

def extract_transcript_with_whisper(url, model_name="base"):
    if not (HAS_YTDLP and HAS_WHISPER): return None, None
    if not ffmpeg_exists():
        st.error("FFmpeg not installed.")
        return None, None
    import yt_dlp, whisper
    tempdir = tempfile.mkdtemp(prefix="ytt_")
    outtmpl = os.path.join(tempdir, "audio.%(ext)s")
    opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [{"key": "FFmpegExtractAudio","preferredcodec":"mp3","preferredquality":"192"}],
    }
    if os.path.exists("cookies.txt"):
        opts["cookiefile"] = "cookies.txt"
    try:
        with st.spinner("🔻 Downloading audio…"):
            with yt_dlp.YoutubeDL(opts) as y:
                y.download([url])
        audio = None
        for f in os.listdir(tempdir):
            if f.lower().endswith((".mp3",".m4a",".webm",".wav",".ogg")):
                audio = os.path.join(tempdir, f); break
        if not audio: raise FileNotFoundError("Audio download failed.")
        with st.spinner("🔎 Transcribing…"):
            model = whisper.load_model(model_name)
            r = model.transcribe(audio)
            return r.get("text","").strip(), r.get("language","unknown")
    except Exception as e:
        st.error(f"Whisper failed: {e}")
        st.code(traceback.format_exc())
        return None, None
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)

# ---------- Summarizer ----------
def simple_summarize(text, max_words=250):
    import re
    text = re.sub(r"\s+"," ", text).strip()
    w = text.split()
    return text if len(w)<=max_words else " ".join(w[:max_words])+"..."

def generate_summary(text):
    if not text: return ""
    if HAS_GENAI and GOOGLE_API_KEY:
        try:
            model = genai.GenerativeModel(GENAI_MODEL)
            resp = model.generate_content(PROMPT + text[:15000])
            return getattr(resp,"text",str(resp))
        except Exception as e:
            st.warning(f"Gemini failed → using local summarizer. ({e})")
            return simple_summarize(text)
    return simple_summarize(text)

# ---------- Q&A ----------
def answer_question(transcript, question):
    """Use Gemini to answer a user question about the transcript."""
    if not question.strip():
        return "Please enter a question."
    if HAS_GENAI and GOOGLE_API_KEY:
        try:
            model = genai.GenerativeModel(GENAI_MODEL)
            prompt = f"Answer the following question based ONLY on the transcript of the YouTube video:\n\nTranscript:\n{transcript[:12000]}\n\nQuestion: {question}\nAnswer clearly in English:"
            resp = model.generate_content(prompt)
            return getattr(resp,"text",str(resp))
        except Exception as e:
            return f"AI could not answer: {e}"
    return "Q&A requires Gemini API."

# ---------- UI ----------
st.set_page_config(page_title="YT → English Notes + Q&A", layout="centered")

# --- CSS ---
st.markdown("""
<style>
    body {background: #f4f5fa;}
    .main-title{
        text-align:center;
        font-size:2.6rem;
        font-weight:800;
        background: linear-gradient(90deg,#6a11cb,#2575fc);
        -webkit-background-clip:text;
        color:transparent;
    }
    .tagline{
        text-align:center;
        font-size:1.1rem;
        color:#555;
        margin-bottom:2rem;
    }
    .stTextInput>div>div>input{
        border-radius:12px;
        border:2px solid #6a11cb;
        padding:0.6rem 1rem;
        font-size:1rem;
    }
    .stButton>button{
        background:linear-gradient(90deg,#6a11cb,#2575fc);
        color:white;
        border:none;
        border-radius:10px;
        padding:0.6rem 1.2rem;
        font-weight:600;
        font-size:1rem;
        box-shadow:0 3px 6px rgba(0,0,0,0.2);
    }
    .stButton>button:hover{
        transform:scale(1.05);
        background:linear-gradient(90deg,#7b2ef5,#3696ff);
    }
    .card-block{
        background:white;
        padding:1.5rem;
        margin-top:1rem;
        border-radius:12px;
        box-shadow:0 4px 12px rgba(0,0,0,0.1);
    }
</style>
""", unsafe_allow_html=True)

# --- Header ---
st.markdown("<h1 class='main-title'>YouTube Transcript → English Notes</h1>", unsafe_allow_html=True)
st.markdown("<p class='tagline'>✨ Paste a YouTube link and get clean, AI-powered English notes instantly!</p>", unsafe_allow_html=True)

# --- Initialize session state ---
if "summary" not in st.session_state:
    st.session_state.summary = ""
if "transcript" not in st.session_state:
    st.session_state.transcript = ""

# --- Input ---
col1,col2 = st.columns([4,1.2])
with col1:
    yt_link = st.text_input("Paste YouTube / Shorts link:")
with col2:
    go = st.button("Summarize 🚀", use_container_width=True)

thumb = None
if yt_link.strip():
    vid = extract_video_id(yt_link)
    if vid: thumb = check_thumbnail_url(vid)
if thumb:
    st.image(thumb, use_container_width=True)

# --- Summarization ---
if go:
    if not yt_link:
        st.error("Please enter a link.")
    else:
        with st.spinner("⏳ Extracting transcript…"):
            text, lang = extract_transcript_via_api(yt_link)
            if not text:
                st.info("No transcript available. Falling back to Whisper — this may take a bit…")
                text, lang = extract_transcript_with_whisper(yt_link, model_name=os.getenv("WHISPER_MODEL","base"))

        if not text:
            st.error("❌ Could not extract transcript or audio.")
        else:
            st.session_state.transcript = text
            st.session_state.summary = generate_summary(text)
            st.success(f"✅ Transcript extracted — Detected language: **{lang or 'unknown'}**")

# --- Display Summary ---
if st.session_state.summary:
    st.markdown("<div class='card-block'>", unsafe_allow_html=True)
    st.markdown("## ✨ Summary")
    st.write(st.session_state.summary)
    st.markdown("</div>", unsafe_allow_html=True)

# --- Display Transcript ---
if st.session_state.transcript:
    st.markdown("<div class='card-block'>", unsafe_allow_html=True)
    st.markdown("## 📄 Transcript (preview)")
    preview = st.session_state.transcript if len(st.session_state.transcript)<=1200 else st.session_state.transcript[:1200]+"..."
    st.write(preview)

    c1,c2 = st.columns([1.5,1.5])
    with c1:
        st.download_button("Download summary .txt", st.session_state.summary, "summary.txt", "text/plain", use_container_width=True)
    with c2:
        st.download_button("Download transcript .txt", st.session_state.transcript, "transcript.txt", "text/plain", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

# --- Q&A ---
if st.session_state.transcript:
    st.markdown("<div class='card-block'>", unsafe_allow_html=True)
    st.markdown("## 💬 Q&A about this Video")
    q = st.text_input("Ask a question about this video’s content:")
    if st.button("Get Answer 💡"):
        if q:
            with st.spinner("🤖 Thinking..."):
                ans = answer_question(st.session_state.transcript, q)
            st.markdown("**Answer:**")
            st.write(ans)
        else:
            st.warning("Please type a question.")
    st.markdown("</div>", unsafe_allow_html=True)
