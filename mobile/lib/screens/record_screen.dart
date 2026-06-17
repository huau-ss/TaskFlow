import 'dart:async';

import 'package:flutter/material.dart';

import '../services/api_service.dart';
import '../services/recording_service.dart';
import '../services/upload_queue.dart';

class RecordScreen extends StatefulWidget {
  const RecordScreen({super.key, required this.api, required this.uploadQueue});

  final ApiService api;
  final UploadQueue uploadQueue;

  @override
  State<RecordScreen> createState() => _RecordScreenState();
}

class _RecordScreenState extends State<RecordScreen> {
  final _recording = RecordingService();
  final _titleCtrl = TextEditingController();
  Timer? _timer;
  Duration _elapsed = Duration.zero;
  bool _isRecording = false;

  @override
  void dispose() {
    _timer?.cancel();
    _recording.dispose();
    _titleCtrl.dispose();
    super.dispose();
  }

  void _startTimer() {
    _elapsed = Duration.zero;
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      setState(() => _elapsed += const Duration(seconds: 1));
    });
  }

  Future<void> _toggleRecording() async {
    if (_isRecording) {
      _timer?.cancel();
      final result = await _recording.stopRecording();
      setState(() => _isRecording = false);
      if (result == null) return;
      await widget.uploadQueue.enqueue(
        localPath: result.path,
        title: _titleCtrl.text.trim().isEmpty ? null : _titleCtrl.text.trim(),
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('录音已保存，已加入上传队列')),
      );
      Navigator.of(context).pop();
    } else {
      try {
        await _recording.startRecording();
        setState(() => _isRecording = true);
        _startTimer();
      } catch (e) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('无法开始录音: $e')));
      }
    }
  }

  String _formatDuration(Duration d) {
    final m = d.inMinutes.remainder(60).toString().padLeft(2, '0');
    final s = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '${d.inHours}:$m:$s';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('录音')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            TextField(
              controller: _titleCtrl,
              enabled: !_isRecording,
              decoration: const InputDecoration(
                labelText: '会议标题（可选）',
                border: OutlineInputBorder(),
              ),
            ),
            const Spacer(),
            Text(
              _formatDuration(_elapsed),
              style: Theme.of(context).textTheme.displayMedium,
            ),
            const SizedBox(height: 8),
            Text(_isRecording ? '录音中…' : '点击开始'),
            const Spacer(),
            GestureDetector(
              onTap: _toggleRecording,
              child: Container(
                width: 88,
                height: 88,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: _isRecording ? Colors.red : Theme.of(context).colorScheme.primary,
                ),
                child: Icon(
                  _isRecording ? Icons.stop : Icons.mic,
                  color: Colors.white,
                  size: 40,
                ),
              ),
            ),
            const SizedBox(height: 48),
          ],
        ),
      ),
    );
  }
}
