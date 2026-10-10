# SAFERA — Women's Safety Planning Prototype

## Features
- Attractive Streamlit dashboard and safety checklist
- Route risk estimate based on selected time, weather, and route familiarity
- Emergency resource lookup through OpenStreetMap
- Local route-risk history
- SOS message preparation demo
- Voice-input guidance and weather placeholder

## Run on Windows / VS Code
1. Extract the ZIP.
2. Open `SAFERA_project` in VS Code.
3. Open Terminal → New Terminal.
4. Run `python -m venv .venv`
5. Activate in PowerShell: `\.venv\Scripts\Activate.ps1`
   Or Git Bash: `source .venv/Scripts/activate`
6. Install: `python -m pip install --upgrade pip`
7. Install packages: `python -m pip install -r requirements.txt`
8. Run: `python -m streamlit run app.py`
9. Open `http://localhost:8501` (or the URL shown in the terminal). Keep terminal open; press Ctrl+C to stop.

## Important safety notes
This is an educational prototype. Route scoring is heuristic, not trained AI, and does not use verified crime reports. The SOS demo does not send SMS or contact emergency services. A website cannot reliably detect triple presses of the hardware power button; native Android/iOS integration is required. Weather is not live-connected. OpenStreetMap data may be incomplete or outdated. Do not rely on this demo during an emergency or treat a score as a safety guarantee.

For real-world deployment, build a native mobile app, secure backend, credible validated data pipeline, approved messaging integration, and complete privacy/safety testing.
