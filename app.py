"""
ClipForge Backend API
Handles: VOD audio extraction → Transcription → AI Clip Detection
Deploy to Railway, Render, or Replit
"""

import os
import time
import json
import re
import tempfile
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# --- Configuration ---
ASSEMBLYAI_API_KEY = os.environ.get("ASSEMBLYAI_API_KEY", "YOUR_ASSEMBLYAI_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "YOUR_OPENAI_KEY")


# =============================================
# STEP 1: Extract direct audio URL from VOD
# =============================================
def extract_audio_url(vod_url):
    """
    Uses yt-dlp to get a direct audio URL from Twitch/Kick/YouTube VODs.
    Returns the direct URL without downloading the file.
    """
    import yt_dlp

    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(vod_url, download=False)
        # Get the best audio format URL
        if "formats" in info:
            # Prefer audio-only formats
            audio_formats = [f for f in info["formats"] if f.get("acodec") != "none" and f.get("vcodec") in ("none", None)]
            if audio_formats:
                return audio_formats[-1]["url"]
            # Fallback: use best format with audio
            for fmt in reversed(info["formats"]):
                if fmt.get("acodec") != "none" and fmt.get("url"):
                    return fmt["url"]
        # Fallback to direct URL
        if "url" in info:
            return info["url"]

    raise Exception("Could not extract audio URL from the provided VOD link.")


# =============================================
# STEP 2: Transcribe audio with AssemblyAI
# =============================================
def submit_transcription(audio_url):
    """Submit audio URL to AssemblyAI for transcription."""
    headers = {
        "Authorization": ASSEMBLYAI_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "audio_url": audio_url,
        "speech_models": ["universal-2"],
    }
    response = requests.post(
        "https://api.assemblyai.com/v2/transcript",
        headers=headers,
        json=payload,
    )
    response.raise_for_status()
    return response.json()["id"]


def poll_transcription(transcript_id, timeout=600):
    """Poll AssemblyAI until transcription is complete (max 10 min)."""
    headers = {"Authorization": ASSEMBLYAI_API_KEY}
    start_time = time.time()

    while time.time() - start_time < timeout:
        response = requests.get(
            f"https://api.assemblyai.com/v2/transcript/{transcript_id}",
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

        if data["status"] == "completed":
            return data
        elif data["status"] == "error":
            raise Exception(f"Transcription failed: {data.get('error', 'Unknown error')}")

        time.sleep(5)  # Wait 5 seconds before polling again

    raise Exception("Transcription timed out after 10 minutes.")


# =============================================
# STEP 3: Use OpenAI to identify best clips
# =============================================
def identify_clips(transcript_text, words_with_timestamps, num_clips=5):
    """
    Send the transcript to OpenAI to identify the most viral moments.
    Uses word-level timestamps for precise clip boundaries.
    """
    # Build a timestamped transcript for better accuracy
    timestamped_sections = []
    current_section = ""
    section_start = 0

    for i, word in enumerate(words_with_timestamps):
        if i % 50 == 0 and i > 0:
            timestamped_sections.append({
                "start_ms": section_start,
                "end_ms": word["end"],
                "text": current_section.strip()
            })
            current_section = ""
            section_start = word["start"]
        current_section += word["text"] + " "

    # Add remaining
    if current_section.strip():
        timestamped_sections.append({
            "start_ms": section_start,
            "end_ms": words_with_timestamps[-1]["end"] if words_with_timestamps else 0,
            "text": current_section.strip()
        })

    sections_text = json.dumps(timestamped_sections, indent=2)

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    prompt = f"""You are an expert at identifying viral, entertaining, and highlight-worthy moments from live stream transcripts.

Analyze the following timestamped transcript sections from a stream VOD. Identify the top {num_clips} most clip-worthy moments.

For each clip:
- Choose moments that would go viral on TikTok, YouTube Shorts, or Twitter
- Look for: funny moments, epic plays, emotional reactions, controversial takes, clutch moments, rage/excitement, plot twists
- Each clip should be 15-60 seconds long
- Use the timestamps (in milliseconds) from the sections

TIMESTAMPED TRANSCRIPT:
{sections_text}

Return ONLY a valid JSON array with exactly {num_clips} objects, each containing:
- "title": catchy clip title (max 60 chars)
- "start_ms": start timestamp in milliseconds
- "end_ms": end timestamp in milliseconds  
- "virality_score": 1-10 rating
- "reason": brief reason why this moment is clip-worthy

Sort by virality_score descending. Return ONLY the JSON array, no other text."""

    payload = {
        "model": "gpt-4.1-mini",
        "messages": [
            {"role": "system", "content": "You identify viral moments in stream transcripts. Always return valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
    }

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=payload,
    )
    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"]

    # Clean up the response (remove markdown code blocks if present)
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    clips = json.loads(content)
    return clips


# =============================================
# API ROUTES
# =============================================

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "ClipForge Backend"})


@app.route("/api/extract-clips", methods=["POST"])
def extract_clips():
    """
    Main endpoint: Takes a VOD URL and returns identified clips.
    
    Request body:
    {
        "vod_url": "https://www.twitch.tv/videos/...",
        "num_clips": 5  (optional, default 5)
    }
    
    Response:
    {
        "status": "success",
        "vod_url": "...",
        "audio_url": "...",
        "transcript_id": "...",
        "clips": [...]
    }
    """
    try:
        data = request.json
        vod_url = data.get("vod_url")
        num_clips = data.get("num_clips", 5)

        if not vod_url:
            return jsonify({"status": "error", "message": "vod_url is required"}), 400

        # Step 1: Extract audio URL
        print(f"[1/4] Extracting audio from: {vod_url}")
        audio_url = extract_audio_url(vod_url)
        print(f"[1/4] Audio URL extracted successfully")

        # Step 2: Submit for transcription
        print(f"[2/4] Submitting to AssemblyAI...")
        transcript_id = submit_transcription(audio_url)
        print(f"[2/4] Transcript ID: {transcript_id}")

        # Step 3: Wait for transcription
        print(f"[3/4] Waiting for transcription to complete...")
        transcript_data = poll_transcription(transcript_id)
        transcript_text = transcript_data.get("text", "")
        words = transcript_data.get("words", [])
        print(f"[3/4] Transcription complete ({len(words)} words)")

        if not transcript_text or not words:
            return jsonify({
                "status": "error",
                "message": "Transcription returned empty. The VOD may not have clear audio."
            }), 400

        # Step 4: Identify clips with OpenAI
        print(f"[4/4] Identifying top {num_clips} clips with AI...")
        clips = identify_clips(transcript_text, words, num_clips)
        print(f"[4/4] Found {len(clips)} clips")

        return jsonify({
            "status": "success",
            "vod_url": vod_url,
            "audio_url": audio_url,
            "transcript_id": transcript_id,
            "transcript_text": transcript_text[:500],  # First 500 chars for preview
            "clips": clips,
        })

    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/transcribe", methods=["POST"])
def transcribe_only():
    """
    Step-by-step endpoint: Just transcribe a VOD.
    Use this if you want to handle clip detection separately in Bubble.
    """
    try:
        data = request.json
        vod_url = data.get("vod_url")

        if not vod_url:
            return jsonify({"status": "error", "message": "vod_url is required"}), 400

        # Extract audio
        audio_url = extract_audio_url(vod_url)

        # Submit transcription
        transcript_id = submit_transcription(audio_url)

        # Poll for result
        transcript_data = poll_transcription(transcript_id)

        return jsonify({
            "status": "success",
            "transcript_id": transcript_id,
            "text": transcript_data.get("text", ""),
            "words": transcript_data.get("words", []),
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/get-audio-url", methods=["POST"])
def get_audio_url():
    """
    Utility endpoint: Just extract the direct audio URL from a VOD link.
    """
    try:
        data = request.json
        vod_url = data.get("vod_url")

        if not vod_url:
            return jsonify({"status": "error", "message": "vod_url is required"}), 400

        audio_url = extract_audio_url(vod_url)

        return jsonify({
            "status": "success",
            "vod_url": vod_url,
            "audio_url": audio_url,
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
