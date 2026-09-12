# Project Tango — Coding Patterns and Constraints

## Code Modification Rules

### No Line-Range Splicing
When editing existing code, you MUST use the StrReplace tool with exact string matching.

**Never do this:**
```python
# Bad: Assuming line ranges
# Replace lines 45-52 in main.py...
```

**Always do this:**
1. Read the file first
2. Find the exact string to replace
3. Provide the complete old string and new string to StrReplace

**Example:**
```python
# Good: Exact string replacement
old_string = '''def old_function():
    return "old"'''

new_string = '''def new_function():
    return "new"'''
```

### Read Before Write
- Always use the Read tool before editing any file
- Verify current state before making assumptions
- Check for recent changes that might conflict

### Atomic Commits
- One logical change per commit
- Never bundle unrelated changes
- Each commit must be revertible independently

## File Organization Patterns

### Backend Structure
```
backend/
├── main.py              # FastAPI app + LiveKit worker entry point
├── history.py           # PostgreSQL session/turn history
├── requirements.txt     # Python dependencies with pinned versions
├── .env                 # Real secrets (never committed)
└── .env.example         # Template (committed, no real values)
```

**Key points:**
- `main.py` contains both FastAPI app and LiveKit worker
- Agent class definitions in same file for simplicity
- Persona configurations in dictionaries at top of file
- Database operations isolated in `history.py`

### Frontend Structure
```
frontend/
├── app/
│   ├── page.tsx         # Main UI entry point
│   ├── layout.tsx       # Root layout
│   └── api/             # API routes (if any)
├── components/
│   ├── PersonaSelector.tsx
│   ├── VoiceControls.tsx
│   └── ...
└── public/
    └── assets/
```

**Key points:**
- Next.js 15 App Router structure
- Components are client-side (`'use client'`)
- LiveKit React components for WebRTC UI

## Python Code Patterns

### Environment Variables
```python
# Always use python-dotenv at top of main.py
from dotenv import load_dotenv
load_dotenv()

# Access with os.getenv()
LIVEKIT_URL = os.getenv("LIVEKIT_URL")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")

# Always provide defaults for non-secret values
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
```

### LiveKit Agent Pattern
```python
from livekit.agents import Agent, AgentSession

class PersonaAgent(Agent):
    def __init__(self, persona_name: str):
        super().__init__()
        self.persona = PERSONAS[persona_name]
    
    async def on_session_start(self, session: AgentSession):
        # Configure STT
        stt = deepgram.STT(
            model=self.persona["stt_model"],
            language=self.persona.get("stt_language")
        )
        
        # Configure TTS
        tts = elevenlabs.TTS(
            model="eleven_flash_v2_5",
            voice=self.persona["voice_id"]
        )
        
        # Configure LLM (ALWAYS through LiteLLM)
        llm = openai.LLM(
            base_url="http://localhost:4000/v1",
            api_key=os.getenv("LITELLM_MASTER_KEY"),
            model=self.persona["model"]
        )
        
        # Start agent session
        await session.start(
            llm=llm,
            stt=stt,
            tts=tts,
            system_prompt=self.persona["system_prompt"],
            turn_handling={
                "turn_detection": "stt"
            },
            use_tts_aligned_transcript=False
        )
```

### Database Interaction Pattern
```python
# history.py pattern
import psycopg2
from psycopg2.extras import RealDictCursor

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "tango"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )

def create_session(persona_name: str) -> str:
    """Create new conversation session, return session_id"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tango.sessions (persona_name) VALUES (%s) RETURNING session_id",
                (persona_name,)
            )
            session_id = cur.fetchone()[0]
            conn.commit()
            return session_id
    finally:
        conn.close()
```

## Frontend Code Patterns

### LiveKit Room Connection
```typescript
// Pattern for connecting to LiveKit room
const connectToRoom = async (personaName: string) => {
  // Step 1: Get token
  const tokenResponse = await fetch('/api/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ persona: personaName })
  });
  const { token } = await tokenResponse.json();
  
  // Step 2: Connect to room
  await room.connect(LIVEKIT_URL, token);
  
  // Step 3: Dispatch agent (ONLY after connection succeeds)
  await fetch('/api/dispatch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ 
      room: room.name,  // Note: 'room', not 'room_name'
      persona: personaName 
    })
  });
};
```

### Error Handling Pattern
```typescript
try {
  await connectToRoom(selectedPersona);
} catch (error) {
  console.error('Connection failed:', error);
  // Show user-friendly error
  setErrorMessage('Could not connect. Please try again.');
  // Cleanup
  await room.disconnect();
}
```

## Configuration Patterns

### Persona Configuration Dictionary
```python
PERSONAS = {
    "damian": {
        "name": "Damian",
        "system_prompt": "You are Damian, a...",
        "voice_id": "pNInz6obpgDQGcFmaJgB",  # ElevenLabs voice ID
        "model": "writer/palmyra-3.5-128k",
        "stt_model": "flux-general-en",
        "stt_language": None  # Flux doesn't need explicit language
    },
    "tita_baby": {
        "name": "Tita Baby",
        "system_prompt": "You are Tita Baby, a loving Filipino aunt...",
        "voice_id": "xyz123...",
        "model": "qwen3.6:latest",
        "stt_model": "nova-3",
        "stt_language": "tl"  # Required for Nova-3 Tagalog
    }
}
```

## Testing Patterns

### Service Health Checks
```bash
# Always verify services after changes
systemctl is-active tango-backend tango-web

# Backend API health
curl -s https://tango-api.schubert.life/healthz

# Check logs for errors
sudo journalctl -u tango-backend -n 50 --no-pager | grep ERROR
```

### Manual Voice Testing Checklist
1. Select persona
2. Wait for "Connected" state
3. Speak a test phrase
4. Verify:
   - STT transcription appears
   - LLM generates response
   - TTS plays audio
   - Turn detection works (doesn't cut off mid-sentence)
5. Test interruption (speak while agent is talking)
6. Test silence handling (long pause between turns)

## Common Pitfalls to Avoid

### ❌ Calling Ollama Directly
```python
# WRONG
llm = openai.LLM(
    base_url="http://localhost:11434/v1",  # Direct Ollama
    model="qwen3.6:latest"
)
```

### ✅ Using LiteLLM Proxy
```python
# CORRECT
llm = openai.LLM(
    base_url="http://localhost:4000/v1",  # LiteLLM proxy
    api_key=os.getenv("LITELLM_MASTER_KEY"),
    model="qwen3.6:latest"
)
```

### ❌ Using Pipecat Imports
```python
# WRONG
from pipecat.pipeline import Pipeline
from pipecat.services.elevenlabs import ElevenLabsTTSService
```

### ✅ Using LiveKit Agents SDK
```python
# CORRECT
from livekit.agents import AgentSession
from livekit.plugins import elevenlabs
```

### ❌ Hardcoding Secrets
```python
# WRONG
LIVEKIT_API_SECRET = "sk_live_abc123..."
```

### ✅ Using Environment Variables
```python
# CORRECT
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")
if not LIVEKIT_API_SECRET:
    raise ValueError("LIVEKIT_API_SECRET not set")
```

### ❌ Agent Dispatch Before Room Connection
```typescript
// WRONG - race condition
await Promise.all([
  room.connect(url, token),
  fetch('/api/dispatch', {...})
]);
```

### ✅ Sequential Dispatch
```typescript
// CORRECT
await room.connect(url, token);
await fetch('/api/dispatch', {...});
```

## Dependency Management

### Python Requirements Pattern
```txt
# requirements.txt - always pin versions
livekit-agents==1.2.3
livekit-plugins-openai==1.0.5
livekit-plugins-deepgram==1.1.2
livekit-plugins-elevenlabs==1.0.8
fastapi==0.104.1
uvicorn[standard]==0.24.0
python-dotenv==1.0.0
psycopg2-binary==2.9.9
```

### Frontend Package.json Pattern
```json
{
  "dependencies": {
    "next": "15.0.0",
    "react": "^18.2.0",
    "livekit-client": "^2.0.0",
    "@livekit/components-react": "^2.0.0"
  }
}
```

## Documentation Requirements

Every code change must update:
1. **Inline comments** - Only for non-obvious logic or constraints
2. **CHANGELOG.md** - What changed and why
3. **ADR (if architectural)** - Decision rationale
4. **README.md (if API/usage changed)** - Keep usage examples current

### Comment Style
```python
# Good: Explains WHY, not WHAT
# Use Nova-3 for Tagalog because Flux doesn't support it
stt_model = "nova-3" if language == "tl" else "flux-general-en"

# Bad: Narrates the obvious
# Set the STT model variable
stt_model = "nova-3"
```
