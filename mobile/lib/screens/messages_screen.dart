import 'package:flutter/material.dart';

import '../services/api_service.dart';

class MessagesScreen extends StatefulWidget {
  const MessagesScreen({
    super.key,
    required this.api,
  });

  final ApiService api;

  @override
  State<MessagesScreen> createState() => _MessagesScreenState();
}

class _MessagesScreenState extends State<MessagesScreen> {
  List<dynamic> _messages = [];
  int _unreadCount = 0;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadMessages();
  }

  Future<void> _loadMessages() async {
    setState(() => _loading = true);
    try {
      final data = await widget.api.getMessages();
      setState(() {
        _messages = data['messages'] as List<dynamic>? ?? [];
        _unreadCount = data['unread_count'] as int? ?? 0;
      });
    } catch (_) {
      _messages = [];
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _markAsRead(int messageId) async {
    try {
      await widget.api.markMessageRead(messageId);
      _loadMessages();
    } catch (_) {}
  }

  Color _getTypeColor(String type) {
    switch (type) {
      case 'task_created':
        return const Color(0xFF1D74F5);
      case 'task_reminder':
        return const Color(0xFFB8860B);
      case 'task_escalation':
        return const Color(0xFFF5455C);
      case 'task_response':
        return const Color(0xFF2DE0A5);
      default:
        return const Color(0xFF8F959E);
    }
  }

  IconData _getTypeIcon(String type) {
    switch (type) {
      case 'task_created':
        return Icons.add_task;
      case 'task_reminder':
        return Icons.alarm;
      case 'task_escalation':
        return Icons.arrow_upward;
      case 'task_response':
        return Icons.check_circle_outline;
      default:
        return Icons.message;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF0F2F5),
      appBar: AppBar(
        title: const Text('消息'),
        backgroundColor: Colors.white,
        foregroundColor: const Color(0xFF1F2329),
        elevation: 0,
        actions: [
          if (_unreadCount > 0)
            TextButton(
              onPressed: () async {
                await widget.api.markAllMessagesRead();
                _loadMessages();
              },
              child: const Text('全部已读'),
            ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadMessages,
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _messages.isEmpty
              ? _buildEmptyState()
              : RefreshIndicator(
                  onRefresh: _loadMessages,
                  child: ListView.builder(
                    padding: const EdgeInsets.all(16),
                    itemCount: _messages.length,
                    itemBuilder: (context, index) {
                      final msg = _messages[index] as Map<String, dynamic>;
                      return _buildMessageCard(msg);
                    },
                  ),
                ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            Icons.notifications_none,
            size: 80,
            color: Colors.grey[300],
          ),
          const SizedBox(height: 16),
          Text(
            '暂无消息',
            style: TextStyle(
              fontSize: 16,
              color: Colors.grey[500],
            ),
          ),
          const SizedBox(height: 8),
          Text(
            '任务通知将在此显示',
            style: TextStyle(
              fontSize: 14,
              color: Colors.grey[400],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMessageCard(Map<String, dynamic> msg) {
    final isRead = msg['is_read'] == true;
    final type = msg['type'] as String? ?? 'unknown';
    final typeColor = _getTypeColor(type);
    final typeIcon = _getTypeIcon(type);

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.04),
            blurRadius: 2,
            offset: const Offset(0, 1),
          ),
        ],
        border: isRead
            ? null
            : Border.all(
                color: typeColor.withOpacity(0.3),
                width: 1,
              ),
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () {
            if (!isRead) {
              _markAsRead(msg['id'] as int);
            }
            _showMessageDetail(msg);
          },
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  width: 40,
                  height: 40,
                  decoration: BoxDecoration(
                    color: typeColor.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Icon(
                    typeIcon,
                    color: typeColor,
                    size: 20,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              msg['title'] as String? ?? '未知消息',
                              style: TextStyle(
                                fontSize: 15,
                                fontWeight:
                                    isRead ? FontWeight.w500 : FontWeight.w700,
                                color: const Color(0xFF1F2329),
                              ),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                          if (!isRead)
                            Container(
                              width: 8,
                              height: 8,
                              decoration: BoxDecoration(
                                color: typeColor,
                                borderRadius: BorderRadius.circular(4),
                              ),
                            ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(
                        msg['content'] as String? ?? '',
                        style: const TextStyle(
                          fontSize: 13,
                          color: Color(0xFF8F959E),
                          height: 1.4,
                        ),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 8,
                              vertical: 2,
                            ),
                            decoration: BoxDecoration(
                              color: typeColor.withOpacity(0.1),
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: Text(
                              _getTypeLabel(type),
                              style: TextStyle(
                                fontSize: 10,
                                fontWeight: FontWeight.w600,
                                color: typeColor,
                              ),
                            ),
                          ),
                          const Spacer(),
                          Text(
                            _formatTime(msg['created_at'] as String?),
                            style: const TextStyle(
                              fontSize: 11,
                              color: Color(0xFF8F959E),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  String _getTypeLabel(String type) {
    switch (type) {
      case 'task_created':
        return '新任务';
      case 'task_reminder':
        return '提醒';
      case 'task_escalation':
        return '升级';
      case 'task_response':
        return '回复';
      default:
        return '消息';
    }
  }

  String _formatTime(String? timeStr) {
    if (timeStr == null) return '';
    try {
      final dt = DateTime.parse(timeStr);
      final now = DateTime.now();
      final diff = now.difference(dt);

      if (diff.inMinutes < 1) return '刚刚';
      if (diff.inMinutes < 60) return '${diff.inMinutes}分钟前';
      if (diff.inHours < 24) return '${diff.inHours}小时前';
      if (diff.inDays < 7) return '${diff.inDays}天前';

      return '${dt.month}-${dt.day}';
    } catch (_) {
      return '';
    }
  }

  void _showMessageDetail(Map<String, dynamic> msg) {
    final type = msg['type'] as String? ?? 'unknown';
    final taskId = msg['task_id'] as int?;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => _MessageDetailSheet(
        message: msg,
        onAction: (action, reason) async {
          if (taskId != null) {
            try {
              await widget.api.replyToTask(
                taskId: taskId,
                action: action,
                reason: reason,
              );
              if (mounted) {
                Navigator.pop(context);
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text('操作成功')),
                );
                _loadMessages();
              }
            } catch (e) {
              if (mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text('操作失败: $e')),
                );
              }
            }
          }
        },
      ),
    );
  }
}

class _MessageDetailSheet extends StatefulWidget {
  final Map<String, dynamic> message;
  final Future<void> Function(String action, String? reason) onAction;

  const _MessageDetailSheet({
    required this.message,
    required this.onAction,
  });

  @override
  State<_MessageDetailSheet> createState() => _MessageDetailSheetState();
}

class _MessageDetailSheetState extends State<_MessageDetailSheet> {
  final _reasonController = TextEditingController();
  String? _selectedAction;
  bool _loading = false;

  @override
  void dispose() {
    _reasonController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final type = widget.message['type'] as String? ?? 'unknown';
    final isTaskMessage = type == 'task_created' || type == 'task_reminder';

    return Container(
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 24,
        bottom: MediaQuery.of(context).viewInsets.bottom + 32,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Center(
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: Colors.grey[300],
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const SizedBox(height: 20),
            Text(
              widget.message['title'] as String? ?? '消息详情',
              style: const TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: Color(0xFF1F2329),
              ),
            ),
            const SizedBox(height: 16),
            Text(
              widget.message['content'] as String? ?? '无内容',
              style: const TextStyle(
                fontSize: 14,
                color: Color(0xFF8F959E),
                height: 1.6,
              ),
            ),
            if (isTaskMessage) ...[
              const SizedBox(height: 24),
              const Text(
                '操作',
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: Color(0xFF1F2329),
                ),
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  _buildActionButton('接受', 'accept', const Color(0xFF2DE0A5)),
                  _buildActionButton('拒绝', 'reject', const Color(0xFFF5455C)),
                  _buildActionButton('完成', 'complete', const Color(0xFF1D74F5)),
                  _buildActionButton('未完成', 'incomplete', const Color(0xFFB8860B)),
                ],
              ),
              if (_selectedAction == 'reject' ||
                  _selectedAction == 'incomplete') ...[
                const SizedBox(height: 16),
                TextField(
                  controller: _reasonController,
                  maxLines: 3,
                  decoration: InputDecoration(
                    hintText: '请输入理由',
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: const BorderSide(color: Color(0xFFE5E6EB)),
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: const BorderSide(color: Color(0xFFE5E6EB)),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: const BorderSide(color: Color(0xFF1D74F5)),
                    ),
                  ),
                ),
              ],
              if (_selectedAction != null) ...[
                const SizedBox(height: 20),
                Row(
                  children: [
                    Expanded(
                      child: TextButton(
                        onPressed: () => Navigator.pop(context),
                        child: const Text('取消'),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: FilledButton(
                        onPressed: _loading ? null : _submitAction,
                        style: FilledButton.styleFrom(
                          backgroundColor: _getActionColor(_selectedAction!),
                          padding: const EdgeInsets.symmetric(vertical: 14),
                        ),
                        child: _loading
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: Colors.white,
                                ),
                              )
                            : const Text('确认'),
                      ),
                    ),
                  ],
                ),
              ],
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildActionButton(String label, String action, Color color) {
    final isSelected = _selectedAction == action;
    return InkWell(
      onTap: () => setState(() => _selectedAction = action),
      borderRadius: BorderRadius.circular(10),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        decoration: BoxDecoration(
          color: isSelected ? color : color.withOpacity(0.1),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(
            color: isSelected ? color : color.withOpacity(0.3),
            width: 1.5,
          ),
        ),
        child: Text(
          label,
          style: TextStyle(
            color: isSelected ? Colors.white : color,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }

  Color _getActionColor(String action) {
    switch (action) {
      case 'accept':
        return const Color(0xFF2DE0A5);
      case 'reject':
        return const Color(0xFFF5455C);
      case 'complete':
        return const Color(0xFF1D74F5);
      case 'incomplete':
        return const Color(0xFFB8860B);
      default:
        return const Color(0xFF8F959E);
    }
  }

  Future<void> _submitAction() async {
    final reason = (_selectedAction == 'reject' || _selectedAction == 'incomplete')
        ? _reasonController.text.trim()
        : null;

    if ((_selectedAction == 'reject' || _selectedAction == 'incomplete') &&
        (reason == null || reason.isEmpty)) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请输入理由')),
      );
      return;
    }

    setState(() => _loading = true);
    try {
      await widget.onAction(_selectedAction!, reason);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }
}
