"""Regression cases from blocked C3 rack access shown in the screenshots."""
import unittest
from collision import detect_collisions, detect_deadlock, resolve_deadlock
from events import EventLogger
from p2p import P2PNetwork
from presentation_robot import PresentationRobot, HANDLING_TICKS, _face
from robot import Robot
from smoke_demo import audit_cartons
from task_manager import TaskManager
from warehouse import Warehouse


class RackAccessTests(unittest.TestCase):
    def setUp(self):
        self.floor = Warehouse()
        self.tasks = TaskManager(self.floor)
        self.tasks.generate_manifest(storage=True)
        self.net = P2PNetwork()
        self.log = EventLogger()
        self.unit = PresentationRobot(1, (16, 11), self.floor)
        self.net.register_robot(1)

    def carrying(self, task_id=10, start=None):
        if start:
            self.unit = PresentationRobot(1, start, self.floor)
        task = self.tasks.find_task(task_id)
        self.unit.assign_task(task.as_payload())
        self.unit.carrying = True
        self.unit.status = 'moving_to_dropoff'
        self.unit._replan_path()
        task.assigned_to = 1
        task.status = 'assigned'
        self.tasks.pending_tasks.remove(task)
        self.tasks.active_tasks.append(task)
        self.tasks.note_pickup(task_id)
        return task

    def finish(self, bound=250):
        for tick in range(1, bound+1):
            before = (self.unit.x, self.unit.y)
            action = self.unit.tick(tick, self.net, self.log)
            after = (self.unit.x, self.unit.y)
            self.assertLessEqual(abs(after[0]-before[0])+abs(after[1]-before[1]), 1)
            self.assertTrue(self.floor.is_walkable(*after))
            self.assertIsNone(self.unit.navigation_message)
            if self.unit.handling:
                self.assertEqual(self.unit.handling['target'], [14,16])
                self.assertEqual(self.unit.handling['face'], _face(after, (14,16)))
            if action == 'delivered':
                return
        self.fail('A reachable alternate face never completed')

    def test_access_cells_are_same_slot_orthogonal_faces(self):
        self.assertEqual(self.floor.rack_access_cells((14,16)), [(15,16),(14,17)])
        self.assertEqual(self.floor.rack_access_cells((14,15)), [(15,15),(14,14)])
        self.assertEqual(self.floor.rack_access_cells((16,11)), [])

    def test_blocked_default_dropoff_uses_same_slot_south_face(self):
        task = self.carrying()
        self.floor.block_aisle(15,16)
        self.unit.tick(1,self.net)
        self.assertEqual(self.unit.current_task['dropoff'], (14,17))
        self.assertEqual(self.unit.current_task['slot_code'], 'C3-04')
        self.assertEqual(self.floor.get_slot(task.slot_id)['task_id'], 10)
        self.finish()
        self.assertEqual((self.unit.x,self.unit.y),(14,17))
        self.assertEqual(self.tasks.complete_leg(10)[0], 'stored')
        self.assertEqual(self.floor.get_slot(task.slot_id)['state'], 'stored')
        self.assertIsNone(self.unit.current_task)
        self.assertIsNone(self.unit.handling)

    def test_access_face_free_but_disconnected_uses_another_face(self):
        self.carrying()
        self.floor.blocked_cells.update({(16,16),(15,15),(15,17)})
        self.assertTrue(self.floor.is_walkable(15,16))
        self.unit._replan_path()
        self.assertEqual(self.unit.current_task['dropoff'], (14,17))
        self.finish()

    def test_both_faces_blocked_warn_then_opening_nondefault_face_recovers(self):
        self.carrying()
        self.floor.blocked_cells.update({(15,16),(14,17)})
        self.unit.tick(1,self.net)
        self.assertEqual(self.unit.navigation_message,'Please remove the barrier')
        self.assertTrue(self.unit.carrying)
        self.floor.unblock_aisle(14,17)
        self.unit.tick(2,self.net)
        self.assertEqual(self.unit.current_task['dropoff'],(14,17))
        self.finish()

    def test_solid_wall_cannot_be_bypassed_even_with_free_destination_face(self):
        self.carrying()
        self.floor.blocked_cells.update({(15,y) for y in range(1,19)})
        self.unit.tick(1,self.net)
        self.assertEqual(self.unit.navigation_message,'Please remove the barrier')
        self.assertTrue(self.floor.get_neighbors(self.unit.x,self.unit.y))
        self.assertTrue(self.floor.is_walkable(14,17))
        self.floor.unblock_aisle(15,18)
        self.unit.tick(2,self.net)
        self.finish()

    def test_second_barrier_change_reselects_face_mid_route(self):
        self.carrying()
        self.floor.block_aisle(15,16)
        self.unit.tick(1,self.net)
        self.assertEqual(self.unit.current_task['dropoff'],(14,17))
        self.floor.unblock_aisle(15,16)
        self.floor.block_aisle(14,17)
        self.unit.tick(2,self.net)
        self.assertEqual(self.unit.current_task['dropoff'],(15,16))
        self.assertIsNone(self.unit.navigation_message)
        self.assertTrue(self.unit.carrying)
        self.assertEqual(self.unit.current_task['slot_code'],'C3-04')

    def test_offline_unit_can_switch_faces_without_gossip(self):
        self.carrying()
        self.net.partition_robot(1)
        self.floor.block_aisle(15,16)
        self.finish()

    def test_alternate_face_already_occupied_uses_original_if_available(self):
        self.floor.set_occupancy(2,(14,17))
        self.carrying(start=(16,17))
        self.assertEqual(self.unit.current_task['dropoff'],(15,16))

    def test_arrival_already_at_nondefault_face_starts_dwell_without_fake_move(self):
        self.carrying(start=(14,17))
        self.unit.current_task['dropoff']=(15,16)
        distance=self.unit.total_distance
        self.assertEqual(self.unit.tick(1,self.net),'handling')
        self.assertEqual(self.unit.total_distance,distance)
        self.assertEqual(self.unit.handling['station'],[14,17])
        self.assertEqual(self.unit.handling['face'],270)
        self.assertEqual(self.unit.tick(1+HANDLING_TICKS,self.net),'delivered')

    def test_task_telemetry_tracks_new_access_without_changing_shelf_destination(self):
        task=self.carrying()
        self.floor.block_aisle(15,16)
        self.unit._replan_path()
        self.tasks.pending_tasks=[]
        self.tasks.allocate_tasks([self.unit],self.net)
        row=self.tasks.to_dict()['active'][0]
        self.assertEqual(row['dropoff'],(14,17))
        self.assertEqual(row['destination'],[14,16])
        self.assertEqual(task.slot_code,'C3-04')

    def test_rack_pickup_can_use_alternate_face_too(self):
        unit=Robot(1,(16,11),self.floor)
        self.floor.block_aisle(15,16)
        unit.assign_task({'id':77,'pickup':(15,16),'pickup_kind':'rack',
                          'slot_cell':[14,16],'dropoff':(16,8)})
        self.assertEqual(unit.current_task['pickup'],(14,17))
        self.assertIsNone(unit.navigation_message)
        for tick in range(1,100):
            if unit.tick(tick,self.net)=='picked_up':
                break
        else:
            self.fail('Rack pickup from an alternate face stalled')
        self.assertTrue(unit.carrying)

    def test_screenshot_inspired_26_barriers_finishes_remaining_two_cartons(self):
        # Screenshots do not expose every cell. This deliberately explicit fixture
        # blocks the two shown destinations and leaves a valid southern gap.
        fleet=[PresentationRobot(1,(16,11),self.floor,95),
               PresentationRobot(2,(18,18),self.floor,77),
               PresentationRobot(3,(16,8),self.floor,96)]
        for unit in fleet:
            self.net.register_robot(unit.id)
        self.tasks.pending_tasks=[]
        for task in self.tasks.all_tasks:
            self.tasks.note_pickup(task.id)
            if task.id in (9,10):
                unit=fleet[2] if task.id==9 else fleet[0]
                task.assigned_to=unit.id;task.status='assigned'
                self.tasks.active_tasks.append(task)
                unit.assign_task(task.as_payload());unit.carrying=True
                unit.status='moving_to_dropoff';unit._replan_path()
            else:
                task.status='completed';self.tasks.completed_tasks.append(task)
                self.floor.mark_slot_stored(task.slot_id)
                self.tasks.stored_count+=1
        self.floor.blocked_cells.update({(15,y) for y in range(1,17)} |
                                       {(4,y) for y in range(1,11)})
        self.assertEqual(len(self.floor.blocked_cells),26)
        self.net.partition_robot(3)
        for tick in range(1,400):
            self.tasks.allocate_tasks(fleet,self.net,self.log,tick)
            for unit in fleet:
                action=unit.tick(tick,self.net,self.log)
                self.assertNotEqual(unit.navigation_message,'Please remove the barrier')
                if action=='delivered':
                    self.tasks.complete_leg(unit.last_delivered_task_id)
            self.assertFalse(detect_collisions(fleet))
            self.assertEqual(audit_cartons(self.floor,fleet,self.tasks),[])
            cycles=detect_deadlock(fleet)
            if cycles:
                resolve_deadlock(fleet,cycles,self.floor,self.net,tick)
            if len(self.tasks.completed_tasks)==12:
                break
        self.assertEqual(len(self.tasks.completed_tasks),12)
        self.assertEqual((fleet[0].x,fleet[0].y),(14,17))
        self.assertEqual((fleet[2].x,fleet[2].y),(14,14))
        self.assertEqual(self.tasks.stored_count,12)


if __name__=='__main__':
    unittest.main()
