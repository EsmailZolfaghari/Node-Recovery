#!/bin/bash
# ASO Node Recovery - System Health Check Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="aso-recovery"
PID_FILE="/tmp/${APP_NAME}.pid"
DB_PATH="${SCRIPT_DIR}/data/aso_recovery.db"
LOG_FILE="${SCRIPT_DIR}/logs/aso-recovery.log"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

PASS=0
WARN=0
FAIL=0

check_pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((PASS++))
}

check_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
    ((WARN++))
}

check_fail() {
    echo -e "${RED}✗${NC} $1"
    ((FAIL++))
}

echo "======================================"
echo "  ASO Node Recovery - Health Check"
echo "======================================"
echo ""

# Check 1: Process running
echo "Checking service status..."
if [ -f "$PID_FILE" ] && ps -p $(cat "$PID_FILE") > /dev/null 2>&1; then
    check_pass "Service is running (PID: $(cat $PID_FILE))"
else
    check_fail "Service is not running"
fi

# Check 2: Database exists and is accessible
echo ""
echo "Checking database..."
if [ -f "$DB_PATH" ]; then
    DB_SIZE=$(du -h "$DB_PATH" | cut -f1)
    check_pass "Database exists ($DB_SIZE)"
    
    # Try to query database
    if python3 -c "import sqlite3; conn = sqlite3.connect('$DB_PATH'); conn.execute('SELECT 1'); print('OK')" > /dev/null 2>&1; then
        check_pass "Database is accessible"
    else
        check_fail "Database is corrupted or locked"
    fi
else
    check_warn "Database not found (will be created on first run)"
fi

# Check 3: Log file
echo ""
echo "Checking logs..."
if [ -f "$LOG_FILE" ]; then
    LOG_SIZE=$(du -h "$LOG_FILE" | cut -f1)
    LAST_LINE=$(tail -1 "$LOG_FILE" 2>/dev/null | cut -c1-60)
    check_pass "Log file exists ($LOG_SIZE)"
    echo "  Last log: $LAST_LINE"
else
    check_warn "Log file not found"
fi

# Check 4: Configuration
echo ""
echo "Checking configuration..."
if [ -f "${SCRIPT_DIR}/.env" ]; then
    check_pass ".env file exists"
    
    # Check for required variables (without exposing values)
    if grep -q "HETZNER_API_TOKEN=" "${SCRIPT_DIR}/.env" 2>/dev/null; then
        check_pass "Hetzner API token configured"
    else
        check_warn "Hetzner API token not configured"
    fi
    
    if grep -q "LINODE_API_TOKEN=" "${SCRIPT_DIR}/.env" 2>/dev/null; then
        check_pass "Linode API token configured"
    else
        check_warn "Linode API token not configured"
    fi
    
    if grep -q "MASTER_HOST=" "${SCRIPT_DIR}/.env" 2>/dev/null; then
        check_pass "Master host configured"
    else
        check_warn "Master host not configured"
    fi
else
    check_fail ".env file not found"
fi

# Check 5: Python environment
echo ""
echo "Checking Python environment..."
if command -v aso-recovery &> /dev/null; then
    VERSION=$(aso-recovery --version 2>&1 || echo "unknown")
    check_pass "aso-recovery command available ($VERSION)"
else
    check_fail "aso-recovery command not found"
fi

# Check 6: Disk space
echo ""
echo "Checking disk space..."
DISK_USAGE=$(df -h "${SCRIPT_DIR}" | awk 'NR==2 {print $5}' | tr -d '%')
if [ "$DISK_USAGE" -lt 80 ]; then
    check_pass "Disk usage is ${DISK_USAGE}%"
elif [ "$DISK_USAGE" -lt 90 ]; then
    check_warn "Disk usage is ${DISK_USAGE}% (consider cleanup)"
else
    check_fail "Disk usage is critical: ${DISK_USAGE}%"
fi

# Check 7: Recent errors in logs
echo ""
echo "Checking for recent errors..."
if [ -f "$LOG_FILE" ]; then
    ERROR_COUNT=$(grep -c "ERROR\|CRITICAL" "$LOG_FILE" 2>/dev/null || echo "0")
    if [ "$ERROR_COUNT" -eq 0 ]; then
        check_pass "No recent errors in logs"
    elif [ "$ERROR_COUNT" -lt 10 ]; then
        check_warn "$ERROR_COUNT errors in log (review recommended)"
    else
        check_fail "$ERROR_COUNT errors in log (immediate review needed)"
    fi
else
    check_warn "Cannot check logs (file not found)"
fi

# Summary
echo ""
echo "======================================"
echo "  Summary"
echo "======================================"
echo -e "${GREEN}Passed:${NC} $PASS"
echo -e "${YELLOW}Warnings:${NC} $WARN"
echo -e "${RED}Failed:${NC} $FAIL"
echo ""

if [ "$FAIL" -gt 0 ]; then
    echo -e "${RED}Health check FAILED. Immediate attention required.${NC}"
    exit 1
elif [ "$WARN" -gt 0 ]; then
    echo -e "${YELLOW}Health check PASSED with warnings. Review recommended.${NC}"
    exit 0
else
    echo -e "${GREEN}Health check PASSED. All systems operational.${NC}"
    exit 0
fi
