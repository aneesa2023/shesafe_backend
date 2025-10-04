from fastapi import FastAPI, UploadFile, File, Form, Depends
from fastapi.responses import JSONResponse
from schemas import IncidentCreate
from utils import transcribe_audio
import os
import shutil
from dotenv import load_dotenv

from elevenlabs import ElevenLabs  # ElevenLabs SDK

from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

import google.generativeai as genai  # Gemini SDK

# ---------- Load Environment Variables ----------
load_dotenv()

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
if not ELEVENLABS_API_KEY:
    raise RuntimeError("ELEVENLABS_API_KEY not set in environment or .env file")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY not set in environment or .env file")

# ---------- Config ----------
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ElevenLabs client
eleven_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# Gemini client
genai.configure(api_key=GEMINI_API_KEY)
# Use correct model name that exists for your account
gemini_model = genai.GenerativeModel("models/gemini-2.5-flash")

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
    id = Column(String, primary_key=True)  # use Auth0 sub
    email = Column(String)
    name = Column(String)
    last_login = Column(String)

Base.metadata.create_all(engine)

# ---------- FastAPI App ----------
app = FastAPI(title="SheSafe Backend")

# ---------- CORS Configuration ----------
from fastapi.middleware.cors import CORSMiddleware

origins = [
    "http://localhost:3000",  # React dev server
    "http://127.0.0.1:3000",
    "http://localhost:8000",  # Flutter dev server if needed
    "*",  # Optional for testing
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

security = HTTPBearer()

# def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
#     token = credentials.credentials
#     try:
#         payload = jwt.decode(token, "SECRET_KEY", algorithms=["HS256"])
#         return payload['user_id']
#     except Exception:
#         raise HTTPException(status_code=401, detail="Invalid token")
from jose import jwt
import requests
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    jwks_url = f"https://{os.getenv('AUTH0_DOMAIN')}/.well-known/jwks.json"
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
                "e": key["e"]
            }
    if not rsa_key:
        raise HTTPException(status_code=401, detail="Invalid token")

    payload = jwt.decode(
        token,
        rsa_key,
        algorithms=["RS256"],
        audience=os.getenv("AUTH0_AUDIENCE"),
        issuer=f"https://{os.getenv('AUTH0_DOMAIN')}/"
    )
    return payload["sub"]  # This is your Auth0 user_id# ---------- Endpoints ----------

@app.post("/incident/text")
async def create_text_incident(incident: IncidentCreate, user_id: str = Depends(get_current_user)):
    db = SessionLocal()
    record = Incident(user_id=user_id, text=incident.text, type="text")
    db.add(record)
    db.commit()
    db.close()
    print(f"New text incident from user {incident.user_id}: {incident.text}")
    return JSONResponse({"status": "success", "message": "Incident reported"})

@app.post("/incident/audio")
async def create_audio_incident(user_id: str = Form(...), file: UploadFile = File(...)):
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
async def text_to_speech_incident(text: str = Form(...), user_id: str = Form(...)):
    try:
        response = eleven_client.generate(
            voice="Rachel",  # You can change this voice name or use a valid voice_id
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
async def get_incidents():
    db = SessionLocal()
    records = db.query(Incident).all()
    db.close()
    return [{"id": r.id, "user_id": r.user_id, "text": r.text, "type": r.type} for r in records]

@app.get("/voices")
async def list_voices():
    try:
        voices = eleven_client.voices.get_all()
        return [{"id": v.voice_id, "name": v.name} for v in voices.voices]
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

# ---------- Gemini Integration ----------
@app.post("/incident/analyze")
async def analyze_incident(incident_id: int = Form(...)):
    db = SessionLocal()
    record = db.query(Incident).filter(Incident.id == incident_id).first()
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

        return {
            "status": "success",
            "incident_id": record.id,
            "analysis": analysis
        }

    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
 
import requests, os

def get_auth0_token():
    url = f"https://{os.getenv('AUTH0_DOMAIN')}/oauth/token"
    data = {
        "client_id": os.getenv("AUTH0_CLIENT_ID"),
        "client_secret": os.getenv("AUTH0_CLIENT_SECRET"),
        "audience": f"https://{os.getenv('AUTH0_DOMAIN')}/api/v2/",
        "grant_type": "client_credentials"
    }
    response = requests.post(url, json=data)
    response.raise_for_status()
    return response.json()["access_token"]

def fetch_auth0_users():
    token = get_auth0_token()
    url = f"https://{os.getenv('AUTH0_DOMAIN')}/api/v2/users"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()
   
@app.get("/users")
def list_users():
    try:
        users = fetch_auth0_users()
        return [
            {
                "user_id": user["user_id"],
                "email": user.get("email"),
                "name": user.get("name"),
                "created_at": user.get("created_at")
            }
            for user in users
        ]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)