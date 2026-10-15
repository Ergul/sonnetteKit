import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

enum CallPhase { idle, outgoing, incoming, connecting, active }

class SonnetteCredentials {
  const SonnetteCredentials({
    required this.server,
    required this.connectionId,
    required this.accessToken,
  });

  final Uri server;
  final String connectionId;
  final String accessToken;
}

typedef SonnetteCredentialsProvider = Future<SonnetteCredentials> Function();
typedef SonnetteMediaConstraintsProvider = Future<Map<String, dynamic>>
    Function();

/// One authenticated device, one signaling socket and at most one call.
/// Call shutdown() before disposing the owning screen. Credentials stay in memory.
class SonnetteClient extends ChangeNotifier {
  SonnetteClient({
    this.beforeMediaStart,
    this.afterMediaStop,
    this.mediaConstraintsProvider,
  });

  final Future<void> Function()? beforeMediaStart;
  final Future<void> Function()? afterMediaStop;
  final SonnetteMediaConstraintsProvider? mediaConstraintsProvider;
  final localRenderer = RTCVideoRenderer();
  final remoteRenderer = RTCVideoRenderer();
  bool online = false;
  bool microphoneEnabled = true;
  bool cameraEnabled = true;
  CallPhase phase = CallPhase.idle;
  String? callId;
  String? peer;
  String? peerLabel;
  String? peerLocation;
  String? lastEndedCallId;
  String? lastEndReason;
  String? error;
  String? deviceId;
  List<String> peers = [];
  String mediaStatus = 'Idle';
  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _subscription;
  RTCPeerConnection? _pc;
  MediaStream? _local;
  MediaStream? _remote;
  Map<String, dynamic> _rtc = {};
  final _pendingIce = <RTCIceCandidate>[];
  final _requests = <String, Completer<Map<String, dynamic>>>{};
  Completer<void>? _ready;
  Timer? _heartbeat;
  Timer? _reconnect;
  Timer? _mediaGrace;
  Uri? _uri;
  String? _token;
  SonnetteCredentialsProvider? _credentialsProvider;
  bool _stopping = false;
  bool _initialized = false;
  bool _disposed = false;
  bool _remoteSet = false;
  bool _readySent = false;
  bool _negotiated = false;
  bool _opening = false;
  bool _mediaPrepared = false;
  int _serial = 0;
  int _generation = 0;
  int _retry = 0;
  Future<void> _events = Future.value();

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  Future<void> initialize() async {
    if (_initialized) return;
    await localRenderer.initialize();
    await remoteRenderer.initialize();
    _initialized = true;
  }

  Future<void> connect({
    required Uri server,
    required String id,
    required String token,
  }) async {
    if (_channel != null || _opening) throw StateError('Disconnect first');
    _validateServer(server);
    await initialize();
    _credentialsProvider = null;
    _uri = server;
    deviceId = id;
    _token = token;
    _stopping = false;
    await _open();
  }

  Future<void> connectWithCredentials(
    SonnetteCredentialsProvider provider,
  ) async {
    if (_channel != null || _opening) throw StateError('Disconnect first');
    await initialize();
    _credentialsProvider = provider;
    _stopping = false;
    await _open();
  }

  void _validateServer(Uri server) {
    if (!['wss', 'ws'].contains(server.scheme) || server.path != '/ws') {
      throw ArgumentError(
        'Use wss://your-server/ws (ws only for localhost development)',
      );
    }
    if (server.scheme == 'ws' &&
        !['localhost', '127.0.0.1', '10.0.2.2'].contains(server.host)) {
      throw ArgumentError('A remote server requires wss://');
    }
  }

  Future<void> _open() async {
    if (_stopping || _opening) return;
    _opening = true;
    if (_credentialsProvider != null) {
      try {
        final credentials = await _credentialsProvider!();
        _validateServer(credentials.server);
        _uri = credentials.server;
        deviceId = credentials.connectionId;
        _token = credentials.accessToken;
      } catch (_) {
        _opening = false;
        rethrow;
      }
    }
    if (_uri == null || deviceId == null || _token == null) {
      _opening = false;
      throw StateError('Missing signaling credentials');
    }
    final generation = ++_generation;
    final ready = Completer<void>();
    _ready = ready;
    // Attach an error listener before the socket can fail.
    final readyFuture = ready.future.timeout(const Duration(seconds: 15));
    WebSocketChannel? channel;
    try {
      channel = WebSocketChannel.connect(_uri!);
      _channel = channel;
      _subscription = channel.stream.listen(
        (raw) {
          _events = _events.then((_) async {
            if (generation != _generation || _stopping) return;
            try {
              await _handle(
                Map<String, dynamic>.from(jsonDecode(raw as String) as Map),
              );
            } catch (e) {
              error = 'Media/signaling error: $e';
              if (callId != null) {
                _sendUntracked('call.end', {'call_id': callId});
                await _clearCall();
              }
              _notify();
            }
          });
        },
        onError: (Object e) {
          if (generation == _generation) {
            error = 'Connection error';
            unawaited(channel!.sink.close());
          }
        },
        onDone: () {
          _events = _events.then((_) async {
            if (generation == _generation) await _lost(channel!.closeCode);
          });
        },
      );
      // auth is the first frame; tokens never appear in URLs or access logs.
      channel.sink.add(
        jsonEncode({
          'v': 1,
          'type': 'auth',
          'device_id': deviceId,
          'token': _token,
        }),
      );
      await readyFuture;
    } catch (_) {
      await channel?.sink.close();
      rethrow;
    } finally {
      _opening = false;
    }
  }

  Future<void> _lost(int? closeCode) async {
    online = false;
    _channel = null;
    _heartbeat?.cancel();
    if (!(_ready?.isCompleted ?? true))
      _ready!.completeError(StateError('Authentication or connection failed'));
    for (final request in _requests.values) {
      if (!request.isCompleted)
        request.completeError(StateError('Disconnected'));
    }
    _requests.clear();
    await _clearCall();
    // Policy/auth failures need operator action, not an endless retry loop.
    if (closeCode == 1008) {
      _stopping = true;
      error ??= 'Access denied or device already connected';
    }
    if (!_stopping) {
      error = 'Disconnected; reconnecting (the previous call has ended)';
      _scheduleReconnect();
    }
    _notify();
  }

  void _scheduleReconnect() {
    if (_stopping || (_reconnect?.isActive ?? false)) return;
    final seconds = [1, 2, 4, 8, 15][_retry < 4 ? _retry : 4];
    _retry++;
    _reconnect = Timer(Duration(seconds: seconds), () async {
      try {
        await _open();
      } catch (_) {
        if (!_stopping) _scheduleReconnect();
      }
    });
  }

  Future<Map<String, dynamic>> _request(
    String type, [
    Map<String, dynamic> body = const {},
  ]) async {
    if (!online || _channel == null) throw StateError('Not connected');
    final id = '${DateTime.now().microsecondsSinceEpoch}-${_serial++}';
    final completer = Completer<Map<String, dynamic>>();
    _requests[id] = completer;
    _channel!.sink.add(jsonEncode({'v': 1, 'id': id, 'type': type, ...body}));
    try {
      return await completer.future.timeout(const Duration(seconds: 10));
    } finally {
      _requests.remove(id);
    }
  }

  void _sendUntracked(String type, Map<String, dynamic> body) {
    if (!online || _channel == null) return;
    _channel!.sink.add(
      jsonEncode({'v': 1, 'id': 'event-${_serial++}', 'type': type, ...body}),
    );
  }

  Future<void> invite(String target) async {
    if (phase != CallPhase.idle) throw StateError('Already in a call');
    error = null;
    // Reserve UI immediately to prevent duplicate clicks.
    phase = CallPhase.outgoing;
    peer = target;
    _notify();
    try {
      await _request('call.invite', {'to': target});
      // call.ringing is authoritative; it supplies the call ID.
    } catch (e) {
      await _clearCall();
      error = '$e';
      _notify();
      rethrow;
    }
  }

  Future<void> accept() async {
    if (phase != CallPhase.incoming) return;
    phase = CallPhase.connecting;
    _notify();
    try {
      await _request('call.accept', {'call_id': callId});
    } catch (_) {
      await _clearCall();
      _notify();
      rethrow;
    }
  }

  Future<void> reject() async {
    if (callId != null) await _request('call.reject', {'call_id': callId});
  }

  Future<void> hangUp() async {
    final id = callId;
    if (id != null && online) {
      try {
        await _request('call.end', {'call_id': id});
      } finally {
        if (callId == id) {
          lastEndedCallId = id;
          lastEndReason = 'hangup';
          await _clearCall();
          _notify();
        }
      }
    }
  }

  void setMicrophone(bool enabled) {
    microphoneEnabled = enabled;
    for (final track in _local?.getAudioTracks() ?? <MediaStreamTrack>[]) {
      track.enabled = enabled;
    }
    _notify();
  }

  void setCamera(bool enabled) {
    cameraEnabled = enabled;
    for (final track in _local?.getVideoTracks() ?? <MediaStreamTrack>[]) {
      track.enabled = enabled;
    }
    _notify();
  }

  Future<void> _handle(Map<String, dynamic> m) async {
    switch (m['type']) {
      case 'ready':
        _rtc = Map<String, dynamic>.from(m['rtc'] as Map);
        peers = List<String>.from(m['peers'] as List);
        online = true;
        error = null;
        _retry = 0;
        if (!(_ready?.isCompleted ?? true)) _ready!.complete();
        _heartbeat?.cancel();
        _heartbeat = Timer.periodic(const Duration(seconds: 25), (_) async {
          try {
            await _request('ping');
          } catch (_) {
            await _channel?.sink.close();
          }
        });
        break;
      case 'ack':
        final request = _requests[m['id']];
        if (request != null && !request.isCompleted) request.complete(m);
        break;
      case 'error':
        final request = _requests[m['id']];
        if (request != null && !request.isCompleted)
          request.completeError(StateError(m['code'] as String));
        error = m['code'] as String;
        break;
      case 'call.ringing':
      case 'call.incoming':
        callId = m['call_id'] as String;
        peer = m['peer'] as String;
        peerLabel = m['peer_label']?.toString() ?? peer;
        peerLocation = m['peer_location']?.toString() ?? '';
        phase = m['type'] == 'call.incoming'
            ? CallPhase.incoming
            : CallPhase.outgoing;
        break;
      case 'rtc.config':
        if (m['call_id'] == callId)
          _rtc = Map<String, dynamic>.from(m['rtc'] as Map);
        break;
      case 'call.accepted':
        if (m['call_id'] != callId) return;
        phase = CallPhase.connecting;
        await _createPeer();
        if (m['offerer'] == deviceId) {
          final offer = await _pc!.createOffer();
          await _pc!.setLocalDescription(offer);
          _sendUntracked('rtc.offer', {'call_id': callId, 'sdp': offer.sdp});
        }
        break;
      case 'rtc.offer':
      case 'rtc.answer':
        if (m['call_id'] != callId || _pc == null) return;
        await _pc!.setRemoteDescription(
          RTCSessionDescription(
            m['sdp'] as String,
            m['type'] == 'rtc.offer' ? 'offer' : 'answer',
          ),
        );
        _remoteSet = true;
        for (final candidate in _pendingIce) {
          await _pc!.addCandidate(candidate);
        }
        _pendingIce.clear();
        if (m['type'] == 'rtc.offer') {
          final answer = await _pc!.createAnswer();
          await _pc!.setLocalDescription(answer);
          _sendUntracked('rtc.answer', {'call_id': callId, 'sdp': answer.sdp});
        }
        _negotiated = true;
        _reportReady();
        break;
      case 'rtc.ice':
        if (m['call_id'] != callId) return;
        final c = m['candidate'] as Map;
        final candidate = RTCIceCandidate(
          c['candidate'] as String?,
          c['sdpMid'] as String?,
          c['sdpMLineIndex'] as int?,
        );
        if (_remoteSet && _pc != null) {
          await _pc!.addCandidate(candidate);
        } else {
          _pendingIce.add(candidate);
        }
        break;
      case 'call.active':
        if (m['call_id'] == callId) phase = CallPhase.active;
        break;
      case 'call.ended':
        if (m['call_id'] == callId) {
          lastEndedCallId = callId;
          lastEndReason = m['reason']?.toString() ?? 'ended';
          await _clearCall();
          mediaStatus = 'Ended: ${m['reason']}';
        }
        break;
    }
    _notify();
  }

  Future<void> _createPeer() async {
    final id = callId;
    if (!_mediaPrepared) {
      await beforeMediaStart?.call();
      _mediaPrepared = true;
    }
    final pc = await createPeerConnection(_rtc);
    _pc = pc;
    _remoteSet = false;
    _readySent = false;
    _negotiated = false;
    pc.onIceCandidate = (candidate) {
      if (callId == id && candidate.candidate?.isNotEmpty == true) {
        _sendUntracked('rtc.ice', {
          'call_id': id,
          'candidate': candidate.toMap(),
        });
      }
    };
    pc.onTrack = (event) {
      if (callId != id || event.streams.isEmpty) return;
      _remote = event.streams.first;
      remoteRenderer.srcObject = _remote;
      _notify();
    };
    pc.onConnectionState = (state) {
      if (callId != id) return;
      mediaStatus = state.name;
      if (state == RTCPeerConnectionState.RTCPeerConnectionStateConnected) {
        _mediaGrace?.cancel();
        _reportReady();
      } else if (state == RTCPeerConnectionState.RTCPeerConnectionStateFailed) {
        _sendUntracked('call.end', {'call_id': id});
      } else if (state ==
          RTCPeerConnectionState.RTCPeerConnectionStateDisconnected) {
        _mediaGrace?.cancel();
        _mediaGrace = Timer(const Duration(seconds: 15), () {
          if (callId == id) _sendUntracked('call.end', {'call_id': id});
        });
      }
      _notify();
    };
    final constraints = await mediaConstraintsProvider?.call() ??
        {
          'audio': true,
          'video': {
            'facingMode': 'user',
            'width': {'ideal': 640},
            'height': {'ideal': 480},
          },
        };
    final local = await navigator.mediaDevices.getUserMedia(constraints);
    _local = local;
    localRenderer.srcObject = local;
    microphoneEnabled = true;
    cameraEnabled = true;
    for (final track in local.getTracks()) {
      await pc.addTrack(track, local);
    }
  }

  void _reportReady() {
    if (_negotiated &&
        !_readySent &&
        callId != null &&
        _pc?.connectionState ==
            RTCPeerConnectionState.RTCPeerConnectionStateConnected) {
      _readySent = true;
      _sendUntracked('media.ready', {'call_id': callId});
    }
  }

  Future<void> _clearCall() async {
    callId = null;
    peer = null;
    peerLabel = null;
    peerLocation = null;
    phase = CallPhase.idle;
    _mediaGrace?.cancel();
    _pendingIce.clear();
    _remoteSet = false;
    final pc = _pc;
    _pc = null;
    final local = _local;
    _local = null;
    final remote = _remote;
    _remote = null;
    if (_initialized) {
      localRenderer.srcObject = null;
      remoteRenderer.srcObject = null;
    }
    if (pc != null) {
      await pc.close();
      await pc.dispose();
    }
    if (local != null) {
      for (final track in local.getTracks()) {
        await track.stop();
      }
      await local.dispose();
    }
    if (remote != null) await remote.dispose();
    if (_mediaPrepared) {
      _mediaPrepared = false;
      try {
        await afterMediaStop?.call();
      } catch (e) {
        error = 'Media cleanup error: $e';
      }
    }
  }

  Future<void> disconnect() async {
    _stopping = true;
    _generation++;
    if (!(_ready?.isCompleted ?? true))
      _ready!.completeError(StateError('Disconnected'));
    _heartbeat?.cancel();
    _reconnect?.cancel();
    await _subscription?.cancel();
    _subscription = null;
    final channel = _channel;
    _channel = null;
    await channel?.sink.close();
    for (final request in _requests.values) {
      if (!request.isCompleted)
        request.completeError(StateError('Disconnected'));
    }
    _requests.clear();
    online = false;
    _token = null;
    _credentialsProvider = null;
    await _events;
    await _clearCall();
    _notify();
  }

  Future<void> shutdown() async {
    await disconnect();
    if (_initialized) {
      await localRenderer.dispose();
      await remoteRenderer.dispose();
    }
    _initialized = false;
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}
