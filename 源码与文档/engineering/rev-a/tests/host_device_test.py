import ctypes,sys,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'host'))
from device import SimulatedDevice,command_packet,decode
from transactions import Rejected

class DeviceProtocol(unittest.TestCase):
 def setUp(self):self.d=SimulatedDevice();self.d.pulse()
 def tearDown(self):self.d.close()
 def wait(self,predicate,seconds=.3):
  deadline=time.monotonic()+seconds
  while time.monotonic()<deadline:
   with self.d.lock:
    value=self.d.snapshot()
   if predicate(value):return value
   time.sleep(.003)
  self.fail('firmware state predicate timed out: '+str(value))
 def test_real_c_wire_ownership_and_raw_mic_cut(self):
  self.assertEqual(self.d.command(2)['owner'],1)
  self.d.buttons(4);self.wait(lambda s:s['buttons']==4)
  self.assertTrue(self.d.command(5,1)['flags']&2)
  self.wait(lambda s:s['flags']&4)
  self.d.buttons(0);self.wait(lambda s:not(s['flags']&2),.05)
  self.assertEqual(self.d.command(4)['owner'],0)
 def test_held_left_cannot_be_claimed_and_has_no_replay(self):
  self.d.buttons(1);self.wait(lambda s:s['hid_buttons']==1)
  with self.assertRaises(Rejected):self.d.command(2)
  self.d.disconnect();self.assertEqual(self.d.snapshot()['hid_buttons'],0)
  self.d.pulse();self.assertEqual(self.d.snapshot()['hid_buttons'],0)
 def test_window_heartbeat_loss_cuts_recording_and_rotates_session(self):
  self.d.command(2);self.d.buttons(4);self.wait(lambda s:s['buttons']==4);self.d.command(5,1)
  session=self.d.snapshot()['session']
  state=self.wait(lambda s:s['session']!=session,.8)
  self.assertFalse(state['flags']&2);self.assertEqual(state['owner'],0)
 def test_python_wire_crc_rejected_by_same_c_decoder(self):
  packet=bytearray(command_packet(self.d.snapshot()['session'],999,2));packet[16]=1
  array=(ctypes.c_uint8*32).from_buffer_copy(packet)
  with self.d.lock:self.assertEqual(self.d.lib.ak_sim_command(array,self.d.now()),-1)
 def test_decoder_corrupt_event_rejected(self):
  data=(ctypes.c_uint8*32)();self.d.lib.ak_sim_state(data);packet=bytearray(data);packet[3]^=1
  with self.assertRaises(Rejected):decode(bytes(packet))
 def test_fresh_subscription_never_replays_previous_button_edges(self):
  self.d.buttons(8);self.wait(lambda s:s['buttons']==8);self.d.buttons(0);self.wait(lambda s:s['buttons']==0)
  self.assertTrue(any(e['type']==1 for e in self.d.history))
  self.assertEqual(self.d.pulse()['events'],[])
  cursor=self.d.pulse()['cursor'];self.assertEqual(self.d.pulse(cursor)['events'],[])
if __name__=='__main__':unittest.main(verbosity=2)
