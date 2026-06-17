import 'package:flutter/material.dart';

import '../services/api_service.dart';
import '../services/upload_queue.dart';
import 'meeting_detail_screen.dart';
import 'record_screen.dart';
import 'upload_queue_screen.dart';
import 'voice_print_management_screen.dart';
import 'me_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({
    super.key,
    required this.api,
    required this.uploadQueue,
    required this.onLogout,
  });

  final ApiService api;
  final UploadQueue uploadQueue;
  final Future<void> Function() onLogout;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _tabIndex = 0;
  List<dynamic> _meetings = [];
  bool _loading = true;
  bool _hasPendingUploads = false;

  @override
  void initState() {
    super.initState();
    _loadMeetings();
    _loadPendingUploads();
  }

  Future<void> _loadMeetings() async {
    setState(() => _loading = true);
    try {
      _meetings = await widget.api.listMeetings();
    } catch (_) {
      _meetings = [];
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _loadPendingUploads() async {
    final pending = await widget.uploadQueue.getPending();
    if (mounted) setState(() => _hasPendingUploads = pending.isNotEmpty);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('TaskFlow'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadMeetings,
          ),
          IconButton(
            icon: const Icon(Icons.logout),
            onPressed: () async {
              await widget.onLogout();
            },
          ),
        ],
      ),
      body: IndexedStack(
        index: _tabIndex,
        children: [
          _buildMeetingsList(),
          UploadQueueScreen(uploadQueue: widget.uploadQueue),
          VoicePrintManagementScreen(api: widget.api),
          MeScreen(api: widget.api),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tabIndex,
        onDestinationSelected: (i) {
          setState(() => _tabIndex = i);
          _loadPendingUploads();
        },
        destinations: [
          const NavigationDestination(icon: Icon(Icons.meeting_room), label: '会议'),
          NavigationDestination(
            icon: Badge(
              isLabelVisible: _hasPendingUploads,
              child: const Icon(Icons.cloud_upload),
            ),
            label: '上传',
          ),
          const NavigationDestination(icon: Icon(Icons.fingerprint), label: '声纹'),
          const NavigationDestination(icon: Icon(Icons.person), label: '我的'),
        ],
      ),
      floatingActionButton: _tabIndex == 0
          ? FloatingActionButton.extended(
              onPressed: () async {
                await Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => RecordScreen(api: widget.api, uploadQueue: widget.uploadQueue),
                  ),
                );
                _loadMeetings();
              },
              icon: const Icon(Icons.mic),
              label: const Text('录音'),
            )
          : null,
    );
  }

  Widget _buildMeetingsList() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_meetings.isEmpty) {
      return const Center(child: Text('暂无会议，点击右下角开始录音'));
    }
    return RefreshIndicator(
      onRefresh: _loadMeetings,
      child: ListView.builder(
        itemCount: _meetings.length,
        itemBuilder: (context, index) {
          final m = _meetings[index] as Map<String, dynamic>;
          return ListTile(
            leading: Icon(_statusIcon(m['status'] as String?)),
            title: Text(m['title']?.toString() ?? '未命名会议'),
            subtitle: Text('状态: ${m['status']}'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () async {
              await Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => MeetingDetailScreen(api: widget.api, meeting: m),
                ),
              );
              _loadMeetings();
            },
          );
        },
      ),
    );
  }

  IconData _statusIcon(String? status) {
    switch (status) {
      case 'transcribed':
        return Icons.check_circle;
      case 'transcribing':
        return Icons.hourglass_top;
      case 'failed':
        return Icons.error;
      default:
        return Icons.audio_file;
    }
  }
}
