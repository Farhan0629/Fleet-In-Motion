import asyncio
from dataclasses import dataclass, field
import time

@dataclass
class P2PMessage:
    """A single peer-to-peer message between robots."""
    sender_id: int          # robot who sent it
    msg_type: str           # from MESSAGE_TYPES in config.py
    payload: dict           # message data
    timestamp: float = field(default_factory=time.time)
    epoch: int = 0

class P2PNetwork:
    """
    Simulated peer-to-peer network.
    Each robot gets its own inbox (asyncio.Queue).
    No central broker — robots send directly to peers.
    """
    
    def __init__(self):
        self.inboxes: dict[int, asyncio.Queue] = {}
        self.message_log: list[dict] = []
        self.is_partitioned: dict[int, bool] = {}
        self.epochs: dict[int, int] = {}
    
    def register_robot(self, robot_id: int):
        """Create an inbox for a new robot."""
        self.inboxes[robot_id] = asyncio.Queue()
        self.is_partitioned[robot_id] = False
        self.epochs[robot_id] = self.epochs.get(robot_id, 0) + 1
    
    def broadcast(self, sender_id: int, msg_type: str, payload: dict):
        """
        Send message from sender to ALL other robots' inboxes.
        Skip if sender is network-partitioned (simulates Wi-Fi dead zone).
        """
        if self.is_partitioned.get(sender_id, False):
            return
        
        msg = P2PMessage(sender_id=sender_id, msg_type=msg_type, payload=dict(payload), epoch=self.epochs.get(sender_id, 0))
        
        for robot_id, inbox in self.inboxes.items():
            if robot_id != sender_id and not self.is_partitioned.get(robot_id, False):
                inbox.put_nowait(msg)
        
        self.message_log.append({
            "from": sender_id,
            "to": "all",
            "type": msg_type,
            "tick": payload.get("tick", 0)
        })
    
    def send_direct(self, sender_id: int, target_id: int, msg_type: str, payload: dict):
        """Send message to a specific robot (used for task bid responses)."""
        if self.is_partitioned.get(sender_id, False) or self.is_partitioned.get(target_id, False):
            return
        
        msg = P2PMessage(sender_id=sender_id, msg_type=msg_type, payload=dict(payload), epoch=self.epochs.get(sender_id, 0))
        if target_id in self.inboxes:
            self.inboxes[target_id].put_nowait(msg)
            self.message_log.append({
                "from": sender_id,
                "to": target_id,
                "type": msg_type,
                "tick": payload.get("tick", 0)
            })
    
    def receive_all(self, robot_id: int) -> list[P2PMessage]:
        """Drain all messages from a robot's inbox. Non-blocking."""
        messages = []
        if robot_id not in self.inboxes:
            return messages
        inbox = self.inboxes[robot_id]
        while not inbox.empty():
            try:
                msg = inbox.get_nowait()
                # Queued pre-partition/previous-connection packets are not truth.
                if (not self.is_partitioned.get(robot_id, False)
                        and not self.is_partitioned.get(msg.sender_id, False)
                        and msg.epoch == self.epochs.get(msg.sender_id, 0)):
                    messages.append(msg)
            except asyncio.QueueEmpty:
                break
        return messages
    
    def get_recent_messages(self, last_n: int = 20) -> list[dict]:
        """Return last N messages for dashboard visualization."""
        return self.message_log[-last_n:]
    
    def partition_robot(self, robot_id: int):
        """Simulate network partition (Wi-Fi dead zone)."""
        self.is_partitioned[robot_id] = True
        self.epochs[robot_id] = self.epochs.get(robot_id, 0) + 1
        self._clear_inbox(robot_id)
    
    def restore_robot(self, robot_id: int):
        """Restore a fresh connection, never replay old traffic predictions."""
        if self.is_partitioned.get(robot_id, False):
            self.epochs[robot_id] = self.epochs.get(robot_id, 0) + 1
            self._clear_inbox(robot_id)
        self.is_partitioned[robot_id] = False

    def _clear_inbox(self, robot_id):
        inbox = self.inboxes.get(robot_id)
        if inbox:
            while not inbox.empty():
                inbox.get_nowait()
    
    def partitioned_ids(self) -> list[int]:
        """Robot ids currently inside a Wi-Fi dead zone."""
        return sorted(rid for rid, offline in self.is_partitioned.items() if offline)
    
    def clear_log(self):
        """Clear message log."""
        self.message_log.clear()
