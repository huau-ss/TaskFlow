import 'dart:async';
import 'dart:io';

import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

class RecordingService {
  RecordingService() : _recorder = AudioRecorder();

  final AudioRecorder _recorder;
  String? _currentPath;
  DateTime? _startedAt;

  bool get isRecording => _currentPath != null;

  Future<bool> hasPermission() => _recorder.hasPermission();

  Future<String> startRecording() async {
    if (!await hasPermission()) {
      throw Exception('Microphone permission denied');
    }
    final dir = await getApplicationDocumentsDirectory();
    final recordingsDir = Directory(p.join(dir.path, 'recordings'));
    if (!await recordingsDir.exists()) {
      await recordingsDir.create(recursive: true);
    }
    final filename = 'rec_${DateTime.now().millisecondsSinceEpoch}.wav';
    _currentPath = p.join(recordingsDir.path, filename);
    _startedAt = DateTime.now();
    await _recorder.start(
      const RecordConfig(encoder: AudioEncoder.wav, sampleRate: 16000, numChannels: 1),
      path: _currentPath!,
    );
    return _currentPath!;
  }

  Future<RecordingResult?> stopRecording() async {
    final path = await _recorder.stop();
    final result = RecordingResult(
      path: path ?? _currentPath!,
      startedAt: _startedAt ?? DateTime.now(),
      endedAt: DateTime.now(),
    );
    _currentPath = null;
    _startedAt = null;
    return result;
  }

  Future<void> cancelRecording() async {
    await _recorder.stop();
    if (_currentPath != null) {
      final f = File(_currentPath!);
      if (await f.exists()) await f.delete();
    }
    _currentPath = null;
    _startedAt = null;
  }

  void dispose() => _recorder.dispose();
}

class RecordingResult {
  RecordingResult({required this.path, required this.startedAt, required this.endedAt});

  final String path;
  final DateTime startedAt;
  final DateTime endedAt;

  Duration get duration => endedAt.difference(startedAt);

  int get fileSize {
    final file = File(path);
    return file.existsSync() ? file.lengthSync() : 0;
  }
}
