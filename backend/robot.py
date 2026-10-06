import time
from config import (
    BATTERY_MAX,
    BATTERY_CHARGE_PER_TICK,
    BATTERY_CHARGED_LEVEL,
    BATTERY_DRAIN_PER_MOVE,
    BATTERY_DRAIN_IDLE,
    BATTERY_LOW_THRESHOLD,
    LOOKAHEAD_WINDOW,
    P2P_BROADCAST_INTERVAL,
    SENSOR_RANGE,
    robot_name,
)
from pathfinding import a_star

# How many consecutive blocked ticks a unit tolerates before it stops waiting
# and asks its onboard planner for a different route.
REPLAN_AFTER_WAITS = 2
PEER_MEMORY_TICKS = max(3, 3 * P2P_BROADCAST_INTERVAL)

class Robot:
    """
    Independent, decentralized robot agent.
    Simulates edge computing — all decisions are local.
    """
    
    def __init__(self, robot_id: int, start_pos: tuple[int, int], warehouse, battery: float | None = None):
        self.id = robot_id
        self.name = robot_name(robot_id)
        
        # Physical state
        self.x, self.y = start_pos
        self.prev_x, self.prev_y = start_pos  # for frontend interpolation
        self.heading = 0                      # 0=right, 90=down, 180=left, 270=up
        self.battery = float(BATTERY_MAX if battery is None else battery)
        
        # Task state
        self.status = "idle"  # "idle" | "moving_to_pickup" | "moving_to_dropoff" | "waiting" | "charging" | "moving_to_charge"
        self.carrying = False # True once item is picked up
        self.current_task = None
        self.last_delivered_task_id = None
        self.abandoned_task = None
        self.planned_path = []
        self.path_index = 0
        self.navigation_message = None
        self.navigation_blocked_reason = None
        self._reported_navigation_message = None
        self._barrier_snapshot = frozenset(warehouse.blocked_cells)
        self._current_tick = 0
        self.known_peer_intent_ticks = {}
        
        # Energy state. `target_charger` is the pad this unit has claimed over
        # the mesh; it survives transient "waiting" states, so a unit that is
        # briefly blocked on the way to a pad does not forget it was charging.
        self.target_charger = None
        self.known_charger_claims = {}   # {(x,y): (robot_id, cost)}
        self.charge_cycles = 0
        self.charge_started_tick = None
        self.charge_started_battery = None
        self.charge_reason = None        # "low_battery" | "end_of_round"
        # True once the round is finished and this unit is docked on its pad
        # for the shift. A parked unit does not bid, does not wander and does
        # not give up the pad it is standing on.
        self.parked = False
        self._deferred_charge_logged = False
        
        # Decentralized knowledge (learned from P2P messages ONLY)
        self.known_peer_positions = {}  # {robot_id: (x, y, tick)}
        self.known_peer_intents = {}    # {robot_id: [(x,y), ...]}
        self.known_peer_dists = {}      # {robot_id: int}
        
        # Metrics
        self.decision_time_ms = 0.0
        self.tasks_completed = 0
        self.total_distance = 0
        self.wait_ticks = 0
        self.consecutive_waits = 0
        self.is_yielding = False
        
        # Environment reference
        self.warehouse = warehouse
        # Publish our physical footprint so peers can sense us even if the
        # radio link is down.
        warehouse.set_occupancy(self.id, (self.x, self.y))
    
    def tick(self, current_tick: int, p2p_network, event_logger=None) -> str:
        """
        Main agent loop called once per simulation tick.
        Returns action taken: "moved", "waited", "picked_up", "delivered", "idle", etc.
        """
        start_time = time.perf_counter()
        
        self._current_tick = current_tick
        self._expire_peer_memory(current_tick)

        # 1. Process incoming P2P messages
        messages = p2p_network.receive_all(self.id)
        self._process_messages(messages, event_logger, current_tick)
        self._expire_peer_memory(current_tick)
        
        # 2. Broadcast position & intent at start of tick
        if current_tick % P2P_BROADCAST_INTERVAL == 0:
            self._broadcast_position(p2p_network, current_tick)
            self._broadcast_intent(p2p_network, current_tick)
        
        # 3. Save previous position for interpolation
        self.prev_x, self.prev_y = self.x, self.y
        
        # 4. Decide and act
        action = self._decide_and_act(current_tick, p2p_network, event_logger)
        
        # Emit only transitions, not one warning per tick.
        if self.navigation_message != self._reported_navigation_message:
            if event_logger:
                event_logger.add_event(
                    "hazard" if self.navigation_message else "reroute",
                    f"{self.name}: {self.navigation_message or 'Route available again'}",
                    robot_id=self.id, tick=current_tick,
                )
            self._reported_navigation_message = self.navigation_message

        # 5. Update battery
        if action == "moved":
            self.battery = max(0.0, self.battery - BATTERY_DRAIN_PER_MOVE)
        else:
            self.battery = max(0.0, self.battery - BATTERY_DRAIN_IDLE)
        
        # 6. Low battery check: book a pad and detour, autonomously.
        if (
            self.battery <= BATTERY_LOW_THRESHOLD
            and self.status != "charging"
            and self.target_charger is None
        ):
            carried_id = self.current_task["id"] if (self.carrying and self.current_task) else None
            abandoned_id = self.current_task["id"] if (self.current_task and not self.carrying) else None
            self._go_to_charging(p2p_network, current_tick)
            if event_logger:
                if self.target_charger is not None:
                    pad = self._charger_label(self.target_charger)
                    detail = (
                        f" \\u2014 package #{abandoned_id} handed back to the auction"
                        if abandoned_id else ""
                    )
                    event_logger.add_event(
                        "charging",
                        f"{self.name} at {self.battery:.0f}% claimed {pad} over the mesh and is detouring to charge{detail}",
                        robot_id=self.id,
                        tick=current_tick,
                    )
                elif carried_id and not self._deferred_charge_logged:
                    self._deferred_charge_logged = True
                    event_logger.add_event(
                        "charging",
                        f"{self.name} at {self.battery:.0f}% will finish delivering package #{carried_id} before charging",
                        robot_id=self.id,
                        tick=current_tick,
                    )
        
        self.decision_time_ms = (time.perf_counter() - start_time) * 1000.0
        return action
    
    def _process_messages(self, messages, event_logger=None, tick: int = 0):
        for msg in messages:
            if msg.msg_type == "pos":
                if msg.payload.get("tick", tick) < self.known_peer_positions.get(msg.sender_id, (0, 0, -1))[2]:
                    continue
                self.known_peer_positions[msg.sender_id] = (
                    msg.payload["x"],
                    msg.payload["y"],
                    msg.payload.get("tick", tick),
                )
            elif msg.msg_type == "intent":
                intent_tick = msg.payload.get("tick", tick)
                if intent_tick < self.known_peer_intent_ticks.get(msg.sender_id, -1):
                    continue
                self.known_peer_intent_ticks[msg.sender_id] = intent_tick
                self.known_peer_intents[msg.sender_id] = msg.payload.get("path", [])
                self.known_peer_dists[msg.sender_id] = msg.payload.get("dist", len(self.known_peer_intents[msg.sender_id]))
            elif msg.msg_type == "blocked":
                blocked_cell = (msg.payload["x"], msg.payload["y"])
                self._handle_blocked_aisle(blocked_cell, event_logger, tick)
            elif msg.msg_type == "charger_claim":
                cell = tuple(msg.payload["cell"])
                self.known_charger_claims[cell] = (msg.sender_id, msg.payload.get("cost", 0))
            elif msg.msg_type == "charger_release":
                cell = tuple(msg.payload["cell"])
                holder = self.known_charger_claims.get(cell)
                if holder and holder[0] == msg.sender_id:
                    self.known_charger_claims.pop(cell, None)
    
    def _broadcast_position(self, p2p_network, tick: int):
        p2p_network.broadcast(
            self.id,
            "pos",
            {"x": self.x, "y": self.y, "tick": tick},
        )
    
    def _broadcast_intent(self, p2p_network, tick: int):
        remaining_path = self.planned_path[self.path_index:] if self.planned_path else []
        p2p_network.broadcast(
            self.id,
            "intent",
            {
                "path": remaining_path[:LOOKAHEAD_WINDOW],
                "dist": self._distance_to_goal(),
                "tick": tick,
            },
        )
    
    # ─── Charging pad negotiation ─────────────────────────────────────────
    
    def _charge_cost(self, pad) -> int:
        return abs(pad[0] - self.x) + abs(pad[1] - self.y)
    
    def _charger_label(self, pad) -> str:
        try:
            return f"CHARGE {self.warehouse.charging_stations.index(tuple(pad)) + 1}"
        except (ValueError, AttributeError):
            return "charging pad"
    
    def _select_charger(self, exclude=()):
        """Nearest pad that nobody else has claimed or is standing on.
        
        Claims arrive over the mesh; occupancy also comes from onboard sensing,
        so a radio-silent unit still refuses a pad it can see is taken.
        """
        pads = [pad for pad in self.warehouse.charging_stations if tuple(pad) not in exclude]
        if not pads:
            return None
        sensed = self._sensed_cells()
        free = []
        for pad in pads:
            claim = self.known_charger_claims.get(tuple(pad))
            if claim and claim[0] != self.id:
                continue
            if tuple(pad) in sensed:
                continue
            free.append(pad)
        pool = free or pads
        return tuple(min(pool, key=lambda pad: (self._charge_cost(pad), pad[0], pad[1])))
    
    def _claim_charger(self, pad, p2p_network=None, tick: int = 0):
        pad = tuple(pad)
        cost = self._charge_cost(pad)
        self.target_charger = pad
        self.known_charger_claims[pad] = (self.id, cost)
        if p2p_network:
            p2p_network.broadcast(self.id, "charger_claim", {"cell": list(pad), "cost": cost, "tick": tick})
    
    def _release_charger(self, p2p_network=None, tick: int = 0):
        pad = self.target_charger
        self.target_charger = None
        if pad is None:
            return
        holder = self.known_charger_claims.get(pad)
        if holder and holder[0] == self.id:
            self.known_charger_claims.pop(pad, None)
        if p2p_network:
            p2p_network.broadcast(self.id, "charger_release", {"cell": list(pad), "tick": tick})
    
    def _resolve_charger_conflict(self, p2p_network=None, tick: int = 0, event_logger=None):
        """Two units must never book the same pad.
        
        Whoever is closer keeps it; ties break on the lower unit id, so both
        sides of the conflict reach the same verdict from local state alone.
        """
        pad = self.target_charger
        if pad is None:
            return
        claim = self.known_charger_claims.get(pad)
        if not claim or claim[0] == self.id:
            return
        peer_id, peer_cost = claim
        mine = (self._charge_cost(pad), self.id)
        theirs = (peer_cost, peer_id)
        if mine < theirs:
            # We win: restate the claim so the peer hears it and backs off.
            self._claim_charger(pad, p2p_network, tick)
            return
        alternative = self._select_charger(exclude=(pad,))
        self.target_charger = None
        if alternative is None:
            self.status = "waiting"
            return
        self._claim_charger(alternative, p2p_network, tick)
        self.status = "moving_to_charge"
        self._replan_path(p2p_network, tick)
        if event_logger:
            event_logger.add_event(
                "charging",
                f"{self.name} yielded {self._charger_label(pad)} to {robot_name(peer_id)} "
                f"and rebooked {self._charger_label(alternative)}",
                robot_id=self.id,
                tick=tick,
            )
    
    def _begin_charging(self, tick: int, event_logger=None) -> str:
        self.status = "charging"
        self.planned_path = []
        self.path_index = 0
        self.charge_started_tick = tick
        self.charge_started_battery = self.battery
        if event_logger:
            reason = (
                " \\u2014 round complete, parking for the shift"
                if self.charge_reason == "end_of_round" else " \\u2014 cable connected"
            )
            event_logger.add_event(
                "charging",
                f"{self.name} docked at {self._charger_label(self.target_charger)} with {self.battery:.0f}%{reason}",
                robot_id=self.id,
                tick=tick,
            )
        return "charging"

    def park_for_charging(self, p2p_network=None, tick: int = 0, event_logger=None) -> bool:
        """End of round: book a pad, drive to it and stay there.

        Called once the manifest is empty. It uses exactly the same mesh
        negotiation as a low-battery detour, so two units still never claim the
        same pad, and it refuses to run while the unit is holding a carton.
        """
        if self.parked or self.carrying or self.current_task is not None:
            return False
        if self.status == "charging" or self.target_charger is not None:
            return False
        pad = self._select_charger()
        if pad is None:
            return False
        self.charge_reason = "end_of_round"
        self.status = "moving_to_charge"
        self._claim_charger(pad, p2p_network, tick)
        self._replan_path(p2p_network, tick)
        if event_logger:
            event_logger.add_event(
                "charging",
                f"{self.name} finished the round at {self.battery:.0f}% and claimed "
                f"{self._charger_label(pad)} over the mesh to dock and charge",
                robot_id=self.id,
                tick=tick,
            )
        return True
    
    def _decide_and_act(self, tick: int, p2p_network, event_logger=None) -> str:
        self.is_yielding = False
        # Barrier state is checked locally, including when mesh packets are lost.
        barriers = frozenset(self.warehouse.blocked_cells)
        if barriers != self._barrier_snapshot:
            self._barrier_snapshot = barriers
            self._replan_path(p2p_network, tick)

        # Pad bookings are renegotiated before anything else moves. A unit that
        # is already parked on its pad keeps it - it is physically there.
        if self.target_charger is not None and self.status != "charging" and not self.parked:
            self._resolve_charger_conflict(p2p_network, tick, event_logger)
        
        if self.status == "idle":
            # Even an idle unit reports a barrier placed around its footprint.
            enclosed = not self.warehouse.get_neighbors(self.x, self.y)
            structurally_open = any(self.warehouse._structurally_walkable(*cell)
                                    for cell in ((self.x+1, self.y), (self.x-1, self.y),
                                                 (self.x, self.y+1), (self.x, self.y-1)))
            self.navigation_message = "Please remove the barrier" if enclosed and barriers and structurally_open else None
            self.navigation_blocked_reason = "barrier" if self.navigation_message else None
            # A parked unit is docked on its pad and stays put.
            if self.parked:
                return "idle"
            # If an active peer intends to enter our cell on its next step, politely yield/step aside
            for peer_id, intent in self.known_peer_intents.items():
                if intent and (intent[0] == (self.x, self.y) or (self.x, self.y) in intent[:3]):
                    neighbors = self.warehouse.get_neighbors(self.x, self.y)
                    occupied = self._occupied_cells()
                    free = [n for n in neighbors if n not in occupied and n != (self.x, self.y)]
                    best_free = [n for n in free if n not in intent]
                    chosen = best_free[0] if best_free else (free[0] if free else None)
                    if chosen:
                        self.is_yielding = True
                        self._move_to(chosen, p2p_network, tick)
                        return "stepped_aside"
            return "idle"
        
        if self.status == "charging":
            self.battery = min(float(BATTERY_MAX), self.battery + BATTERY_CHARGE_PER_TICK)
            if self.battery >= BATTERY_CHARGED_LEVEL:
                opening = self.charge_started_battery
                gained = self.battery - opening if opening is not None else 0.0
                end_of_round = self.charge_reason == "end_of_round"
                pad_label = self._charger_label(self.target_charger)
                if gained >= 1.0:
                    self.charge_cycles += 1
                self.status = "idle"
                self.charge_started_tick = None
                self.charge_started_battery = None
                self.charge_reason = None
                self._deferred_charge_logged = False
                if end_of_round:
                    # Keep the pad: the unit is standing on it until the next
                    # round starts, so the booking stays honest on the mesh.
                    self.parked = True
                else:
                    self._release_charger(p2p_network, tick)
                if event_logger:
                    if end_of_round:
                        event_logger.add_event(
                            "charging",
                            f"{self.name} is charged to {self.battery:.0f}% and parked on {pad_label} for the shift",
                            robot_id=self.id,
                            tick=tick,
                        )
                    else:
                        event_logger.add_event(
                            "charging",
                            f"{self.name} charged to {self.battery:.0f}%, released {pad_label} over the mesh and rejoined the auction",
                            robot_id=self.id,
                            tick=tick,
                        )
                return "charged" if gained >= 1.0 else "parked"
            return "charging"
        
        # A rack transfer may finish from any legal face of the same slot.
        if self.current_task and self._at_task_goal():
            return self._handle_arrival(tick, p2p_network)
        elif self.target_charger is not None and not self.current_task:
            if (self.x, self.y) == self.target_charger:
                return self._begin_charging(tick, event_logger)

        # Recheck the entire remaining route, not just the next waypoint.
        if any(not self.warehouse.is_walkable(*cell)
               for cell in self.planned_path[self.path_index:]):
            self._replan_path(p2p_network, tick)

        # Ensure we have a valid planned path
        if not self.planned_path or self.path_index >= len(self.planned_path):
            self._replan_path(p2p_network, tick)
            if not self.planned_path or self.path_index >= len(self.planned_path):
                self.status = "waiting"
                self.wait_ticks += 1
                return "stuck"
        
        next_cell = self.planned_path[self.path_index]
        
        # Check if next cell was dynamically blocked
        if not self.warehouse.is_walkable(next_cell[0], next_cell[1]):
            self._replan_path(p2p_network, tick)
            if event_logger:
                event_logger.add_event(
                    "reroute",
                    f"{self.name} encountered blocked cell at {next_cell} -> rerouted via onboard A*",
                    robot_id=self.id,
                    tick=tick
                )
            if not self.planned_path or self.path_index >= len(self.planned_path):
                self.status = "waiting"
                self.wait_ticks += 1
                return "stuck"
            next_cell = self.planned_path[self.path_index]
        
        # Collision avoidance check
        if self._would_collide(next_cell):
            self.status = "waiting"
            self.is_yielding = True
            self.wait_ticks += 1
            self.consecutive_waits += 1
            if self.consecutive_waits < REPLAN_AFTER_WAITS:
                return "waited"
            self._replan_path(p2p_network, tick)
            if not self.planned_path or self.path_index >= len(self.planned_path):
                return "waited"
            next_cell = self.planned_path[self.path_index]
            if self._would_collide(next_cell):
                return "waited"
            # A safe detour is available now; do not waste another tick waiting.
            self.is_yielding = False
            self.wait_ticks -= 1

        self.navigation_message = None
        self.navigation_blocked_reason = None

        # Clear consecutive wait counter on successful movement
        self.consecutive_waits = 0
        if self.current_task:
            self.status = "moving_to_dropoff" if self.carrying else "moving_to_pickup"
        elif self.target_charger is not None:
            self.status = "moving_to_charge"
        
        self._move_to(next_cell, p2p_network, tick)
        self.path_index += 1
        
        # Check arrival against all rack faces, not a single fixed waypoint.
        if self.current_task and self._at_task_goal():
            return self._handle_arrival(tick, p2p_network)
        elif self.target_charger is not None and not self.current_task and (self.x, self.y) == self.target_charger:
            return self._begin_charging(tick, event_logger)

        return "moved"
    
    def _expire_peer_memory(self, tick):
        for peer_id, info in list(self.known_peer_positions.items()):
            if tick - info[2] > PEER_MEMORY_TICKS:
                self.known_peer_positions.pop(peer_id, None)
        for peer_id, seen_tick in list(self.known_peer_intent_ticks.items()):
            if tick - seen_tick > PEER_MEMORY_TICKS:
                self.known_peer_intent_ticks.pop(peer_id, None)
                self.known_peer_intents.pop(peer_id, None)
                self.known_peer_dists.pop(peer_id, None)

    def _occupied_cells(self):
        occupied = self._sensed_cells()
        for px, py, seen_tick in self.known_peer_positions.values():
            if (self._current_tick - seen_tick <= PEER_MEMORY_TICKS
                    and abs(px - self.x) + abs(py - self.y) > SENSOR_RANGE):
                occupied.add((px, py))
        return occupied

    def _sensed_cells(self) -> set[tuple[int, int]]:
        """Cells physically occupied by peers inside onboard sensor range.

        This is deliberately independent of the P2P radio: a unit inside a
        Wi-Fi dead zone still has eyes, so it can never drive into a body it
        can see. Radio silence degrades coordination, not safety.
        """
        sensed = set()
        for peer_id, cell in self.warehouse.robot_occupancy.items():
            if peer_id == self.id:
                continue
            if abs(cell[0] - self.x) + abs(cell[1] - self.y) <= SENSOR_RANGE:
                sensed.add(cell)
        return sensed
    
    def _would_collide(self, next_cell: tuple[int, int]) -> bool:
        # Onboard proximity sensing first — always available.
        if next_cell in self._occupied_cells():
            return True
        
        for peer_id in self.known_peer_intents:
            # Future conflict in lookahead window
            peer_intent = self.known_peer_intents.get(peer_id, [])
            if not peer_intent:
                continue
            
            if next_cell in peer_intent[:LOOKAHEAD_WINDOW]:
                step_idx = peer_intent[:LOOKAHEAD_WINDOW].index(next_cell)
                # If peer is targeting this cell immediately or within 2 steps
                if step_idx <= 2:
                    my_dist = self._distance_to_goal()
                    peer_goal_dist = self.known_peer_dists.get(peer_id, len(peer_intent))
                    if my_dist > peer_goal_dist:
                        return True
                    elif my_dist == peer_goal_dist and self.id > peer_id:
                        return True
        return False
    
    def _distance_to_goal(self) -> int:
        if self.planned_path and self.path_index < len(self.planned_path):
            return len(self.planned_path) - self.path_index
        return 0
    
    def _move_to(self, cell: tuple[int, int], p2p_network=None, tick: int = 0):
        dx = cell[0] - self.x
        dy = cell[1] - self.y
        if dx == 1:
            self.heading = 0
        elif dx == -1:
            self.heading = 180
        elif dy == 1:
            self.heading = 90
        elif dy == -1:
            self.heading = 270
        self.x, self.y = cell
        self.total_distance += 1
        self.warehouse.set_occupancy(self.id, cell)
        
        if p2p_network:
            self._broadcast_position(p2p_network, tick)
    
    def _handle_arrival(self, tick: int, p2p_network) -> str:
        if not self.carrying and self.current_task:
            self.carrying = True
            self.status = "moving_to_dropoff"
            self._replan_path(p2p_network, tick)
            return "picked_up"
        
        elif self.carrying and self.current_task:
            self.last_delivered_task_id = self.current_task["id"]
            self.tasks_completed += 1
            self.carrying = False
            self.current_task = None
            self.planned_path = []
            self.path_index = 0
            self.status = "idle"
            self.navigation_message = None
            self.navigation_blocked_reason = None
            self._broadcast_position(p2p_network, tick)
            self._broadcast_intent(p2p_network, tick)
            return "delivered"
        
        return "idle"
    
    def _navigation_goals(self):
        if not self.current_task:
            return [self.target_charger] if self.target_charger is not None else []
        key = "dropoff" if self.carrying else "pickup"
        preferred = tuple(self.current_task[key])
        if self.current_task.get(f"{key}_kind") == "rack" and self.current_task.get("slot_cell"):
            faces = self.warehouse.rack_access_cells(self.current_task["slot_cell"])
            return sorted(faces, key=lambda cell: (cell != preferred, cell))
        return [preferred]

    def _set_navigation_goal(self, goal):
        if self.current_task:
            key = "dropoff" if self.carrying else "pickup"
            self.current_task[key] = tuple(goal)

    def _at_task_goal(self):
        cell = (self.x, self.y)
        if self.warehouse.is_walkable(*cell) and cell in self._navigation_goals():
            self._set_navigation_goal(cell)
            self.navigation_message = None
            self.navigation_blocked_reason = None
            return True
        return False

    def _replan_path(self, p2p_network=None, tick: int = 0):
        if not self.current_task and self.target_charger is None:
            self.planned_path = []
            self.path_index = 0
            self.navigation_message = None
            self.navigation_blocked_reason = None
            return
        
        goals = self._navigation_goals()
        start = (self.x, self.y)
        # Check every face of a rack slot before declaring its carton blocked.
        terrain_routes = [(goal, route) for goal in goals
                          if (route := a_star(self.warehouse, start, goal)) is not None]
        if not terrain_routes:
            barrier_caused = bool(self.warehouse.blocked_cells) and any(
                a_star(self.warehouse, start, goal, ignore_barriers=True) is not None
                for goal in goals
            )
            self.navigation_blocked_reason = "barrier" if barrier_caused else "unreachable"
            self.navigation_message = "Please remove the barrier" if barrier_caused else "Destination unreachable"
            path = None
        else:
            self.navigation_message = None
            self.navigation_blocked_reason = None
            occupied = self._occupied_cells()
            if self.consecutive_waits >= REPLAN_AFTER_WAITS:
                occupied |= {tuple(cell) for intent in self.known_peer_intents.values()
                             for cell in intent[:3] if self._would_collide(tuple(cell))}
            safe_routes = [(goal, route) for goal, _ in terrain_routes
                           if (goal not in occupied or goal == start)
                           and (route := a_star(self.warehouse, start, goal, occupied)) is not None]
            # Preserve the current face when reachable; choose another safe face
            # if blocked. Physical slot identity and cargo reservation never change.
            goal, path = min(safe_routes or terrain_routes,
                             key=lambda item: (goals.index(item[0]), len(item[1])))
            self._set_navigation_goal(goal)

        self.planned_path = path or []
        self.path_index = 1 if self.planned_path and len(self.planned_path) > 1 else 0
        if p2p_network:
            self._broadcast_intent(p2p_network, tick)
    
    def _handle_blocked_aisle(self, blocked_cell, event_logger=None, tick: int = 0):
        if self.planned_path and blocked_cell in self.planned_path[self.path_index:]:
            self._replan_path()
            if event_logger:
                event_logger.add_event(
                    "reroute",
                    f"{self.name} heard a blocked-aisle alert at {blocked_cell} -> "
                    f"{self.navigation_message or 'recalculated A* route'}",
                    robot_id=self.id,
                    tick=tick,
                )
    
    def _go_to_charging(self, p2p_network=None, tick: int = 0):
        if not self.warehouse.charging_stations:
            return
        # If currently carrying cargo, complete delivery to dropoff first before charging
        if self.carrying and self.current_task:
            return
        
        pad = self._select_charger()
        if pad is None:
            return
        self.charge_reason = "low_battery"
        if self.current_task:
            self.abandoned_task = self.current_task
        self.current_task = None
        self.carrying = False
        self.status = "moving_to_charge"
        self._claim_charger(pad, p2p_network, tick)
        self._replan_path(p2p_network, tick)
    
    def calculate_bid(self, task: dict) -> float:
        pickup = task["pickup"]
        dropoff = task["dropoff"]
        dist_to_pickup = abs(pickup[0] - self.x) + abs(pickup[1] - self.y)
        dist_to_dropoff = abs(dropoff[0] - pickup[0]) + abs(dropoff[1] - pickup[1])
        total_dist = dist_to_pickup + dist_to_dropoff + 1
        battery_factor = self.battery / float(BATTERY_MAX)
        
        if self.status != "idle" or self.current_task is not None:
            return 0.0
        # A unit parked on its pad at the end of a round is off shift.
        if self.parked:
            return 0.0
        # A unit that is about to detour for energy does not take new work: it
        # would only abandon the package a tick later.
        if self.target_charger is not None or self.battery <= BATTERY_LOW_THRESHOLD:
            return 0.0
        
        return battery_factor / float(total_dist)
    
    def assign_task(self, task: dict):
        self.current_task = task
        self.carrying = False
        self.status = "moving_to_pickup"
        self.consecutive_waits = 0
        self._replan_path()
    
    def to_dict(self) -> dict:
        remaining_path = self.planned_path[self.path_index:] if self.planned_path else []
        status_str = "yielding" if getattr(self, "is_yielding", False) else self.status
        return {
            "id": self.id,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "prev_x": self.prev_x,
            "prev_y": self.prev_y,
            "heading": self.heading,
            "battery": round(self.battery, 1),
            "battery_low": self.battery <= BATTERY_LOW_THRESHOLD,
            "status": status_str,
            "navigation_message": self.navigation_message,
            "navigation_blocked_reason": self.navigation_blocked_reason,
            "is_yielding": getattr(self, "is_yielding", False),
            "task": self.current_task,
            "has_cargo": self.carrying,
            "carrying_task_id": self.current_task["id"] if (self.carrying and self.current_task) else None,
            "planned_path": remaining_path,
            "decision_ms": round(self.decision_time_ms, 2),
            "tasks_completed": self.tasks_completed,
            "total_distance": self.total_distance,
            "wait_ticks": self.wait_ticks,
            "charger": list(self.target_charger) if self.target_charger else None,
            "charger_label": self._charger_label(self.target_charger) if self.target_charger else None,
            "charge_cycles": self.charge_cycles,
            "charge_reason": self.charge_reason,
            "parked": self.parked,
        }
