"""
Holos Vision Edge Pipeline — Agent 6
Video walkthrough → per-room item inventory.

Architecture:
  Video → PyAV scene extraction → pHash dedup → parallel Gemini classify
       → cross-frame item merge → auto-save high-confidence items

No system dependencies required (PyAV bundles libav codecs for Windows/Mac/Linux).

Run:
    uvicorn backend_v2.main:app --port 8000 --reload
    POST /v2/scan/video  (multipart, returns scan_id immediately)
    GET  /v2/scan/{scan_id}/status  (poll until status == "completed")
"""
