import google.generativeai as genai
from dotenv import load_dotenv
import os

load_dotenv()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

def list_models():
    models = genai.list_models()
    for m in models:
        print(m.name, m.supported_generation_methods)

if __name__ == "__main__":
    list_models()