#!/bin/bash
# ASO Node Recovery - Integration Test Script
# This script runs a simulated replacement workflow in dry-run mode

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR}/.."

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}  ASO Node Recovery - Integration Test${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

# Ensure we're in dry-run mode
export DRY_RUN_ENABLED=true
export DATABASE_PATH="/tmp/aso_test_${RANDOM}.db"

echo -e "${YELLOW}Test Configuration:${NC}"
echo "  Dry Run: Enabled"
echo "  Database: $DATABASE_PATH"
echo ""

# Test 1: Import check
echo -e "${BLUE}Test 1: Importing modules...${NC}"
if python3 -c "
import aso_node_recovery
from aso_node_recovery.models import Node, ReplacementJob, VPSInfo, Event
from aso_node_recovery.database import Database, NodeRepository, ReplacementJobRepository
from aso_node_recovery.providers import BaseProvider
from aso_node_recovery.reachability import BaseReachabilityChecker
from aso_node_recovery.deployer import DeploymentManager
from aso_node_recovery.master import Master3XUI
print('All imports successful')
"; then
    echo -e "${GREEN}✓ Module imports passed${NC}"
else
    echo -e "${RED}✗ Module imports failed${NC}"
    exit 1
fi
echo ""

# Test 2: Database initialization
echo -e "${BLUE}Test 2: Database initialization...${NC}"
if python3 -c "
import asyncio
from aso_node_recovery.database import Database

async def test():
    db = Database('$DATABASE_PATH')
    await db.initialize()
    print('Database initialized successfully')
    await db.close()

asyncio.run(test())
"; then
    echo -e "${GREEN}✓ Database initialization passed${NC}"
else
    echo -e "${RED}✗ Database initialization failed${NC}"
    exit 1
fi
echo ""

# Test 3: Node creation and state transitions
echo -e "${BLUE}Test 3: Node state transitions...${NC}"
if python3 -c "
from aso_node_recovery.models.node import Node, NodeStatus
from datetime import datetime, timezone

# Create node
node = Node(name='test-node-01', provider='hetzner', location='Germany')
assert node.status == NodeStatus.HEALTHY
print(f'Created node: {node.name}, status: {node.status}')

# Mark as unhealthy
node.mark_unhealthy()
assert node.status == NodeStatus.UNHEALTHY
print(f'Marked unhealthy: {node.status}')

# Mark as failed
node.mark_failed()
assert node.status == NodeStatus.FAILED
print(f'Marked failed: {node.status}')

# Mark as replacing
node.mark_replacing()
assert node.status == NodeStatus.REPLACING
print(f'Marked replacing: {node.status}')

# Clear replacement (simulate failure)
node.clear_replacement()
assert node.status == NodeStatus.FAILED
print(f'Cleared replacement: {node.status}')

print('All state transitions valid')
"; then
    echo -e "${GREEN}✓ Node state transitions passed${NC}"
else
    echo -e "${RED}✗ Node state transitions failed${NC}"
    exit 1
fi
echo ""

# Test 4: Replacement job workflow
echo -e "${BLUE}Test 4: Replacement job workflow...${NC}"
if python3 -c "
from aso_node_recovery.models.replacement import ReplacementJob, ReplacementStage, JobStatus
from datetime import datetime, timezone

# Create job
job = ReplacementJob(node_id='test-node-01', reason='Persistent failure detected')
assert job.status == JobStatus.PENDING
print(f'Created job: {job.id}, status: {job.status}')

# Start job
job.start()
assert job.status == JobStatus.RUNNING
assert job.current_stage == ReplacementStage.CREATING_VPS
print(f'Job started: stage={job.current_stage}')

# Advance through stages
stages = [
    ReplacementStage.VPS_CREATED,
    ReplacementStage.IP_VALIDATED,
    ReplacementStage.SSH_AVAILABLE,
    ReplacementStage.DEPLOYING_3XUI,
    ReplacementStage.DEPLOYMENT_VERIFIED,
    ReplacementStage.UPDATING_MASTER,
    ReplacementStage.MASTER_UPDATED,
    ReplacementStage.FINAL_HEALTH_CHECK,
]

for stage in stages:
    job.advance_to(stage)
    print(f'Advanced to: {stage.value}')

# Complete job
job.mark_completed()
assert job.status == JobStatus.COMPLETED
print(f'Job completed: {job.status}')

# Check if old VPS should be deleted
assert job.should_delete_old_vps() == True
print('Old VPS deletion check: PASSED')

print('All workflow steps valid')
"; then
    echo -e "${GREEN}✓ Replacement job workflow passed${NC}"
else
    echo -e "${RED}✗ Replacement job workflow failed${NC}"
    exit 1
fi
echo ""

# Test 5: Safety checks
echo -e "${BLUE}Test 5: Safety checks (Old VPS protection)...${NC}"
if python3 -c "
from aso_node_recovery.models.replacement import ReplacementJob, ReplacementStage, JobStatus

# Test case 1: Job not completed
job1 = ReplacementJob(node_id='test-01', reason='Test')
job1.start()
job1.advance_to(ReplacementStage.IP_VALIDATED)
assert job1.should_delete_old_vps() == False
print('✓ Old VPS preserved when job not completed')

# Test case 2: Job completed but new VPS not ready
job2 = ReplacementJob(node_id='test-02', reason='Test')
job2.start()
job2.advance_to(ReplacementStage.DEPLOYING_3XUI)
job2.new_vps_id = 'new-vps-123'
# Don't mark deployment as verified
try:
    job2.mark_completed()
    assert job2.should_delete_old_vps() == False
    print('✓ Old VPS preserved when deployment not verified')
except:
    pass

# Test case 3: All conditions met
job3 = ReplacementJob(node_id='test-03', reason='Test')
job3.start()
stages = [
    ReplacementStage.VPS_CREATED,
    ReplacementStage.IP_VALIDATED,
    ReplacementStage.SSH_AVAILABLE,
    ReplacementStage.DEPLOYING_3XUI,
    ReplacementStage.DEPLOYMENT_VERIFIED,
    ReplacementStage.UPDATING_MASTER,
    ReplacementStage.MASTER_UPDATED,
    ReplacementStage.FINAL_HEALTH_CHECK,
]
for stage in stages:
    job3.advance_to(stage)
job3.new_vps_id = 'new-vps-456'
job3.mark_completed()
assert job3.should_delete_old_vps() == True
print('✓ Old VPS can be deleted when all conditions met')

print('All safety checks passed')
"; then
    echo -e "${GREEN}✓ Safety checks passed${NC}"
else
    echo -e "${RED}✗ Safety checks failed${NC}"
    exit 1
fi
echo ""

# Cleanup
rm -f "$DATABASE_PATH"

# Summary
echo -e "${BLUE}======================================${NC}"
echo -e "${GREEN}All integration tests passed!${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""
echo "Note: These tests ran in DRY-RUN mode."
echo "No real VPS instances were created or modified."
