# ClipForge Backend

Backend API for ClipForge — extracts audio from Twitch/Kick/YouTube VODs, transcribes with AssemblyAI, and identifies viral clips with OpenAI.

## How It Works

1. **User pastes VOD URL** in Bubble
2. **Bubble calls this backend** → `/api/extract-clips`
3. **yt-dlp** extracts the direct audio URL from the VOD
4. **AssemblyAI** transcribes the audio with word-level timestamps
5. **OpenAI** analyzes the transcript and identifies top clip-worthy moments
6. **Backend returns** clip timestamps, titles, and virality scores to Bubble
7. **Bubble sends** timestamps to Shotstack to render the clips

## API Endpoints

### `POST /api/extract-clips` (Main endpoint)
Send a VOD URL, get back identified clips.

**Request:**
```json
{
  "vod_url": "https://www.twitch.tv/videos/123456789",
  "num_clips": 5
}
```

**Response:**
```json
{
  "status": "success",
  "clips": [
    {
      "title": "Insane clutch play in final round",
      "start_ms": 125000,
      "end_ms": 155000,
      "virality_score": 9,
      "reason": "Epic comeback moment with high excitement"
    }
  ]
}
```

### `POST /api/transcribe` (Transcription only)
Just transcribe a VOD without clip detection.

### `POST /api/get-audio-url` (Audio URL extraction only)
Just get the direct audio URL from a VOD link.

## Deploy to Railway (Recommended)

1. Push this folder to a GitHub repo
2. Go to [railway.app](https://railway.app)
3. Click "New Project" → "Deploy from GitHub repo"
4. Select your repo
5. Add environment variables:
   - `ASSEMBLYAI_API_KEY` = your AssemblyAI key
   - `OPENAI_API_KEY` = your OpenAI key
6. Railway will auto-deploy and give you a URL like `https://clipforge-backend-production.up.railway.app`

## Deploy to Render (Alternative)

1. Push this folder to a GitHub repo
2. Go to [render.com](https://render.com)
3. Create a new "Web Service"
4. Connect your repo
5. Set:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app`
6. Add environment variables (same as above)

## Connect to Bubble

In Bubble's API Connector:

1. Create a new API collection: `ClipForge Backend`
2. Add API Call:
   - Name: `Extract Clips`
   - Method: POST
   - URL: `https://YOUR-RAILWAY-URL.up.railway.app/api/extract-clips`
   - Headers: `Content-Type: application/json`
   - Body:
     ```json
     {
       "vod_url": "<vod_url>",
       "num_clips": 5
     }
     ```
3. Initialize and save

Then in your button workflow:
- Step 1: Call `ClipForge Backend - Extract Clips` with `vod_url` = Input VodUrlInput's value
- Step 2: Use the returned clips to create database entries or send to Shotstack

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ASSEMBLYAI_API_KEY` | Your AssemblyAI API key |
| `OPENAI_API_KEY` | Your OpenAI API key |
| `PORT` | Server port (auto-set by Railway/Render) |
