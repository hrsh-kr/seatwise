# Demo video tooling

Builds the Seatwise demo video from voice notes: slides and the live app are driven by a scripted Chrome window,
highlights and clicks are timed to the words you say (whisper.cpp word timestamps), subtitles are burned into the frame.

1. Start the API: `.venv/bin/python -W ignore -m uvicorn crowdplan.api:app --port 8000`
2. Start the stage server from the repo root: `python3 -m http.server 8765 --bind 127.0.0.1`
3. Put voice notes in `video/voice/` named `01` to `15` (m4a, mp3, wav, ogg ...). The text of each note is in `docs/DEMO_SCRIPT.md`.
4. Build: `.venv/bin/python video/build.py --voice video/voice --out video/out/seatwise-demo.mp4`

Needs Google Chrome, ffmpeg, `playwright` (pip), and whisper.cpp (`brew install whisper.cpp`) with `video/models/ggml-base.en.bin`.
`video/scenes.py` says what happens on screen and which spoken phrase triggers it. Slides are in `video/slides/`.
