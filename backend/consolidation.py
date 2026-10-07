"""Phase 6 inventory-driven mission, using TaskManager's existing auction/queue.

No motion controller, robot assignment, coordinates or warehouse branches live here.
Slots remain authoritative; reservations are claims, never duplicate inventory.
"""
from pathfinding import a_star


class ConsolidationMission:
    def __init__(self, manager):
        self.manager = manager
        self.warehouse = manager.warehouse
        self.enabled = False
        self.status = "not_prepared"
        self.message = "Prepare consolidation inventory before filling the empty rack"
        self.target = None
        self.capacity = 0
        self.started = False
        self.robots_used = set()
        self.collisions = 0
        self.deadlocks = 0
        self.excluded = set()

    def target_slots(self):
        return [self.warehouse.get_slot(sid) for sid in self.target['slots']] if self.target else []

    def detect_target(self):
        config = self.warehouse.consolidation
        if not config:
            raise ValueError("No consolidation target rack configured in warehouse data")
        target = next((r for r in self.warehouse.rack_islands if r['code'] == config['target_rack']), None)
        if not target or not target['slots']:
            raise ValueError("Configured consolidation target rack does not exist or has no accessible slots")
        if not 1 <= config['capacity'] <= len(target['slots']):
            raise ValueError("Configured consolidation capacity exceeds target slots")
        self.target, self.capacity = target, config['capacity']
        return target

    def prepare(self):
        """Explicit fixture reset, not task generation. Never called by start()."""
        if self.manager.active_tasks:
            raise ValueError("Finish active transfers before preparing inventory")
        self.detect_target()
        slots = {s['code']: s for s in self.warehouse.rack_slots}
        inventory = self.warehouse.consolidation['initial_inventory']
        seen_slots, seen_cargo = set(), set()
        # Validate the complete fixture before changing any state.
        for row in inventory:
            slot = slots.get(row['slot'])
            if not slot or slot['island'] == self.target['code']:
                raise ValueError("Initial inventory must use valid non-target rack slots")
            if row['slot'] in seen_slots or row['cargo_id'] in seen_cargo:
                raise ValueError("Duplicate initial slot or carton ID")
            seen_slots.add(row['slot']); seen_cargo.add(row['cargo_id'])
        self.warehouse.reset_tables()
        self.warehouse.reset_racks()
        for row in inventory:
            slots[row['slot']].update(state='stored', cargo_id=row['cargo_id'], task_id=None)
        for name in ('pending_tasks', 'active_tasks', 'completed_tasks', 'cancelled_tasks', 'failed_tasks', 'all_tasks'):
            getattr(self.manager, name).clear()
        self.manager.stored_count = 0
        from resilience import FleetResilience
        self.manager.resilience = FleetResilience(self.manager)
        self.enabled = True
        self.status = 'ready'
        self.message = 'Inventory prepared; target rack is completely empty'
        self.started = False
        self.excluded.clear(); self.robots_used.clear()
        self.collisions = self.deadlocks = 0

    def movable_cartons(self):
        if not self.target:
            return []
        return [s for s in self.warehouse.rack_slots
                if s['island'] != self.target['code'] and s['state'] == 'stored'
                and s.get('cargo_id') is not None and s['task_id'] is None
                and s['cargo_id'] not in self.excluded]

    def start(self, robots, tick=0):
        if self.started:
            raise ValueError("Consolidation already started; prepare a new round to restart")
        try:
            self.detect_target()
            slots = self.target_slots()
            if all(s['state'] == 'stored' for s in slots) or sum(s['state'] == 'stored' for s in slots) >= self.capacity:
                raise ValueError("Target rack already full at configured consolidation capacity")
            if any(s['state'] != 'empty' for s in slots):
                raise ValueError("No empty target rack: designated target must be completely empty")
            if self.manager.remaining():
                raise ValueError("Finish other tasks or prepare consolidation before starting")
        except ValueError as error:
            self.enabled = True
            self.status, self.message = 'failed', str(error)
            raise
        self.enabled = self.started = True
        self.status = 'running'
        self.refresh(robots, tick)

    def route_pair(self, source, destination, robots, cache=None):
        """Shortest feasible aisle-to-aisle A* route, deterministic ties.

        Robot-to-source reachability is a feasibility check only: the existing
        decentralized bid calculation still decides ownership.
        """
        cache = {} if cache is None else cache
        def distance(a, b):
            key = (tuple(a), tuple(b))
            if key not in cache:
                path = a_star(self.warehouse, key[0], key[1]) if self.warehouse.is_walkable(*a) and self.warehouse.is_walkable(*b) else None
                cache[key] = len(path) - 1 if path else None
            return cache[key]
        choices = []
        for pickup in self.warehouse.rack_access_cells(source['cell']):
            if not any(distance((r.x, r.y), pickup) is not None for r in robots):
                continue
            for dropoff in self.warehouse.rack_access_cells(destination['cell']):
                cost = distance(pickup, dropoff)
                if cost is not None:
                    choices.append((cost, pickup, dropoff))
        return min(choices) if choices else None

    def fail_uncollected(self, task, robots, reason):
        if task.picked_up:
            return  # Keep physical ownership; never strand a carried carton.
        if task in self.manager.active_tasks:
            self.manager._detach_robot(task, robots)
        if task in self.manager.pending_tasks:
            self.manager.pending_tasks.remove(task)
        self.manager._release_source_claim(task)
        self.manager._release_destination(task)
        task.status, task.failure_reason = 'failed', reason
        self.manager.failed_tasks.append(task)
        self.excluded.add(task.cargo_id)

    def refresh(self, robots, tick=0):
        if not self.started or self.status in ('completed', 'partial', 'failed', 'timed_out'):
            return
        manager = self.manager
        self.robots_used.update(t.assigned_to for t in manager.active_tasks + manager.completed_tasks if t.assigned_to is not None)
        for task in manager.cancelled_tasks + manager.failed_tasks:
            self.excluded.add(task.cargo_id)
        # Do not let physical lifting/placement proceed with an invalid claim.
        # Once lifting begins, ownership cannot be cancelled or reconstructed.
        for task in list(manager.active_tasks):
            source, dest = self.warehouse.get_slot(task.pickup_slot_id), self.warehouse.get_slot(task.dropoff_slot_id)
            source_valid = task.picked_up or (source['state'] == 'stored' and source['cargo_id'] == task.cargo_id and source['task_id'] == task.id)
            dest_valid = dest['state'] == 'reserved' and dest['task_id'] == task.id
            if not source_valid or not dest_valid:
                if task.picked_up:
                    self.status, self.message = 'blocked', 'Destination slot unavailable during transfer; mission paused with carton ownership retained. Restore the reservation before resuming.'
                    return
                self.fail_uncollected(task, robots, 'Source carton or destination reservation unavailable')
        # Live inventory can change between task generation and auction.
        for task in list(manager.pending_tasks):
            source, dest = self.warehouse.get_slot(task.pickup_slot_id), self.warehouse.get_slot(task.dropoff_slot_id)
            if task.reservations_released:
                continue  # Phase 7 holds this original task pending valid claims.
            if task.recovery_required:
                if dest['state'] != 'reserved' or dest['task_id'] != task.id:
                    self.status, self.message = 'blocked', 'Recovery destination reservation unavailable; cargo retained on failed robot'
                    return
                continue  # Source is already empty; cargo is on its failed owner.
            if source['state'] != 'stored' or source['cargo_id'] != task.cargo_id or source['task_id'] != task.id:
                self.fail_uncollected(task, robots, 'Source carton unavailable')
            elif dest['state'] != 'reserved' or dest['task_id'] != task.id:
                self.fail_uncollected(task, robots, 'Destination slot unavailable')
            elif not self.route_pair(source, dest, robots):
                self.fail_uncollected(task, robots, 'Source carton or destination slot unreachable')
        filled = sum(s['state'] == 'stored' for s in self.target_slots())
        if filled >= self.capacity:
            self.status, self.message = 'completed', 'Target rack filled to configured consolidation capacity'
            return
        need = self.capacity - filled - manager.remaining()
        sources = self.movable_cartons()
        destinations = [s for s in self.target_slots() if s['state'] == 'empty']
        candidates, cache = [], {}
        if need > 0:
            for source in sources:
                for dest in destinations:
                    pair = self.route_pair(source, dest, robots, cache)
                    if pair:
                        candidates.append((pair[0], source['code'], dest['code'], pair[1], pair[2], source, dest))
        used_sources, used_destinations = set(), set()
        from task_manager import Task
        for cost, _, _, pickup, dropoff, source, dest in sorted(candidates, key=lambda c: c[:3]):
            if need <= 0:
                break
            if source['id'] in used_sources or dest['id'] in used_destinations:
                continue
            task = Task(pickup, dropoff, stage='consolidation', pickup_kind='rack', dropoff_kind='rack',
                        pickup_slot=source, dropoff_slot=dest, destination=tuple(dest['cell']),
                        source_ref=source['code'], destination_ref=dest['code'],
                        source_label=f"Rack {source['island']} / Slot {source['code']}",
                        destination_label=f"Rack {dest['island']} / Slot {dest['code']}",
                        created_tick=tick, dynamic=True)
            task.cargo_id = source['cargo_id']
            task.estimated_cost = cost
            if not self.warehouse.reserve_slot(dest['id'], task.id):
                continue
            source['task_id'] = task.id
            manager.pending_tasks.append(task); manager.all_tasks.append(task)
            used_sources.add(source['id']); used_destinations.add(dest['id'])
            need -= 1
        if not manager.remaining():
            reason = ('Insufficient movable cartons (including cancelled/failed work)' if not sources
                      else 'Source cartons or destination slots unreachable/unavailable')
            self.status = 'partial' if filled else 'failed'
            self.message = f'{reason}; filled {filled}/{self.capacity} slots'
        elif not any(getattr(r, 'available', True) and not getattr(r, 'parked', False) for r in robots):
            self.status, self.message = 'waiting_for_robots', 'No robot available; tasks remain queued until a robot returns'
        else:
            self.status, self.message = 'running', 'Fleet auction → pickup → transport → placement'
        self.robots_used.update(t.assigned_to for t in manager.active_tasks + manager.completed_tasks if t.assigned_to is not None)
        recovering = [t for t in manager.pending_tasks + manager.active_tasks
                      if t.recovery_required or t.reservations_released]
        if recovering:
            self.status = 'recovering' if any(t.recovery_robot_id is not None for t in recovering) else 'recovery_pending'
            self.message = 'Cargo recovery required; original tasks/destinations retained. Awaiting a connected, reachable recovery robot.'

    def timeout(self):
        if self.started and self.status != 'completed':
            self.status = 'timed_out'
            self.message = 'Mission time limit reached; unresolved tasks and carried cartons retained. Resume to continue or inspect barriers/robot availability.'

    def to_dict(self):
        manager = self.manager
        filled = sum(s['state'] == 'stored' for s in self.target_slots())
        return {'enabled': self.enabled, 'started': self.started, 'status': self.status, 'message': self.message,
                'target_rack': self.target['code'] if self.target else (self.warehouse.consolidation or {}).get('target_rack'),
                'capacity': self.capacity or (self.warehouse.consolidation or {}).get('capacity', 0),
                'available_source_cartons': len(self.movable_cartons()), 'filled_slots': filled,
                'tasks_generated': len(manager.all_tasks) if self.enabled else 0,
                'pending': len(manager.pending_tasks) if self.enabled else 0,
                'active': len(manager.active_tasks) if self.enabled else 0,
                'completed': len(manager.completed_tasks) if self.enabled else 0,
                'progress': round(100 * filled / self.capacity) if self.capacity else 0,
                'robots_used': sorted(self.robots_used), 'collision_count': self.collisions, 'deadlock_count': self.deadlocks}
