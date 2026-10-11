import 'package:flutter/material.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';
import 'client.dart';

/// Embeddable call UI. The host owns, authenticates and disposes [client].
/// Place in a bounded area (e.g. SizedBox(height: 620) or Expanded).
/// Uses the host Material theme; does not create its own MaterialApp or routes.
class SonnetteCallWidget extends StatefulWidget {
  const SonnetteCallWidget({super.key, required this.client, this.targetDeviceId,
    this.title = 'Video call', this.onError});
  final SonnetteClient client;
  /// If supplied, only show this destination; server ACLs remain authoritative.
  final String? targetDeviceId;
  final String title;
  final ValueChanged<Object>? onError;

  @override
  State<SonnetteCallWidget> createState() => _SonnetteCallWidgetState();
}

class _SonnetteCallWidgetState extends State<SonnetteCallWidget> {
  bool _working = false;
  String? _error;
  SonnetteClient get client => widget.client;

  Future<void> _run(Future<void> Function() action) async {
    setState(() { _working = true; _error = null; });
    try { await action(); }
    catch (e) {
      widget.onError?.call(e);
      if (mounted) setState(() { _error = e.toString(); });
    } finally { if (mounted) setState(() { _working = false; }); }
  }

  Widget _video(RTCVideoRenderer renderer, {bool local = false}) => ClipRRect(
    borderRadius: BorderRadius.circular(16),
    child: Container(
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      child: renderer.srcObject == null
          ? Center(child: Column(mainAxisSize: MainAxisSize.min, children: [
              Icon(local ? Icons.videocam_outlined : Icons.person_outline, size: 40),
              const SizedBox(height: 8), Text(local ? 'Your camera' : 'Waiting for video'),
            ]))
          : RTCVideoView(renderer, mirror: local,
              objectFit: RTCVideoViewObjectFit.RTCVideoViewObjectFitContain),
    ),
  );

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: client,
    builder: (context, _) => ListView(padding: const EdgeInsets.all(16), children: [
      Text(widget.title, style: Theme.of(context).textTheme.headlineSmall),
      const SizedBox(height: 8),
      Text(client.online ? 'Connected · ${client.phase.name}' : 'Offline — connect the device to receive calls'),
      const SizedBox(height: 16),
      if (client.online && client.phase == CallPhase.idle)
        Wrap(spacing: 12, runSpacing: 12,
          children: (widget.targetDeviceId == null ? client.peers : [widget.targetDeviceId!]).map((p) =>
            FilledButton.icon(onPressed: _working ? null : () => _run(() => client.invite(p)),
              icon: const Icon(Icons.call), label: Text('Call $p'))).toList()),
      if (client.phase == CallPhase.incoming) Card(child: Padding(
        padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Incoming call from ${client.peer}', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 16),
          Wrap(spacing: 12, children: [
            FilledButton(onPressed: _working ? null : () => _run(client.accept), child: const Text('Accept')),
            OutlinedButton(onPressed: _working ? null : () => _run(client.reject), child: const Text('Decline')),
          ]),
        ]))),
      if (client.phase != CallPhase.idle) ...[
        const SizedBox(height: 16),
        AspectRatio(aspectRatio: 16 / 9, child: Stack(children: [
          Positioned.fill(child: _video(client.remoteRenderer)),
          Positioned(right: 8, bottom: 8, width: 120, height: 90,
            child: _video(client.localRenderer, local: true)),
        ])),
        const SizedBox(height: 12), Text(client.mediaStatus), const SizedBox(height: 12),
        Wrap(spacing: 12, runSpacing: 12, children: [
          OutlinedButton.icon(onPressed: () => client.setMicrophone(!client.microphoneEnabled),
            icon: Icon(client.microphoneEnabled ? Icons.mic : Icons.mic_off), label: const Text('Microphone')),
          OutlinedButton.icon(onPressed: () => client.setCamera(!client.cameraEnabled),
            icon: Icon(client.cameraEnabled ? Icons.videocam : Icons.videocam_off), label: const Text('Camera')),
          FilledButton.tonalIcon(onPressed: _working || client.callId == null ? null : () => _run(client.hangUp),
            icon: const Icon(Icons.call_end), label: const Text('End call')),
        ]),
      ],
      if (_error != null || client.error != null) Padding(padding: const EdgeInsets.only(top: 16),
        child: Text(_error ?? client.error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
    ]),
  );
}
