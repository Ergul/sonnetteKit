import 'dart:async';
import 'package:flutter/material.dart';
import 'package:sonnette_kit/sonnette_kit.dart';

void main() => runApp(MaterialApp(
  title: 'sonnetteKit demo', debugShowCheckedModeBanner: false,
  theme: ThemeData(colorSchemeSeed: const Color(0xFF386759), useMaterial3: true),
  home: const DemoScreen(),
));

class DemoScreen extends StatefulWidget {
  const DemoScreen({super.key});
  @override
  State<DemoScreen> createState() => _DemoScreenState();
}

class _DemoScreenState extends State<DemoScreen> {
  final client = SonnetteClient();
  final endpoint = TextEditingController(text: 'ws://localhost:8000/ws');
  final identity = TextEditingController(text: 'door');
  final token = TextEditingController();
  bool busy = false;
  String? failure;

  Future<void> connect() async {
    setState(() { busy = true; failure = null; });
    try {
      await client.disconnect();
      await client.connect(server: Uri.parse(endpoint.text.trim()), id: identity.text.trim(), token: token.text.trim());
    } catch (e) { failure = '$e'; }
    finally { if (mounted) setState(() { busy = false; }); }
  }

  @override
  void dispose() {
    unawaited(client.shutdown().whenComplete(client.dispose));
    endpoint.dispose(); identity.dispose(); token.dispose(); super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('sonnetteKit · Widget integration demo')),
    body: SafeArea(child: Center(child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 1000),
      child: Column(children: [
        Padding(padding: const EdgeInsets.all(16), child: Column(children: [
          TextField(controller: endpoint, decoration: const InputDecoration(labelText: 'Signaling URL')),
          Row(children: [
            Expanded(child: TextField(controller: identity, decoration: const InputDecoration(labelText: 'Device ID'))),
            const SizedBox(width: 16),
            Expanded(child: TextField(controller: token, obscureText: true, autocorrect: false, enableSuggestions: false,
              decoration: const InputDecoration(labelText: 'Device key'))),
          ]),
          const SizedBox(height: 12),
          Wrap(spacing: 12, children: [
            FilledButton(onPressed: busy ? null : connect, child: Text(busy ? 'Connecting…' : 'Connect')),
            OutlinedButton(onPressed: busy ? null : () async { await client.disconnect(); }, child: const Text('Disconnect')),
          ]),
          if (failure != null) Text(failure!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
        ])),
        Expanded(child: SonnetteCallWidget(client: client, title: 'A direct conversation.')),
      ]),
    ))),
  );
}
