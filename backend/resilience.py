"""Phase 7 recovery/custody hooks around the existing task queue and P2P network.

The same task, carton and destination survive a failure. Only the pickup endpoint
changes for an adjacent physical handoff. This module never awards tasks or moves
robots; TaskManager's existing auction and Robot's A* do that.
"""
import math
from pathfinding import a_star


class FleetResilience:
    def __init__(self, manager):
        self.manager = manager
        self.records = []
        self.robot_failures = 0
        self.successful_recoveries = 0
        self.communication_losses = 0
        self.reconciliations = 0
        self.tasks_reassigned = 0
        self.cargo_recovered = 0
        self.recovery_ticks = []

    def _task(self, robot):
        return self.manager.find_task(robot.current_task['id']) if robot.current_task else None

    def fail_robot(self, robot, robots, network, tick):
        mission = self.manager.consolidation
        task = self._task(robot)
        if not mission.started or mission.status in ('completed', 'failed', 'partial'):
            raise ValueError('Robot failure drills require an active consolidation mission')
        if getattr(robot, 'failed', False) or not robot.available or task is None:
            raise ValueError('Select an available robot with an active task')
        if getattr(robot, 'handling', None):
            raise ValueError('Let the physical lift/placement finish before simulating failure')
        if task.status not in ('assigned', 'recovery_assigned', 'recovered'):
            raise ValueError('This task is not in a fail-safe drill state')
        carrying = robot.carrying
        if task.picked_up != carrying:
            raise ValueError('Cargo ownership is transitioning; wait for the lift to finish')
        if carrying and task.recovery_required:
            raise ValueError('Let the handoff finish before another failure')
        if robot.target_charger is not None:
            robot._release_charger(network, tick)
        if carrying:
            # Keep the failed unit's body and cargo where they actually are.
            if task in self.manager.active_tasks:
                self.manager.active_tasks.remove(task)
            task.recovery_required = True
            task.recovery_cell = (robot.x, robot.y)
            radians = math.radians(robot.heading)
            task.recovery_cargo_position = [robot.x + .5 + .35 * math.cos(radians), 1.04,
                                            robot.y + .5 + .35 * math.sin(radians)]
            task.cargo_owner = f'robot:{robot.id}'
            task.cargo_state = 'recovery_required'
            # Original target reservation must survive a carrying failure.
        else:
            self.manager._detach_robot(task, robots)
            self.manager._release_source_claim(task)
            self.manager._release_destination(task)
            task.reservations_released = True
            task.cargo_state = 'stored'
            task.cargo_owner = f'rack:{task.pickup_slot_code}'
        task.status = 'recovery_pending'
        task.failed_robot_id = robot.id
        task.recovery_robot_id = None
        task.assigned_to = None
        task.priority = 5
        task.failure_reason = 'Robot failed; awaiting recovery auction'
        self.manager.pending_tasks.append(task)
        robot.failed = True
        robot.available = False
        robot.availability_reason = 'simulated robot failure'
        robot.status = 'failed'
        robot.is_yielding = False
        robot.prev_x, robot.prev_y = robot.x, robot.y
        robot.planned_path = []; robot.path_index = 0
        self.robot_failures += 1
        self.records.append({'task_id': task.id, 'cargo_id': task.cargo_id,
                             'failed_robot_id': robot.id, 'recovery_robot_id': None,
                             'case': 'carrying' if carrying else 'before_pickup',
                             'destination': task.dropoff_slot_code, 'failure_tick': tick,
                             'handoff_tick': None, 'completion_tick': None, 'status': 'recovery_pending'})
        # Stationary footprint replaces the last moving intent; radio loss is
        # independent, so an offline failed robot cannot broadcast magically.
        robot._broadcast_position(network, tick)
        robot._broadcast_intent(network, tick)
        if not network.is_partitioned.get(robot.id, False):
            self.publish_snapshot(robot, robots, network, tick)
        return task

    def restore_robot(self, robot, robots, network, tick):
        if not getattr(robot, 'failed', False):
            raise ValueError('This robot is not failed')
        if robot.carrying or robot.current_task or getattr(robot, 'handling', None):
            raise ValueError('Cargo must be recovered before the failed robot returns to service')
        robot.failed = False
        robot.set_available(True)
        robot.status = 'idle'
        robot.navigation_message = None
        robot.navigation_blocked_reason = None
        self.publish_snapshot(robot, robots, network, tick)

    def refresh(self, robots, network, tick):
        # Before-pickup failure releases old claims. Reacquire the same valid
        # carton and destination before re-entering the original fleet auction.
        for task in self.manager.pending_tasks:
            if not task.reservations_released:
                continue
            source = self.manager.warehouse.get_slot(task.pickup_slot_id)
            dest = self.manager.warehouse.get_slot(task.dropoff_slot_id)
            if (source['state'] == 'stored' and source['cargo_id'] == task.cargo_id
                    and source['task_id'] is None and dest['state'] == 'empty'):
                if self.manager.warehouse.reserve_slot(dest['id'], task.id):
                    source['task_id'] = task.id
                    task.reservations_released = False
                    task.failure_reason = 'Task ready for recovery auction'
            else:
                task.failure_reason = 'Recovery blocked: original source carton or destination unavailable'
        # Expire learned peer data even while a failed/handling unit is frozen.
        for robot in robots:
            robot._expire_peer_memory(tick)

    def auction_payload(self, task, robot):
        if task.failed_robot_id == robot.id:
            return None  # A recovery drill must select another robot.
        if task.reservations_released:
            return None
        payload = task.as_payload()
        if not task.recovery_required:
            return payload
        warehouse = self.manager.warehouse
        x, y = task.recovery_cell
        body = {(x, y)}
        choices = []
        for cell in ((x-1,y), (x+1,y), (x,y-1), (x,y+1)):
            if not warehouse.is_walkable(*cell):
                continue
            route = a_star(warehouse, (robot.x, robot.y), cell, body)
            if route is None:
                continue
            drop_routes = [path for goal in warehouse.rack_access_cells(task.dropoff_slot_cell)
                           if warehouse.is_walkable(*goal)
                           and (path := a_star(warehouse, cell, goal, body)) is not None]
            if drop_routes:
                choices.append((len(route) + min(map(len, drop_routes)), cell))
        if not choices:
            task.failure_reason = 'Recovery pending: no feasible adjacent handoff/delivery route'
            return None
        payload['pickup'] = min(choices)[1]
        return payload

    def assigned(self, task, robot, tick):
        if task.failed_robot_id is None:
            return
        task.recovery_robot_id = robot.id
        task.failure_reason = None
        task.status = 'recovery_assigned' if task.recovery_required else 'assigned'
        self.tasks_reassigned += 1
        record = next((r for r in reversed(self.records) if r['task_id'] == task.id and r['completion_tick'] is None), None)
        if record:
            record.update(recovery_robot_id=robot.id, status=task.status)

    def begin_handoff(self, robot, robots, network, tick):
        task = self._task(robot)
        failed = next((r for r in robots if task and r.id == task.failed_robot_id), None)
        if (task is None or not task.recovery_required or task.assigned_to != robot.id
                or failed is None or not failed.failed or not failed.carrying
                or failed.current_task is None or failed.current_task['id'] != task.id
                or task.cargo_owner != f'robot:{failed.id}'
                or abs(robot.x-failed.x) + abs(robot.y-failed.y) != 1
                or not self.manager.warehouse.is_walkable(robot.x, robot.y)):
            raise ValueError('Cargo handoff requires the assigned robot beside its failed owner')
        dest = self.manager.warehouse.get_slot(task.dropoff_slot_id)
        if dest['state'] != 'reserved' or dest['task_id'] != task.id:
            raise ValueError('Original destination reservation must exist before handoff')
        # One atomic custody transition, at actual contact, into transfer dwell.
        failed.carrying = False
        failed.current_task = None
        failed.handling = None
        failed._handling_start = None
        task.cargo_owner = f'robot:{robot.id}'
        task.cargo_state = 'handoff'
        task.status = 'recovering'
        task.failure_reason = None
        record = next(r for r in reversed(self.records) if r['task_id'] == task.id and r['completion_tick'] is None)
        record['status'] = 'recovering'
        self.publish_snapshot(failed, robots, network, tick)
        self.publish_snapshot(robot, robots, network, tick)

    def action(self, robot, action, robots, network, tick):
        task = self._task(robot)
        if task is None:
            return
        if action == 'handling' and robot.handling['progress'] == 0 and robot.handling['kind'] == 'pickup':
            if robot.handling['place'] == 'recovery':
                self.begin_handoff(robot, robots, network, tick)
            else:
                task.cargo_owner = f'robot:{robot.id}'
                task.cargo_state = 'pickup_transfer'
        elif action == 'picked_up':
            task.cargo_owner = f'robot:{robot.id}'
            task.cargo_state = 'carrying'
            if task.recovery_required:
                task.recovery_required = False
                task.status = 'recovered'
                robot.current_task['recovery_required'] = False
                self.cargo_recovered += 1
                record = next(r for r in reversed(self.records) if r['task_id'] == task.id and r['completion_tick'] is None)
                record.update(handoff_tick=tick, status='recovered')
                self.publish_snapshot(robot, robots, network, tick)

    def delivered(self, task, tick):
        task.cargo_owner = f'rack:{task.dropoff_slot_code}' if task.dropoff_kind == 'rack' else f'table:{tuple(task.dropoff)}'
        task.cargo_state = 'stored' if task.dropoff_kind == 'rack' else 'delivered'
        for record in self.records:
            if record['task_id'] == task.id and record['completion_tick'] is None:
                record.update(completion_tick=tick, status='completed')
                self.successful_recoveries += 1
                self.recovery_ticks.append(tick-record['failure_tick'])

    def cancelled(self, task):
        for record in self.records:
            if record['task_id'] == task.id and record['completion_tick'] is None:
                record['status'] = 'cancelled'

    def snapshot(self, robot, tick):
        task = self._task(robot)
        return {'robot_id': robot.id, 'x': robot.x, 'y': robot.y, 'tick': tick,
                'status': robot.status, 'current_task': task.id if task else None,
                'cargo_id': task.cargo_id if task else None,
                'cargo_owner': task.cargo_owner if task else None,
                'cargo_state': task.cargo_state if task else None,
                'has_cargo': bool(robot.carrying or getattr(robot, 'handling', None)),
                'destination': task.dropoff_slot_code if task else None,
                'task_status': task.status if task else None,
                'communication_mode': robot.communication_mode,
                'charger': list(robot.target_charger) if robot.target_charger is not None else None,
                'charger_cost': robot._charge_cost(robot.target_charger) if robot.target_charger is not None else None}

    def publish_snapshot(self, robot, robots, network, tick):
        snapshot = self.snapshot(robot, tick)
        network.broadcast(robot.id, 'state_sync', snapshot)
        robot._broadcast_position(network, tick)
        robot._broadcast_intent(network, tick)

    def lose_communication(self, robot, robots, network, tick):
        if network.is_partitioned.get(robot.id, False):
            raise ValueError('Communication is already offline')
        network.partition_robot(robot.id)
        robot.communication_mode = 'local'
        # Radio link transitions invalidate traffic predictions immediately;
        # position sensing remains local and independent of this transport.
        robot.clear_peer_knowledge()
        for peer in robots:
            peer.forget_peer(robot.id)
        self.communication_losses += 1

    def restore_communication(self, robot, robots, network, tick):
        if not network.is_partitioned.get(robot.id, False):
            raise ValueError('Communication is already online')
        # Reconnection cannot resurrect a source carton or overwrite custody.
        task = self._task(robot)
        if robot.carrying and (task is None or task.cargo_owner != f'robot:{robot.id}' or not task.picked_up):
            raise ValueError('Cannot reconcile conflicting cargo ownership')
        if task and task.picked_up:
            source = self.manager.warehouse.get_slot(task.pickup_slot_id)
            if source and source['state'] == 'stored' and source.get('cargo_id') == task.cargo_id:
                raise ValueError('Cannot reconcile duplicated source inventory')
        network.restore_robot(robot.id)
        robot.communication_mode = 'online'
        robot.clear_peer_knowledge()
        # Exchange current snapshots in BOTH directions before the next move.
        self.publish_snapshot(robot, robots, network, tick)
        for peer in robots:
            if peer.id != robot.id and not network.is_partitioned.get(peer.id, False):
                network.send_direct(peer.id, robot.id, 'state_sync', self.snapshot(peer, tick))
                peer._process_messages(network.receive_all(peer.id), tick=tick)
        robot._process_messages(network.receive_all(robot.id), tick=tick)
        self.reconciliations += 1

    def to_dict(self):
        mission = self.manager.consolidation
        return {'robot_failures': self.robot_failures, 'successful_recoveries': self.successful_recoveries,
                'communication_loss_events': self.communication_losses, 'reconciliations': self.reconciliations,
                'tasks_reassigned': self.tasks_reassigned, 'cargo_recovered': self.cargo_recovered,
                'recovery_times_ticks': list(self.recovery_ticks),
                'avg_recovery_ticks': round(sum(self.recovery_ticks)/len(self.recovery_ticks), 1) if self.recovery_ticks else None,
                'collisions': mission.collisions, 'deadlocks': mission.deadlocks,
                'mission_completed': mission.status == 'completed', 'events': [dict(r) for r in self.records]}
