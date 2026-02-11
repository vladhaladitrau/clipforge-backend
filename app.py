from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import subprocess
import assemblyai as aai
from openai import OpenAI
import json
import tempfile
import logging

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize API clients
aai.settings.api_key = os.environ.get("ASSEMBLYAI_API_KEY")
openai_client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY")
)

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy"}), 200

@app.route('/api/extract-clips', methods=['POST'])
def extract_clips():
    """
    Main endpoint: Takes a VOD URL, extracts audio, transcribes, and identifies viral clips
    """
    try:
        data = request.json
        vod_url = data.get('vod_url')
        num_clips = data.get('num_clips', 5)
        
        if not vod_url:
            return jsonify({"status": "error", "message": "vod_url is required"}), 400
        
        logger.info(f"Processing VOD: {vod_url}")
        
        # Step 1: Extract audio from VOD
        logger.info("Step 1: Extracting audio...")
        audio_path = extract_audio(vod_url)
        
        # Step 2: Upload to AssemblyAI and get transcript
        logger.info("Step 2: Transcribing audio...")
        transcript_result = transcribe_audio(audio_path)
        
        # Step 3: Analyze transcript for viral clips
        logger.info("Step 3: Finding viral clips...")
        clips = find_viral_clips(transcript_result['text'], num_clips)
        
        # Clean up temp file
        try:
            os.remove(audio_path)
        except:
            pass
        
        return jsonify({
            "status": "success",
            "vod_url": vod_url,
            "audio_url": transcript_result['audio_url'],
            "transcript_id": transcript_result['id'],
            "transcript_text": transcript_result['text'],
            "clips": clips
        }), 200
        
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

def extract_audio(vod_url):
    """
    Extract audio from VOD URL using yt-dlp
    Returns path to temporary audio file
    """
    try:
        # Create temp file for audio
        temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        audio_path = temp_audio.name
        temp_audio.close()
        
        # Updated yt-dlp command with better format selection for Twitch
        cmd = [
            'yt-dlp',
            '--extract-audio',
            '--audio-format', 'mp3',
            '--audio-quality', '0',  # Best quality
            '--output', audio_path,
            '--no-playlist',
            '--format', 'bestaudio/best',  # Try best audio first, fall back to best overall
            '--postprocessor-args', '-ar 16000',  # Resample to 16kHz for transcription
            vod_url
        ]
        
        logger.info(f"Running yt-dlp command: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode != 0:
            logger.error(f"yt-dlp error: {result.stderr}")
            raise Exception(f"Failed to extract audio: {result.stderr}")
        
        # Verify file exists and has content
        if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
            raise Exception("Audio file was not created or is empty")
        
        logger.info(f"Audio extracted successfully: {audio_path} ({os.path.getsize(audio_path)} bytes)")
        return audio_path
        
    except subprocess.TimeoutExpired:
        raise Exception("Audio extraction timed out - VOD may be too long")
    except Exception as e:
        logger.error(f"Error extracting audio: {str(e)}")
        raise

def transcribe_audio(audio_path):
    """
    Upload audio to AssemblyAI and get transcript
    """
    try:
        # Upload file
        logger.info("Uploading audio to AssemblyAI...")
        transcriber = aai.Transcriber()
        
        # Configure transcription
        config = aai.TranscriptionConfig(
            speaker_labels=True,  # Detect different speakers
            punctuate=True,
            format_text=True
        )
        
        # Start transcription
        transcript = transcriber.transcribe(audio_path, config=config)
        
        # Wait for completion
        if transcript.status == aai.TranscriptStatus.error:
            raise Exception(f"Transcription failed: {transcript.error}")
        
        logger.info(f"Transcription complete: {transcript.id}")
        
        return {
            "id": transcript.id,
            "text": transcript.text,
            "audio_url": transcript.audio_url
        }
        
    except Exception as e:
        logger.error(f"Transcription error: {str(e)}")
        raise Exception(f"Transcription failed: {str(e)}")

def find_viral_clips(transcript_text, num_clips=5):
    """
    Use OpenAI to analyze transcript and identify viral-worthy moments
    """
    try:
        prompt = f"""You are an expert at identifying viral-worthy gaming/streaming clips.

Analyze this stream transcript and identify the {num_clips} BEST moments that would make viral clips (10-60 seconds each).

Look for:
- Funny moments, reactions, or unexpected events
- Skilled plays or clutch moments
- Emotional reactions (hype, rage, wholesome)
- Memes or quotable lines
- Drama or heated discussions

For EACH clip, provide:
1. A catchy title (under 60 characters)
2. Start timestamp in format MM:SS or HH:MM:SS
3. End timestamp in format MM:SS or HH:MM:SS
4. Brief description of why it's viral-worthy

Transcript:
{transcript_text}

Respond ONLY with a JSON array in this exact format:
[
  {{
    "title": "Insane Clutch 1v5",
    "start_time": "12:34",
    "end_time": "13:05",
    "description": "Player pulls off incredible comeback"
  }}
]

If you cannot find {num_clips} viral moments, return fewer clips. Only include genuinely interesting moments."""

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a viral clip detection expert. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=2000
        )
        
        # Parse response
        content = response.choices[0].message.content.strip()
        
        # Remove markdown code blocks if present
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        clips = json.loads(content)
        
        logger.info(f"Found {len(clips)} viral clips")
        return clips
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse OpenAI response: {content}")
        return []
    except Exception as e:
        logger.error(f"Error finding clips: {str(e)}")
        return []

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
