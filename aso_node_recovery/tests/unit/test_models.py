"""Unit tests for models."""

import pytest
from datetime import datetime

from aso_node_recovery.models.node import Node, NodeStatus
from aso_node_recovery.models.replacement import ReplacementJob, ReplacementStage, ReplacementStatus
from aso_node_recovery.models.event import Event, EventType
from aso_node_recovery.models.vps import VPSInfo


class TestNode:
    """Tests for Node model."""

    def test_create_node(self):
        """Test creating a node."""
        node = Node(id=1, name="test-node")
        assert node.id == 1
        assert node.name == "test-node"
        assert node.status == NodeStatus.HEALTHY
        assert node.consecutive_failures == 0

    def test_mark_healthy(self):
        """Test marking node as healthy."""
        node = Node(id=1, name="test-node", status=NodeStatus.UNHEALTHY, consecutive_failures=5)
        node.mark_healthy()
        assert node.status == NodeStatus.HEALTHY
        assert node.consecutive_failures == 0
        assert node.last_health_check is not None
        assert node.last_successful_check is not None

    def test_mark_unhealthy(self):
        """Test marking node as unhealthy."""
        node = Node(id=1, name="test-node")
        initial_failures = node.consecutive_failures
        node.mark_unhealthy()
        assert node.status == NodeStatus.UNHEALTHY
        assert node.consecutive_failures == initial_failures + 1

    def test_mark_failed(self):
        """Test marking node as failed."""
        node = Node(id=1, name="test-node")
        node.mark_failed()
        assert node.status == NodeStatus.FAILED

    def test_mark_replacing(self):
        """Test marking node as being replaced."""
        node = Node(id=1, name="test-node")
        node.mark_replacing(123)
        assert node.status == NodeStatus.REPLACING
        assert node.active_replacement_job_id == 123

    def test_clear_replacement(self):
        """Test clearing replacement after completion."""
        node = Node(id=1, name="test-node")
        node.mark_replacing(123)
        node.clear_replacement()
        assert node.active_replacement_job_id is None
        assert 123 in node.replacement_history

    def test_update_vps_info(self):
        """Test updating VPS information."""
        node = Node(id=1, name="test-node")
        node.update_vps_info("vps-123", "192.168.1.1")
        assert node.current_vps_id == "vps-123"
        assert node.current_ip == "192.168.1.1"

    def test_is_replaceable_healthy(self):
        """Test that healthy node is not replaceable."""
        node = Node(id=1, name="test-node", status=NodeStatus.HEALTHY)
        assert not node.is_replaceable()

    def test_is_replaceable_failed(self):
        """Test that failed node is replaceable."""
        node = Node(id=1, name="test-node", status=NodeStatus.FAILED)
        assert node.is_replaceable()

    def test_is_replaceable_with_active_job(self):
        """Test that node with active job is not replaceable."""
        node = Node(id=1, name="test-node", status=NodeStatus.FAILED, active_replacement_job_id=123)
        assert not node.is_replaceable()


class TestReplacementJob:
    """Tests for ReplacementJob model."""

    def test_create_job(self):
        """Test creating a replacement job."""
        job = ReplacementJob(id=1, node_id=1, node_name="test-node")
        assert job.id == 1
        assert job.node_id == 1
        assert job.status == ReplacementStatus.PENDING
        assert job.current_stage == ReplacementStage.PENDING
        assert job.attempt_number == 1

    def test_start_job(self):
        """Test starting a replacement job."""
        job = ReplacementJob(id=1, node_id=1, node_name="test-node")
        job.start()
        assert job.status == ReplacementStatus.RUNNING
        assert job.current_stage == ReplacementStage.CONFIRMING_FAILURE
        assert job.started_at is not None

    def test_advance_stage(self):
        """Test advancing job stage."""
        job = ReplacementJob(id=1, node_id=1, node_name="test-node")
        job.advance_stage(ReplacementStage.CREATING_VPS)
        assert job.current_stage == ReplacementStage.CREATING_VPS

    def test_mark_completed(self):
        """Test marking job as completed."""
        job = ReplacementJob(id=1, node_id=1, node_name="test-node")
        job.mark_completed()
        assert job.status == ReplacementStatus.COMPLETED
        assert job.current_stage == ReplacementStage.COMPLETED
        assert job.completed_at is not None

    def test_mark_failed(self):
        """Test marking job as failed."""
        job = ReplacementJob(id=1, node_id=1, node_name="test-node")
        job.mark_failed("Test error", {"detail": "test"})
        assert job.status == ReplacementStatus.FAILED
        assert job.error_message == "Test error"
        assert job.error_details == {"detail": "test"}

    def test_should_delete_old_vps_false_when_not_completed(self):
        """Test that old VPS is not deleted when job not completed."""
        job = ReplacementJob(id=1, node_id=1, node_name="test-node")
        job.new_vps_id = "new-vps"
        job.new_vps_ip = "1.2.3.4"
        job.deployment_verified = True
        job.master_updated = True
        # Status is still PENDING
        assert not job.should_delete_old_vps()

    def test_should_delete_old_vps_true_when_ready(self):
        """Test that old VPS is deleted when all conditions met."""
        job = ReplacementJob(id=1, node_id=1, node_name="test-node")
        job.status = ReplacementStatus.COMPLETED
        job.new_vps_id = "new-vps"
        job.new_vps_ip = "1.2.3.4"
        job.deployment_verified = True
        job.master_updated = True
        job.old_vps_deleted = False
        assert job.should_delete_old_vps()

    def test_should_delete_old_vps_false_when_already_deleted(self):
        """Test that old VPS is not deleted twice."""
        job = ReplacementJob(id=1, node_id=1, node_name="test-node")
        job.status = ReplacementStatus.COMPLETED
        job.new_vps_id = "new-vps"
        job.new_vps_ip = "1.2.3.4"
        job.deployment_verified = True
        job.master_updated = True
        job.old_vps_deleted = True
        assert not job.should_delete_old_vps()

    def test_can_retry(self):
        """Test retry logic."""
        job = ReplacementJob(id=1, node_id=1, node_name="test-node", attempt_number=1, max_attempts=5)
        assert job.can_retry()

        job.attempt_number = 5
        assert not job.can_retry()

        job.status = ReplacementStatus.COMPLETED
        assert not job.can_retry()

    def test_increment_attempt(self):
        """Test incrementing attempt counter."""
        job = ReplacementJob(id=1, node_id=1, node_name="test-node")
        initial_retry = job.retry_count
        job.increment_attempt()
        assert job.attempt_number == 2
        assert job.retry_count == initial_retry + 1


class TestVPSInfo:
    """Tests for VPSInfo model."""

    def test_create_vps(self):
        """Test creating VPS info."""
        vps = VPSInfo(id="vps-123", provider="hetzner", ipv4="1.2.3.4")
        assert vps.id == "vps-123"
        assert vps.provider == "hetzner"
        assert vps.ipv4 == "1.2.3.4"

    def test_is_active(self):
        """Test active status check."""
        vps = VPSInfo(id="vps-123", provider="hetzner", status="active")
        assert vps.is_active()

        vps.status = "inactive"
        assert not vps.is_active()

    def test_has_ip(self):
        """Test IP presence check."""
        vps = VPSInfo(id="vps-123", provider="hetzner", ipv4="1.2.3.4")
        assert vps.has_ip()

        vps.ipv4 = None
        assert not vps.has_ip()

    def test_to_dict(self):
        """Test dictionary conversion."""
        vps = VPSInfo(id="vps-123", provider="hetzner", ipv4="1.2.3.4")
        data = vps.to_dict()
        assert data["id"] == "vps-123"
        assert data["provider"] == "hetzner"
        assert data["ipv4"] == "1.2.3.4"

    def test_from_dict(self):
        """Test dictionary parsing."""
        data = {
            "id": "vps-123",
            "provider": "hetzner",
            "ipv4": "1.2.3.4",
            "status": "active",
        }
        vps = VPSInfo.from_dict(data)
        assert vps.id == "vps-123"
        assert vps.provider == "hetzner"
        assert vps.ipv4 == "1.2.3.4"
        assert vps.status == "active"
