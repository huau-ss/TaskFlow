import 'package:flutter/material.dart';

import '../services/api_service.dart';

class MeetingDetailScreen extends StatefulWidget {
  const MeetingDetailScreen({super.key, required this.api, required this.meeting});

  final ApiService api;
  final Map<String, dynamic> meeting;

  @override
  State<MeetingDetailScreen> createState() => _MeetingDetailScreenState();
}

class _MeetingDetailScreenState extends State<MeetingDetailScreen> {
  Map<String, dynamic>? _transcript;
  List<dynamic> _tasks = [];
  bool _loading = true;
  bool _extracting = false;

  int get _meetingId => widget.meeting['id'] as int;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      if (widget.meeting['status'] == 'transcribed') {
        _transcript = await widget.api.getTranscript(_meetingId);
        _tasks = await widget.api.listMeetingTasks(_meetingId);
      }
    } catch (_) {}
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _extractTasks() async {
    setState(() => _extracting = true);
    try {
      final result = await widget.api.extractTasks(_meetingId);
      _tasks = result['tasks'] as List<dynamic>? ?? [];
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('已提取 ${result['tasks_created']} 个任务')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('提取失败: $e')));
    } finally {
      if (mounted) setState(() => _extracting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final status = widget.meeting['status'] as String?;
    return Scaffold(
      appBar: AppBar(title: Text(widget.meeting['title']?.toString() ?? '会议详情')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Card(
                  child: ListTile(
                    title: const Text('转写状态'),
                    subtitle: Text(status ?? 'unknown'),
                    trailing: status == 'transcribed'
                        ? FilledButton(
                            onPressed: _extracting ? null : _extractTasks,
                            child: _extracting
                                ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                                : const Text('提取任务'),
                          )
                        : null,
                  ),
                ),
                if (_transcript != null) ...[
                  const SizedBox(height: 16),
                  Text('转写分段', style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  ...(_transcript!['segments'] as List<dynamic>? ?? []).map((seg) {
                    final s = seg as Map<String, dynamic>;
                    return Card(
                      child: Padding(
                        padding: const EdgeInsets.all(12),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              s['speaker_label']?.toString() ?? '',
                              style: TextStyle(
                                color: Theme.of(context).colorScheme.primary,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(s['text']?.toString() ?? ''),
                          ],
                        ),
                      ),
                    );
                  }),
                ],
                if (_tasks.isNotEmpty) ...[
                  const SizedBox(height: 16),
                  Text('任务列表', style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  ..._tasks.map((t) {
                    final task = t as Map<String, dynamic>;
                    return Card(
                      child: ListTile(
                        title: Text(task['title']?.toString() ?? ''),
                        subtitle: Text(
                          '状态: ${task['status']}${task['deadline'] != null ? '\n截止: ${task['deadline']}' : ''}',
                        ),
                      ),
                    );
                  }),
                ],
              ],
            ),
    );
  }
}
