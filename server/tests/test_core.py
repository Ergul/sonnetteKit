import unittest
from sonnette.core import Hub, ProtocolError
from sonnette.security import authenticate, ice_config
import base64
import hashlib
import hmac


class Calls(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.hub = Hub({'a': ['b'], 'b': ['a'], 'c': []}, clock=lambda: self.now)
        for user in ['a', 'b', 'c']:
            self.hub.connect(user)

    def invite(self):
        result, _ = self.hub.handle('a', {'type': 'call.invite', 'to': 'b'})
        return result['call_id']

    def test_full_lifecycle(self):
        cid = self.invite()
        self.hub.handle('b', {'type': 'call.accept', 'call_id': cid})
        for user, kind in [('a', 'rtc.offer'), ('b', 'rtc.answer')]:
            _, events = self.hub.handle(user, {'type': kind, 'call_id': cid, 'sdp': 'v=0'})
            self.assertNotEqual(events[0][0], user)
        self.hub.handle('a', {'type': 'media.ready', 'call_id': cid})
        self.hub.handle('b', {'type': 'media.ready', 'call_id': cid})
        self.assertEqual(self.hub.calls[cid].state, 'active')
        _, events = self.hub.handle('a', {'type': 'call.end', 'call_id': cid})
        self.assertEqual(len(events), 2)
        self.assertFalse(self.hub.busy)

    def test_unauthorized_cannot_join_or_signal(self):
        cid = self.invite()
        for kind in ['call.accept', 'call.end', 'rtc.offer', 'rtc.ice']:
            with self.assertRaisesRegex(ProtocolError, 'unknown_call'):
                self.hub.handle('c', {'type': kind, 'call_id': cid})
        with self.assertRaisesRegex(ProtocolError, 'forbidden'):
            self.hub.handle('c', {'type': 'call.invite', 'to': 'a'})

    def test_crossed_invites_do_not_create_two_calls(self):
        self.invite()
        with self.assertRaisesRegex(ProtocolError, 'busy'):
            self.hub.handle('b', {'type': 'call.invite', 'to': 'a'})
        self.assertEqual(len(self.hub.calls), 1)

    def test_timeout_and_late_accept(self):
        cid = self.invite()
        self.now += 31
        self.assertEqual(len(self.hub.expire()), 2)
        with self.assertRaisesRegex(ProtocolError, 'unknown_call'):
            self.hub.handle('b', {'type': 'call.accept', 'call_id': cid})
        self.assertFalse(self.hub.busy)

    def test_only_callee_can_accept(self):
        cid = self.invite()
        with self.assertRaisesRegex(ProtocolError, 'invalid_state'):
            self.hub.handle('a', {'type': 'call.accept', 'call_id': cid})

    def test_disconnect_releases_both_devices(self):
        self.invite()
        self.assertEqual(len(self.hub.disconnect('a')), 2)
        self.assertFalse(self.hub.busy)
        with self.assertRaisesRegex(ProtocolError, 'offline'):
            self.hub.handle('b', {'type': 'call.invite', 'to': 'a'})

    def test_duplicate_connection_rejected(self):
        with self.assertRaisesRegex(ProtocolError, 'already_connected'):
            self.hub.connect('a')

    def test_negotiation_sequence(self):
        cid = self.invite()
        self.hub.handle('b', {'type': 'call.accept', 'call_id': cid})
        with self.assertRaisesRegex(ProtocolError, 'invalid_state'):
            self.hub.handle('b', {'type': 'rtc.answer', 'call_id': cid, 'sdp': 'v=0'})
        with self.assertRaisesRegex(ProtocolError, 'invalid_sdp'):
            self.hub.handle('a', {'type': 'rtc.offer', 'call_id': cid, 'sdp': 'x' * 60001})
        self.now += 46
        self.assertEqual(len(self.hub.expire()), 2)

    def test_bad_candidate_is_rejected(self):
        cid = self.invite()
        self.hub.handle('b', {'type': 'call.accept', 'call_id': cid})
        with self.assertRaisesRegex(ProtocolError, 'invalid_candidate'):
            self.hub.handle('a', {'type': 'rtc.ice', 'call_id': cid,
                                 'candidate': {'candidate': 'x', 'sdpMLineIndex': 'oops'}})

    def test_decline(self):
        cid = self.invite()
        _, events = self.hub.handle('b', {'type': 'call.reject', 'call_id': cid})
        self.assertEqual(events[0][1]['reason'], 'rejected')
        self.assertFalse(self.hub.calls)


class Security(unittest.TestCase):
    def test_auth(self):
        data = {'a': {'token_sha256': hashlib.sha256(b'random-key').hexdigest()}}
        self.assertTrue(authenticate(data, 'a', 'random-key'))
        self.assertFalse(authenticate(data, 'a', 'wrong'))
        self.assertFalse(authenticate(data, 'missing', 'random-key'))
        self.assertFalse(authenticate(data, [], 'random-key'))

    def test_turn_credentials(self):
        secret = 'x' * 32
        result = ice_config('a', ['turns:example.com:443?transport=tcp'], secret, 'relay', now=1000)
        server = result['iceServers'][0]
        self.assertEqual(server['username'], '8200:a')
        expected = base64.b64encode(hmac.new(secret.encode(), b'8200:a', hashlib.sha1).digest()).decode()
        self.assertEqual(server['credential'], expected)
        with self.assertRaises(ValueError):
            ice_config('a', [], '', 'relay')


if __name__ == '__main__':
    unittest.main()
