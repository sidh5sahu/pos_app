@echo off
echo Starting POS System...
echo Access at http://localhost:8000
echo To access from LAN, use your IP address.
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
pause
