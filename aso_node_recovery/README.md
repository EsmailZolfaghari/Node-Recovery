# ASO Node Recovery

Automated VPS Node Recovery System for 3X-UI Master Infrastructure.

## Overview

ASO Node Recovery is a production-grade system that automatically detects failed VPS nodes and replaces them with new instances while preserving the logical node identity in your 3X-UI Master.

### Key Features

- **Automatic Failure Detection**: Distinguishes between temporary and persistent failures
- **On-Demand Replacement**: No spare VPS needed - creates replacements only when required
- **Multi-Provider Support**: Extensible architecture supporting Hetzner, Linode, and more
- **IP Reachability Validation**: Ensures new IPs are reachable before deployment
- **Safe Replacement**: Old VPS is never deleted until new node is fully verified
- **Crash Recovery**: Persistent state allows recovery from application crashes
- **Idempotent Operations**: Safe retry on any failure
- **Telegram Integration**: Control and monitor via Telegram bot
- **Audit Logging**: Complete event history for debugging and compliance
- **Dry Run Mode**: Test without making real changes

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Failure        │────▶│  Replacement     │────▶│  Provider       │
│  Detection      │     │  Orchestrator    │     │  Abstraction    │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌──────────────────┐
                        │  State Machine   │
                        │  (Persistent)    │
                        └──────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
       ┌────────────┐  ┌────────────┐  ┌────────────┐
       │  Reach-    │  │  SSH &     │  │  Master    │
       │  ability   │  │  Deploy    │  │  Update    │
       └────────────┘  └────────────┘  └────────────┘
```

## Installation

### Requirements

- Python 3.12+
- SQLite (built-in)
- Network access to your VPS providers and 3X-UI Master

### Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd aso_node_recovery
```

2. Install dependencies:
```bash
pip install -e .
```

3. For development:
```bash
pip install -e ".[dev]"
```

4. Configure environment:
```bash
cp .env.example .env
# Edit .env with your credentials
```

## Configuration

See `.env.example` for all available configuration options.

Key settings:

- `HETZNER_API_TOKEN`: Hetzner Cloud API token
- `LINODE_API_TOKEN`: Linode API token
- `MASTER_HOST`: 3X-UI Master server hostname
- `MASTER_PASSWORD`: Master password
- `TELEGRAM_BOT_TOKEN`: Telegram bot token
- `DRY_RUN_ENABLED`: Enable dry run mode

## Usage

### Running the Application

```bash
# Production mode
aso-recovery

# Dry run mode (no real actions)
aso-recovery --dry-run

# Debug mode
aso-recovery --debug
```

### Telegram Bot Commands

- `/status` - Overall system status
- `/nodes` - List all nodes
- `/node <name>` - Node details
- `/jobs` - Active replacement jobs
- `/replace <node>` - Manual replacement
- `/history` - Recent events
- `/help` - Help message

## Safety Features

### Old VPS Protection

The most critical safety rule: **Old VPS is never deleted until the new node is fully operational and verified.**

Replacement workflow:
1. Create new VPS
2. Validate IP reachability
3. Deploy 3X-UI
4. Verify deployment
5. Update Master
6. Verify Master sync
7. Final health check
8. **Only then**: Delete old VPS

If any step fails, the old VPS remains untouched.

### Crash Recovery

All state is persisted to SQLite database. If the application crashes:
- Running jobs are recovered
- Partial operations are detected
- Workflow continues from last known good state
- Orphaned resources are cleaned up

### Idempotency

All operations are idempotent. Retries due to:
- Network timeouts
- Application restarts
- Manual intervention

Will not cause duplicate resources or inconsistent state.

## Development

### Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=aso_node_recovery

# Specific test file
pytest tests/unit/test_models.py
```

### Code Quality

```bash
# Linting
ruff check .

# Type checking
mypy aso_node_recovery
```

## Project Structure

```
aso_node_recovery/
├── config/          # Configuration and settings
├── core/            # Core utilities (logging, etc.)
├── database/        # Database models and repositories
├── models/          # Domain models
├── providers/       # VPS provider abstractions
├── reachability/    # IP reachability checkers
├── deployer/        # 3X-UI deployment
├── master/          # 3X-UI Master integration
├── telegram/        # Telegram bot
├── services/        # Business logic services
├── api/             # External APIs
└── tests/           # Test suites
```

## License

MIT

## Support

For issues and questions, please open an issue on the repository.
