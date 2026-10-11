import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sonnette_kit/sonnette_kit.dart';

void main() {
  test('A fresh controller can disconnect and shut down before initialization', () async {
    final client = SonnetteClient();
    await client.disconnect();
    await client.shutdown();
    expect(client.online, isFalse);
    expect(client.phase, CallPhase.idle);
    client.dispose();
  });
  testWidgets('Embeds without starting camera or owning a MaterialApp', (tester) async {
    final client = SonnetteClient();
    await tester.pumpWidget(MaterialApp(home: Scaffold(
      body: SonnetteCallWidget(client: client, title: 'Front door'),
    )));
    expect(find.text('Front door'), findsOneWidget);
    expect(find.textContaining('Offline'), findsOneWidget);
    expect(find.byType(MaterialApp), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    client.dispose();
  });
  testWidgets('Uses host-provided target and reacts to controller state', (tester) async {
    final client = SonnetteClient()..online = true;
    await tester.pumpWidget(MaterialApp(home: Scaffold(
      body: SonnetteCallWidget(client: client, targetDeviceId: 'reception'),
    )));
    expect(find.text('Call reception'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    client.dispose();
  });
}
