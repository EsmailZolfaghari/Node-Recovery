#!/bin/bash
# ASO Node Recovery - Service Management Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="aso-recovery"
PID_FILE="/tmp/${APP_NAME}.pid"
LOG_FILE="${SCRIPT_DIR}/logs/aso-recovery.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

usage() {
    echo "Usage: $0 {start|stop|restart|status|logs}"
    echo ""
    echo "Commands:"
    echo "  start    - Start the ASO Node Recovery service"
    echo "  stop     - Stop the service gracefully"
    echo "  restart  - Restart the service"
    echo "  status   - Check if service is running"
    echo "  logs     - View recent logs"
    exit 1
}

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

is_running() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

start_service() {
    if is_running; then
        log_warn "Service is already running (PID: $(cat $PID_FILE))"
        return 0
    fi

    log_info "Starting ASO Node Recovery..."

    # Create logs directory if it doesn't exist
    mkdir -p "$(dirname "$LOG_FILE")"
    mkdir -p "${SCRIPT_DIR}/data"

    # Activate virtual environment if exists, otherwise use system Python
    if [ -d "${SCRIPT_DIR}/.venv" ]; then
        source "${SCRIPT_DIR}/.venv/bin/activate"
    fi

    # Start the application in background
    cd "$SCRIPT_DIR"
    nohup aso-recovery >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"

    sleep 2

    if is_running; then
        log_info "Service started successfully (PID: $(cat $PID_FILE))"
        return 0
    else
        log_error "Failed to start service. Check logs: $LOG_FILE"
        return 1
    fi
}

stop_service() {
    if ! is_running; then
        log_warn "Service is not running"
        rm -f "$PID_FILE"
        return 0
    fi

    PID=$(cat "$PID_FILE")
    log_info "Stopping ASO Node Recovery (PID: $PID)..."

    # Send SIGTERM for graceful shutdown
    kill -TERM "$PID" 2>/dev/null || true

    # Wait for process to terminate
    for i in {1..30}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            log_info "Service stopped successfully"
            rm -f "$PID_FILE"
            return 0
        fi
        sleep 1
    done

    # Force kill if still running
    log_warn "Graceful shutdown timed out. Force killing..."
    kill -9 "$PID" 2>/dev/null || true
    rm -f "$PID_FILE"
    log_info "Service force stopped"
    return 0
}

restart_service() {
    stop_service
    sleep 2
    start_service
}

show_status() {
    if is_running; then
        PID=$(cat "$PID_FILE")
        UPTIME=$(ps -o etime= -p "$PID" | xargs)
        log_info "Service is running (PID: $PID, Uptime: $UPTIME)"
        
        # Show basic stats
        if [ -f "${SCRIPT_DIR}/data/aso_recovery.db" ]; then
            DB_SIZE=$(du -h "${SCRIPT_DIR}/data/aso_recovery.db" | cut -f1)
            echo "  Database size: $DB_SIZE"
        fi
        
        # Show recent log entries
        if [ -f "$LOG_FILE" ]; then
            LAST_LOG=$(tail -1 "$LOG_FILE" | cut -c1-80)
            echo "  Last log: $LAST_LOG"
        fi
        return 0
    else
        log_warn "Service is not running"
        rm -f "$PID_FILE"
        return 1
    fi
}

view_logs() {
    if [ -f "$LOG_FILE" ]; then
        tail -50 "$LOG_FILE"
    else
        log_warn "No log file found at $LOG_FILE"
    fi
}

# Main script logic
case "${1:-}" in
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    restart)
        restart_service
        ;;
    status)
        show_status
        ;;
    logs)
        view_logs
        ;;
    *)
        usage
        ;;
esac
