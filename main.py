from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from schemas import IncidentCreate
from utils import transcribe_audio

import os
import shutil
from dotenv import load_dotenv

from elevenlabs import ElevenLabs  # ElevenLabs SDK
import google.generativeai as genai  # Gemini SDK

from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

import jwt
import requests

# ---------- Load Environment Variables ----------
load_dotenv()
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
AUTH0_DOMAIN = os.environ.get("AUTH0_DOMAIN")  # e.g., "your-tenant.us.auth0.com"
API_AUDIENCE = os.environ.get("API_AUDIENCE")  # Your API Identifier from Auth0

if not ELEVENLABS_API_KEY or not GEMINI_API_KEY or not AUTH0_DOMAIN or not API_AUDIENCE:
    raise RuntimeError("One or more environment variables missing (ELEVENLABS_API_KEY, GEMINI_API_KEY, AUTH0_DOMAIN, API_AUDIENCE)")

# ---------- Config ----------
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ElevenLabs client
eleven_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# Gemini client
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-2.5-flash")

# Database setup
Base = declarative_base()
engine = create_engine("sqlite:///shesafe.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)

class Incident(Base):
    __tablename__ = "incidents"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, nullable=False)
    text = Column(Text, nullable=False)
    type = Column(String, nullable=False)  # "text" or "audio"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=True)

Base.metadata.create_all(engine)

# ---------- FastAPI App ----------
app = FastAPI(title="SheSafe Backend")

# ---------- CORS ----------
origins = [
    "http://localhost:3000",  # React
    "http://127.0.0.1:3000",
    "http://localhost:8000",  # Flutter dev
    "*",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Auth0 JWT ----------
security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        # Fetch Auth0 JWKS and verify token
        jwks_url = f"https://{AUTH0_DOMAIN}/.well-known/jwks.json"
        jwks = requests.get(jwks_url).json()
        unverified_header = jwt.get_unverified_header(token)
        rsa_key = {}
        for key in jwks["keys"]:
            if key["kid"] == unverified_header["kid"]:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"],
                }
        if not rsa_key:
            raise HTTPException(status_code=401, detail="Unable to find appropriate key")
        payload = jwt.decode(token, rsa_key, algorithms=["RS256"], audience=API_AUDIENCE, issuer=f"https://{AUTH0_DOMAIN}/")
        return payload["sub"]  # Auth0 user ID
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

# ---------- Endpoints ----------

@app.post("/incident/text")
async def create_text_incident(incident: IncidentCreate, user_id: str = Depends(get_current_user)):
    db = SessionLocal()
    record = Incident(user_id=user_id, text=incident.text, type="text")
    db.add(record)
    db.commit()
    db.close()
    print(f"New text incident from user {user_id}: {incident.text}")
    return JSONResponse({"status": "success", "message": "Incident reported"})

@app.post("/incident/audio")
async def create_audio_incident(user_id: str = Depends(get_current_user), file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    try:
        text = transcribe_audio(file_path)
        db = SessionLocal()
        record = Incident(user_id=user_id, text=text, type="audio")
        db.add(record)
        db.commit()
        db.close()
        print(f"Audio incident from user {user_id}: {text}")
    finally:
        os.remove(file_path)
    return JSONResponse({"status": "success", "transcribed_text": text})

@app.post("/incident/text-to-speech")
async def text_to_speech_incident(text: str = Form(...), user_id: str = Depends(get_current_user)):
    try:
        response = eleven_client.generate(
            voice="Rachel",
            model="eleven_multilingual_v2",
            text=text
        )
        audio_bytes = b"".join(response)
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
    file_name = f"{user_id}_incident.mp3"
    file_path = os.path.join(UPLOAD_DIR, file_name)
    with open(file_path, "wb") as f:
        f.write(audio_bytes)
    return JSONResponse({"status": "success", "file": file_name})

@app.get("/incidents")
async def get_incidents(user_id: str = Depends(get_current_user)):
    db = SessionLocal()
    records = db.query(Incident).filter(Incident.user_id == user_id).all()
    db.close()
    return [{"id": r.id, "user_id": r.user_id, "text": r.text, "type": r.type} for r in records]

@app.get("/voices")
async def list_voices():
    try:
        voices = eleven_client.voices.get_all()
        return [{"id": v.voice_id, "name": v.name} for v in voices.voices]
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.post("/incident/analyze")
async def analyze_incident(incident_id: int = Form(...), user_id: str = Depends(get_current_user)):
    db = SessionLocal()
    record = db.query(Incident).filter(Incident.id == incident_id, Incident.user_id == user_id).first()
    db.close()
    if not record:
        return JSONResponse({"status": "error", "message": "Incident not found"}, status_code=404)
    try:
        prompt = f"""
        You are an AI safety assistant. Analyze this incident report:

        Incident: {record.text}

        Tasks:
        1. Summarize the report in 2-3 sentences.
        2. Classify severity (low, medium, high).
        3. Suggest recommended next steps for safety or reporting.
        """
        response = gemini_model.generate_content(prompt)
        analysis = response.text
        return {"status": "success", "incident_id": record.id, "analysis": analysis}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.get("/users")
def list_users():
    db = SessionLocal()
    users = db.query(User).all()
    db.close()
    return [{"user_id": u.id, "username": u.username, "email": u.email} for u in users]