import 'package:flutter/material.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';
import 'client.dart';

class SonnetteCallLabels {
  const SonnetteCallLabels({
    required this.connected,
    required this.offline,
    required this.call,
    required this.incomingCall,
    required this.accept,
    required this.decline,
    required this.localCamera,
    required this.waitingForVideo,
    required this.microphone,
    required this.camera,
    required this.endCall,
  });

  const SonnetteCallLabels.english()
      : connected = 'Connected',
        offline = 'Offline — connect the device to receive calls',
        call = 'Call',
        incomingCall = 'Incoming call from',
        accept = 'Accept',
        decline = 'Decline',
        localCamera = 'Your camera',
        waitingForVideo = 'Waiting for video',
        microphone = 'Microphone',
        camera = 'Camera',
        endCall = 'End call';

  const SonnetteCallLabels.french()
      : connected = 'Connecté',
        offline = 'Hors ligne — connexion nécessaire pour recevoir les appels',
        call = 'Appeler',
        incomingCall = 'Appel entrant de',
        accept = 'Accepter',
        decline = 'Refuser',
        localCamera = 'Votre caméra',
        waitingForVideo = 'En attente de la vidéo',
        microphone = 'Microphone',
        camera = 'Caméra',
        endCall = 'Terminer';

  final String connected;
  final String offline;
  final String call;
  final String incomingCall;
  final String accept;
  final String decline;
  final String localCamera;
  final String waitingForVideo;
  final String microphone;
  final String camera;
  final String endCall;
}

/// Embeddable call UI. The host owns, authenticates and disposes [client].
/// Place in a bounded area (e.g. SizedBox(height: 620) or Expanded).
/// Uses the host Material theme; does not create its own MaterialApp or routes.
class SonnetteCallWidget extends StatefulWidget {
  const SonnetteCallWidget({
    super.key,
    required this.client,
    this.targetDeviceId,
    this.title = 'Video call',
    this.onError,
    this.labels = const SonnetteCallLabels.english(),
    this.remoteVideoAspectRatio = 16 / 9,
    this.videoAreaHeight,
  }) : assert(remoteVideoAspectRatio > 0);
  final SonnetteClient client;

  /// If supplied, only show this destination; server ACLs remain authoritative.
  final String? targetDeviceId;
  final String title;
  final ValueChanged<Object>? onError;
  final SonnetteCallLabels labels;

  /// Display ratio reserved for the remote feed. The video itself is always
  /// rendered with `contain`, so a source with another ratio is letterboxed
  /// rather than cropped.
  final double remoteVideoAspectRatio;

  /// Optional fixed stage height. Combined with a centered aspect-ratio box,
  /// this keeps the complete feed visible in a bounded host widget.
  final double? videoAreaHeight;

  @override
  State<SonnetteCallWidget> createState() => _SonnetteCallWidgetState();
}

class _SonnetteCallWidgetState extends State<SonnetteCallWidget> {
  bool _working = false;
  String? _error;
  SonnetteClient get client => widget.client;

  Future<void> _run(Future<void> Function() action) async {
    setState(() {
      _working = true;
      _error = null;
    });
    try {
      await action();
    } catch (e) {
      widget.onError?.call(e);
      if (mounted)
        setState(() {
          _error = e.toString();
        });
    } finally {
      if (mounted)
        setState(() {
          _working = false;
        });
    }
  }

  Widget _video(RTCVideoRenderer renderer, {bool local = false}) => ClipRRect(
        borderRadius: BorderRadius.circular(16),
        child: Container(
          color: Theme.of(context).colorScheme.surfaceContainerHighest,
          child: renderer.srcObject == null
              ? Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        local ? Icons.videocam_outlined : Icons.person_outline,
                        size: 40,
                      ),
                      const SizedBox(height: 8),
                      Text(
                        local
                            ? widget.labels.localCamera
                            : widget.labels.waitingForVideo,
                      ),
                    ],
                  ),
                )
              : RTCVideoView(
                  renderer,
                  mirror: local,
                  objectFit: RTCVideoViewObjectFit.RTCVideoViewObjectFitContain,
                ),
        ),
      );

  Widget _remoteVideoStage() {
    final stage = AspectRatio(
      aspectRatio: widget.remoteVideoAspectRatio,
      child: Stack(
        children: [
          Positioned.fill(child: _video(client.remoteRenderer)),
          Positioned(
            right: 8,
            bottom: 8,
            width: 120,
            height: 90,
            child: _video(client.localRenderer, local: true),
          ),
        ],
      ),
    );
    final height = widget.videoAreaHeight;
    return height == null
        ? stage
        : SizedBox(height: height, child: Center(child: stage));
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: client,
        builder: (context, _) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    widget.title,
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                ),
                if (client.phase != CallPhase.idle)
                  FilledButton.tonalIcon(
                    onPressed: _working || client.callId == null
                        ? null
                        : () => _run(client.hangUp),
                    icon: const Icon(Icons.call_end),
                    label: Text(widget.labels.endCall),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              client.online
                  ? '${widget.labels.connected} · ${client.phase.name}'
                  : widget.labels.offline,
            ),
            const SizedBox(height: 16),
            if (client.online && client.phase == CallPhase.idle)
              Wrap(
                spacing: 12,
                runSpacing: 12,
                children: (widget.targetDeviceId == null
                        ? client.peers
                        : [widget.targetDeviceId!])
                    .map(
                      (p) => FilledButton.icon(
                        onPressed: _working
                            ? null
                            : () => _run(() => client.invite(p)),
                        icon: const Icon(Icons.call),
                        label: Text('${widget.labels.call} $p'),
                      ),
                    )
                    .toList(),
              ),
            if (client.phase == CallPhase.incoming)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${widget.labels.incomingCall} '
                        '${client.peerLabel ?? client.peer}',
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                      if ((client.peerLocation ?? '').isNotEmpty)
                        Text(client.peerLocation!),
                      const SizedBox(height: 16),
                      Wrap(
                        spacing: 12,
                        children: [
                          FilledButton(
                            onPressed:
                                _working ? null : () => _run(client.accept),
                            child: Text(widget.labels.accept),
                          ),
                          OutlinedButton(
                            onPressed:
                                _working ? null : () => _run(client.reject),
                            child: Text(widget.labels.decline),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            if (client.phase != CallPhase.idle) ...[
              const SizedBox(height: 16),
              _remoteVideoStage(),
              const SizedBox(height: 12),
              Text(client.mediaStatus),
              const SizedBox(height: 12),
              Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  OutlinedButton.icon(
                    onPressed: () =>
                        client.setMicrophone(!client.microphoneEnabled),
                    icon: Icon(
                      client.microphoneEnabled ? Icons.mic : Icons.mic_off,
                    ),
                    label: Text(widget.labels.microphone),
                  ),
                  OutlinedButton.icon(
                    onPressed: () => client.setCamera(!client.cameraEnabled),
                    icon: Icon(
                      client.cameraEnabled
                          ? Icons.videocam
                          : Icons.videocam_off,
                    ),
                    label: Text(widget.labels.camera),
                  ),
                  FilledButton.tonalIcon(
                    onPressed: _working || client.callId == null
                        ? null
                        : () => _run(client.hangUp),
                    icon: const Icon(Icons.call_end),
                    label: Text(widget.labels.endCall),
                  ),
                ],
              ),
            ],
            if (_error != null || client.error != null)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Text(
                  _error ?? client.error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
          ],
        ),
      );
}
