import 'package:flutter/material.dart';

import '../services/api_service.dart';
import '../services/upload_queue.dart';
import 'meeting_detail_screen.dart';
import 'meeting_graph_screen.dart';
import 'record_screen.dart';
import 'upload_queue_screen.dart';
import 'voice_print_management_screen.dart';
import 'me_screen.dart';
import 'messages_screen.dart';
import 'tasks_screen.dart';

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
  int _unreadMessageCount = 0;

  bool get _showVoicePrintTab => widget.api.isAdmin;

  /// 构建非管理员用户也能正常对齐的标签结构
  List<_TabItem> get _tabs {
    final tabs = <_TabItem>[
      _TabItem(icon: Icons.meeting_room, label: '会议'),
      _TabItem(icon: Icons.cloud_upload, label: '上传', badge: _hasPendingUploads),
      _TabItem(icon: Icons.task_alt, label: '任务'),
      _TabItem(icon: Icons.notifications, label: '消息', badge: _unreadMessageCount > 0, badgeText: _unreadMessageCount > 99 ? '99+' : '$_unreadMessageCount'),
      _TabItem(icon: Icons.person, label: '我的'),
    ];
    // 管理员在「我的」之前插入声纹管理
    if (_showVoicePrintTab) {
      tabs.insert(3, _TabItem(icon: Icons.fingerprint, label: '声纹'));
    }
    return tabs;
  }

  Widget _buildTabChild(int i) {
    final label = _tabs[i].label;
    switch (label) {
      case '会议':
        return _buildMeetingsList();
      case '上传':
        return UploadQueueScreen(uploadQueue: widget.uploadQueue);
      case '任务':
        return TasksScreen(api: widget.api);
      case '消息':
        return MessagesScreen(api: widget.api);
      case '我的':
        return MeScreen(api: widget.api);
      case '声纹':
        return VoicePrintManagementScreen(api: widget.api);
      default:
        return const SizedBox.shrink();
    }
  }

  @override
  void initState() {
    super.initState();
    _loadMeetings();
    _loadPendingUploads();
    _loadUnreadCount();
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

  Future<void> _loadUnreadCount() async {
    try {
      final count = await widget.api.getUnreadCount();
      if (mounted) setState(() => _unreadMessageCount = count);
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('TaskFlow'),
        actions: [
          IconButton(
            icon: const Icon(Icons.hub),
            tooltip: '会议关联图谱',
            onPressed: () async {
              await Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => MeetingGraphScreen(api: widget.api),
                ),
              );
              _loadMeetings();
            },
          ),
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
        children: List.generate(_tabs.length, (i) => _buildTabChild(i)),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tabIndex,
        onDestinationSelected: (i) {
          setState(() => _tabIndex = i);
          _loadPendingUploads();
          if (_tabs[i].label == '消息') _loadUnreadCount();
        },
        destinations: _tabs.map((t) {
          Widget icon = Icon(t.icon);
          if (t.badge) {
            icon = Badge(
              isLabelVisible: true,
              label: t.badgeText != null ? Text(t.badgeText!) : null,
              child: icon,
            );
          }
          return NavigationDestination(icon: icon, label: t.label);
        }).toList(),
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

class _TabItem {
  final IconData icon;
  final String label;
  final bool badge;
  final String? badgeText;

  _TabItem({required this.icon, required this.label, this.badge = false, this.badgeText});
}
