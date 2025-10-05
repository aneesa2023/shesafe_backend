from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from jose import jwt
import requests
import os
import shutil
from dotenv import load_dotenv

from schemas import IncidentCreate
from utils import transcribe_audio
from elevenlabs import ElevenLabs
import google.generativeai as genai

# ---------- Load Environment Variables ----------
load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
if not ELEVENLABS_API_KEY:
    raise RuntimeError("ELEVENLABS_API_KEY not set in environment or .env file")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY not set in environment or .env file")

AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")
AUTH0_AUDIENCE = os.getenv("AUTH0_AUDIENCE")
if not AUTH0_DOMAIN or not AUTH0_AUDIENCE:
    raise RuntimeError("Auth0 domain or audience not set")

# ---------- Config ----------
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ElevenLabs client
eleven_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# Gemini client
genai.configure(api_key=GEMINI_API_KEY)
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

# models.py or inside the same file (below Incident class)
class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, nullable=False)
    sender = Column(String, nullable=False)  # "user" or "ai"
    text = Column(Text, nullable=False)
Base.metadata.create_all(engine)

# ---------- FastAPI App ----------
app = FastAPI(title="SheSafe Backend")

# ---------- CORS ----------
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "*"
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
                "e": key["e"]
            }
    if not rsa_key:
        raise HTTPException(status_code=401, detail="Invalid token")

    payload = jwt.decode(
        token,
        rsa_key,
        algorithms=["RS256"],
        audience=AUTH0_AUDIENCE,
        issuer=f"https://{AUTH0_DOMAIN}/"
    )
    return payload["sub"]  # Auth0 user_id

# ---------- Endpoints ----------


# @app.post("/incident/text")
# async def create_text_incident(incident: IncidentCreate):
#     db = SessionLocal()
#     record = Incident(user_id="test-user", text=incident.text, type="text")
#     db.add(record)
#     db.commit()
#     db.close()
#     return {"status": "success", "message": "Incident reported"}

@app.post("/incident/text")
async def create_text_incident(
    incident: IncidentCreate, 
    user_id: str = Depends(get_current_user)
):
    db = SessionLocal()
    record = Incident(user_id=user_id, text=incident.text, type="text")
    db.add(record)
    db.commit()
    db.close()
    print(f"New text incident from user {user_id}: {incident.text}")
    return {"status": "success", "message": "Incident reported"}

@app.post("/incident/audio")
async def create_audio_incident(file: UploadFile = File(...), user_id: str = Depends(get_current_user)):
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
    
# ---------- Auth0 Management API ----------

def get_management_api_token():
    """
    Get Auth0 Management API token using client credentials.
    Ensure your Auth0 app has a 'Client Grant' for the Management API with 'read:users' scope.
    """
    url = f"https://{AUTH0_DOMAIN}/oauth/token"
    data = {
        "client_id": os.getenv("AUTH0_CLIENT_ID"),
        "client_secret": os.getenv("AUTH0_CLIENT_SECRET"),
        "audience": f"https://{AUTH0_DOMAIN}/api/v2/",
        "grant_type": "client_credentials"
    }
    try:
        response = requests.post(url, json=data)
        response.raise_for_status()
        return response.json()["access_token"]
    except requests.HTTPError:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Auth0 Management API token error: {response.text}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token generation failed: {str(e)}")


def fetch_auth0_users():
    """
    Fetch all users from Auth0 Management API.
    """
    token = get_management_api_token()
    url = f"https://{AUTH0_DOMAIN}/api/v2/users"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.HTTPError:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Auth0 fetch users error: {response.text}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fetching users failed: {str(e)}")

@app.get("/users")
def list_users():
    """
    List all Auth0 users.
    """
    try:
        users = fetch_auth0_users()
        return [
            {
                "user_id": user.get("user_id"),
                "email": user.get("email"),
                "name": user.get("name"),
                "created_at": user.get("created_at")
            }
            for user in users
        ]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    
@app.post("/incident/analyze-text")
async def analyze_incident_text(text: str = Form(...)):
    """
    Analyze an incident immediately based on its text.
    Returns: summary, severity, recommendation
    """
    try:
        prompt = f"""
        You are an AI safety assistant. Analyze this incident report:

        Incident: {text}

        Tasks:
        1. Summarize the report in 2-3 sentences.
        2. Classify severity (low, medium, high).
        3. Suggest recommended next steps for safety or reporting.
        """
        response = gemini_model.generate_content(prompt)
        analysis = response.text

        # Optional: parse structured output
        lines = [l.strip() for l in analysis.split("\n") if l.strip()]
        summary = lines[0].replace("Summary:", "").strip() if len(lines) > 0 else ""
        severity = lines[1].replace("Severity:", "").strip() if len(lines) > 1 else "medium"
        recommendation = lines[2].replace("Recommendation:", "").strip() if len(lines) > 2 else ""

        return {
            "status": "success",
            "summary": summary,
            "severity": severity,
            "recommendation": recommendation
        }

    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
    
@app.post("/incident/follow-up")
async def follow_up_incident(payload: dict):
    incident_id = payload.get("incidentId")
    follow_up_text = payload.get("followUp")
    conversation = payload.get("conversation", [])

    db = SessionLocal()
    record = db.query(Incident).filter(Incident.id == incident_id).first()
    db.close()
    if not record:
        return {"status": "error", "message": "Incident not found"}

    # Combine previous AI + user conversation for context
    context_text = record.text + "\n"
    for turn in conversation:
        context_text += f"User: {turn['user']}\nAI: {turn['ai']}\n"
    context_text += f"User follow-up: {follow_up_text}\n"

    try:
        prompt = f"""
        You are an AI safety assistant. Continue the conversation based on previous incident analysis.

        Context: {context_text}

        Provide a clear and actionable answer to the follow-up.
        """
        response = gemini_model.generate_content(prompt)
        answer = response.text

        return {"status": "success", "answer": answer}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
@app.post("/chat")
async def chat_with_gemini(payload: dict):
    try:
        user_message = payload.get("message", "")
        history = payload.get("history", [])
        incident_id = payload.get("incidentId")

        if not user_message:
            return JSONResponse({"status": "error", "message": "Message is required"}, status_code=400)

        # Format chat history for context
        chat_context = ""
        for turn in history[-6:]:
            chat_context += f"{turn['sender'].capitalize()}: {turn['text']}\n"
        chat_context += f"User: {user_message}\n"

        prompt = f"""
        You are an empathetic AI safety assistant for women. 
        Be clear, kind, and supportive. 
        Respond conversationally, not as a list.

        Conversation so far:
        {chat_context}

        Respond in a short, natural message.
        """

        response = gemini_model.generate_content(prompt)
        ai_text = response.text.strip()

        # --- Store messages in database ---
        db = SessionLocal()
        if incident_id:
            db.add(Conversation(incident_id=incident_id, sender="user", text=user_message))
            db.add(Conversation(incident_id=incident_id, sender="ai", text=ai_text))
            db.commit()
        db.close()

        return {"status": "success", "reply": ai_text}

    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
    
@app.get("/incident/{incident_id}/chat")
async def get_incident_chat(incident_id: int):
    db = SessionLocal()
    messages = db.query(Conversation).filter(Conversation.incident_id == incident_id).all()
    db.close()
    return [
        {"sender": msg.sender, "text": msg.text, "id": msg.id}
        for msg in messages
    ]