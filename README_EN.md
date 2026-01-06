<p align="center">
  <img src="images/logo.png" alt="Claude to GCP Vertex AI Proxy" width="200">
</p>

<h1 align="center">Claude to GCP Vertex AI Proxy</h1>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.8+-blue?logo=python&logoColor=white" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-green.svg" alt="License"></a>
  <a href="."><img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey" alt="Platform"></a>
  <a href="https://cloud.google.com/vertex-ai"><img src="https://img.shields.io/badge/Google%20Cloud-Vertex%20AI-4285F4?logo=googlecloud&logoColor=white" alt="GCP"></a>
  <a href="https://www.anthropic.com/"><img src="https://img.shields.io/badge/Anthropic-Claude-D4A574?logo=anthropic&logoColor=white" alt="Anthropic"></a>
</p>

<p align="center">
  English | <a href="README.md">中文</a>
</p>

A proxy service that converts Claude API requests to Google Cloud Vertex AI format, enabling Claude Code clients to access Claude models through GCP Vertex AI.

## Disclaimer

This project is a protocol conversion tool designed for **Google Cloud Vertex AI enterprise customers** to simplify the integration between Claude Code client and GCP Vertex AI.

**This project:**
- ✅ Is a legitimate API protocol conversion tool
- ✅ Is intended for users with existing GCP Vertex AI Claude model access
- ✅ Complies with Google Cloud and Anthropic terms of service
- ❌ Does not provide any functionality to bypass authorization or network restrictions
- ❌ Does not provide free access to paid services

**Prerequisites:**
- You must have a valid Google Cloud account
- You must have enabled Vertex AI API in your GCP project
- You must have access to Claude models (via Vertex AI Model Garden)

**Compliance Requirements:**
- Users must comply with Google Cloud Platform Terms of Service
- Users must comply with Anthropic Usage Policy
- Users must comply with applicable local laws and regulations

## Environment Variables

This program supports the following environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `GCP_KEY_FILE` | Path to GCP service account JSON credentials file | `key/key.json` |
| `GCP_REGION` | GCP Vertex AI region (e.g., `global`, `us-east5`, `europe-west1`) | `global` |
| `SSL_VERIFY` | Whether to verify SSL certificates (set to `false` for Charles/Fiddler debugging) | `true` |

### Credentials Configuration

Place your GCP service account JSON credentials file at `key/key.json` (default path).

To customize, set the environment variable:

```bash
# Windows
set GCP_KEY_FILE=path/to/your-credentials.json

# Linux/Mac
export GCP_KEY_FILE=path/to/your-credentials.json
```

### Region Configuration

Default region is `global`. To specify a different region:

```bash
# Windows
set GCP_REGION=us-east5

# Linux/Mac
export GCP_REGION=us-east5
```

## Quick Start

### Step 1: Install Claude Code

1. **Uninstall old versions** (if any):
   ```bash
   npm uninstall -g claude-code
   npm uninstall -g @anthropic-ai/claude
   ```

2. **Install official version**:
   ```bash
   npm install -g @anthropic-ai/claude-code
   ```

### Step 2: Start the Proxy Service

Use the startup script (recommended, automatically creates virtual environment and installs dependencies):

```bash
# Linux/Mac
bash start_proxy.sh

# Windows
start_proxy.cmd
```

The startup script will automatically:
- Create a Python virtual environment (`.venv`)
- Install required dependencies
- Start the proxy service

The service will start at `http://0.0.0.0:8000`.

### Step 3: Configure Environment Variables

Set the following environment variables in a new terminal:

```bash
# API Key can be any value (not used for authentication by this proxy)
export ANTHROPIC_API_KEY='placeholder'

# Point to the proxy service
export ANTHROPIC_BASE_URL=http://127.0.0.1:8000
```

#### Recommended: Use zcf Configuration Tool

Use [zcf (Zero-Config Flow for Claude Code)](https://github.com/UfoMiao/zcf) for persistent configuration:

```bash
npx zcf
```

Follow the on-screen prompts to complete the configuration.

### Step 4: Use Claude Code

Once configured, you can use Claude Code normally. All requests will be forwarded to GCP Vertex AI through the proxy service.

## Verify Service Status

```bash
# Health check
curl http://127.0.0.1:8000/health

# List available models
curl http://127.0.0.1:8000/v1/models
```

## FAQ

### Q: Proxy service fails to start

Please check:
- Credentials file exists at `key/key.json` (or path specified by `GCP_KEY_FILE`)
- Python dependencies are correctly installed
- Port 8000 is not in use

### Q: Response delay or timeout

Please check:
- Network connection stability
- Firewall not blocking outbound connections
- GCP service status

### Q: Permission errors

Please verify:
- Service account has Vertex AI access permissions
- Vertex AI API is enabled in GCP project
- Credentials file permissions are correct

## Technical Details

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `/v1/messages` | Claude messages API (streaming/non-streaming) |
| `/v1/models` | Available models list |
| `/health` | Health check |

### Log Files

- `api_requests.log` - Detailed request/response logs
- `api_requests_simple.log` - Simplified conversation logs

### Compatibility Handling

- Automatically removes `input_examples` field not supported by Vertex AI
- Supports Claude Code model name mapping
- Automatically adds required fields like `anthropic_version`

## Security Notes

⚠️ **Important**:
- Credentials files (`key/*.json`) are excluded in `.gitignore`, do not commit manually
- Run this service only in trusted network environments
- Rotate service account keys regularly

## License

This project is licensed under the [Apache License 2.0](LICENSE).
