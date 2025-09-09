# Chat Server with URL Security Analysis

A real-time chat server with integrated URL security scanning using VirusTotal API. The system provides multi-room chat functionality with automatic malicious URL detection and blocking.

## Features

- **Real-time Chat**: WebSocket-based communication using Socket.IO
- **Multi-room Support**: Users can join different chat rooms
- **URL Security Scanning**: Automatic detection and analysis of URLs using VirusTotal API
- **Malicious URL Blocking**: Prevents messages with malicious URLs from being sent
- **Smart Caching**: Caches URL analysis results to reduce API calls
- **Persistent Storage**: Messages and room data are saved to disk
- **REST API**: HTTP endpoints for room and message management
- **Monitoring**: Watchdog service for server health monitoring

## Architecture

```
├── main-server/     # Chat server with URL analysis
├── message-client/  # Chat client application
├── watchdog/       # Server monitoring service
└── docker-compose.yml
```

## Prerequisites

- Docker and Docker Compose
- VirusTotal API Key (free at https://www.virustotal.com/gui/join-us)

## Quick Start

### 1. Clone Repository
```bash
git clone <repository-url>
cd checkpoint-chat-3_team
```

### 2. Configure VirusTotal API
Edit `main-server/src/config.json` and replace the API key:
```json
{
  "url_detection": {
    "virustotal_api_key": "your-virustotal-api-key-here"
  }
}
```

### 3. Build and Run with Docker Compose
```bash
# Build all services
docker-compose build

# Start the chat server
docker-compose up main-server

# In another terminal, start a client
docker-compose run --rm message-client python3 src/client.py room1 alice

# Start monitoring (optional)
docker-compose up watchdog
```

## Manual Deployment

### Server Setup
```bash
cd main-server

# Install dependencies
pip install -r requirements.txt

# Configure settings
edit src/config.json

# Run server
python3 src/server.py
```

### Client Setup
```bash
cd message-client

# Install dependencies
pip install -r requirements.txt

# Configure client
edit src/config.json

# Run client
python3 src/client.py <room> <username>
```

## Configuration

### Server Configuration (`main-server/src/config.json`)
```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 5000,
    "debug": false,
    "cors_origins": "*"
  },
  "messages": {
    "max_length": 2048,
    "max_per_room": 1000
  },
  "url_detection": {
    "enabled": true,
    "log_detections": true,
    "virustotal_api_key": "your-virustotal-api-key-here"
  },
  "storage": {
    "state_file": "data/state.json"
  }
}
```

### Client Configuration (`message-client/src/config.json`)
```json
{
  "server": {
    "url": "http://main-server:5000"
  },
  "connection": {
    "timeout": 10,
    "transports": ["polling", "websocket"]
  },
  "client": {
    "default_room": "general",
    "default_name": "user"
  },
  "logging": {
    "enabled": false,
    "show_timestamps": true
  }
}
```

## API Endpoints

### REST API
- `GET /health` - Server health check
- `GET /rooms` - List all rooms with member counts
- `GET /rooms/<room>` - Get room details
- `GET /rooms/<room>/messages?limit=50` - Get room messages

### WebSocket Events
- `join` - Join a chat room
- `chat` - Send a message
- `leave` - Leave current room
- `system` - System notifications
- `error` - Error messages

## URL Security Features

### Automatic URL Detection
- Detects URLs in messages using advanced pattern matching
- Supports various formats: `https://`, `www.`, `domain.com`
- Normalizes URLs for consistent analysis

### VirusTotal Integration
- Real-time URL analysis using VirusTotal API
- Categorization by security engines
- Malicious URL blocking
- Smart caching (1-hour TTL) to reduce API usage

### Security Logging
```
1. URL detected: https://example.com
2. Status: CLEAN
3. Categories:
   - social media
   - video hosting
---
```

## Monitoring

The watchdog service monitors:
- Server health (`/health` endpoint)
- Container status
- Configurable check intervals

```bash
# Start monitoring
docker-compose up watchdog

# Configure monitoring
edit watchdog/src/config.json
```

## Development

### Project Structure
```
main-server/src/
├── server.py          # Main server application
├── state_manager.py   # Room and message management
├── url_det.py         # URL detection and analysis
├── utils.py           # Common utilities
└── config.json        # Server configuration

message-client/src/
├── client.py          # Chat client
└── config.json        # Client configuration

watchdog/src/
├── watchdog.py        # Monitoring service
└── config.json        # Monitoring configuration
```

### Adding Features
1. **New URL Analyzers**: Extend `url_det.py`
2. **Custom Commands**: Add handlers in `server.py`
3. **Additional APIs**: Add endpoints in `server.py`
4. **Client Features**: Modify `client.py`

## Troubleshooting

### Common Issues

**Connection Failed**
```bash
# Check if server is running
curl http://localhost:5000/health

# Check Docker containers
docker-compose ps
```

**VirusTotal API Errors**
- Verify API key is correct
- Check API rate limits
- Ensure internet connectivity

**Permission Errors**
```bash
# Fix file permissions
chmod +x run-client.sh
sudo chown -R $USER:$USER data/
```

### Logs
```bash
# Server logs
docker-compose logs main-server

# Client logs
docker-compose logs message-client

# All services
docker-compose logs
```

## Security Considerations

- **API Keys**: Store VirusTotal API key securely
- **Network**: Use HTTPS in production
- **Input Validation**: Messages are length-limited
- **URL Filtering**: Malicious URLs are blocked automatically
- **Data Storage**: Messages are stored locally (consider encryption)
