# 🛟 CrisisCompanion Backend

CrisisCompanion is an AI-powered emergency analysis platform designed to assist during crisis or overload situations.  
It uses **Google Gemini AI** and **Snowflake APIs** to analyze, prioritize, and summarize emergency incident reports in real time.

This repository contains the **backend server** built with **Node.js + Express**, integrating **Gemini API** for AI analysis and **Snowflake API** for intelligent ranking.

---

## 🚀 Features

- Accepts and stores emergency incident reports (text/audio converted to text)
- Analyzes incidents instantly using **Gemini 1.5 Flash**
- Classifies severity and recommends next steps using AI
- Uses **Snowflake API** to rank and summarize bulk incidents
- Provides REST APIs for frontend apps and admin dashboards

---

## 🧩 Tech Stack

| Component | Technology |
|------------|-------------|
| Backend Framework | Node.js (Express) |
| AI Model | Google Gemini 1.5 Flash |
| Data Storage | JSON (or MongoDB / Snowflake optional) |
| API Calls | Axios / Fetch |
| Hosting (Optional) | Render / Vercel / AWS EC2 |

---

## ⚙️ Project Setup

### 1. Clone the repository
```bash
git clone https://github.com/<your-username>/crisiscompanion-backend.git
cd crisiscompanion-backend

2) install Dependencies
npm install

3. Add environment variables

Create a .env file in the root directory and add:

PORT=5000
GEMINI_API_KEY=your_gemini_api_key_here
SNOWFLAKE_API_KEY=your_snowflake_api_key_here

npm run dev

Server runs at:
👉 http://localhost:5000

⸻

📡 API Endpoints

POST /analyze

Analyze a new incident report.

Request Body:

{
  "incidentId": "INC-123",
  "text": "A car accident occurred at Main Street with minor injuries."
}

{
  "summary": "A minor car accident occurred at Main Street.",
  "severity": "Medium",
  "recommended_actions": [
    "Ensure the area is safe.",
    "Call emergency responders.",
    "Collect eyewitness details."
  ]
}
