import 'package:flutter/material.dart';

import '../services/api_service.dart';

class TasksScreen extends StatefulWidget {
  const TasksScreen({
    super.key,
    required this.api,
  });

  final ApiService api;

  @override
  State<TasksScreen> createState() => TasksScreenState();
}

class TasksScreenState extends State<TasksScreen> with SingleTickerProviderStateMixin {
  late TabController _tabController;
  List<dynamic> _tasks = [];
  bool _loading = true;

  final List<_StatusTab> _tabs = [
    _StatusTab('全部', null),
    _StatusTab('进行中', 'in_progress'),
    _StatusTab('已完成', 'completed'),
    _StatusTab('已逾期', 'overdue'),
  ];

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: _tabs.length, vsync: this);
    _tabController.addListener(_onTabChanged);
    _loadTasks();
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  /// 供外部调用，刷新任务列表（如从消息页接受任务后切回）
  void refresh() => _loadTasks();

  void _onTabChanged() {
    if (!_tabController.indexIsChanging) {
      _loadTasks();
    }
  }

  Future<void> _loadTasks() async {
    setState(() => _loading = true);
    try {
      final status = _tabs[_tabController.index].status;
      final data = await widget.api.getTasks(status: status);
      setState(() {
        _tasks = data['tasks'] as List<dynamic>? ?? [];
      });
    } catch (_) {
      _tasks = [];
    }
    if (mounted) setState(() => _loading = false);
  }

  Color _getStatusColor(String? status) {
    switch (status) {
      case 'pending':
        return const Color(0xFFB8860B);
      case 'accepted':
      case 'in_progress':
        return const Color(0xFF1D74F5);
      case 'completed':
        return const Color(0xFF0D8A4E);
      case 'rejected':
      case 'overdue':
        return const Color(0xFFF5455C);
      case 'incomplete':
      case 'escalated':
        return const Color(0xFF7C3AED);
      default:
        return const Color(0xFF8F959E);
    }
  }

  String _getStatusLabel(String? status) {
    switch (status) {
      case 'pending':
        return '待处理';
      case 'accepted':
        return '已接受';
      case 'in_progress':
        return '进行中';
      case 'completed':
        return '已完成';
      case 'rejected':
        return '已拒绝';
      case 'overdue':
        return '已逾期';
      case 'incomplete':
        return '已逾期';
      case 'escalated':
        return '已升级';
      default:
        return '未知';
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF0F2F5),
      appBar: AppBar(
        title: const Text('我的任务'),
        backgroundColor: Colors.white,
        foregroundColor: const Color(0xFF1F2329),
        elevation: 0,
        bottom: TabBar(
          controller: _tabController,
          labelColor: const Color(0xFF1D74F5),
          unselectedLabelColor: const Color(0xFF8F959E),
          indicatorColor: const Color(0xFF1D74F5),
          tabs: _tabs.map((t) => Tab(text: t.label)).toList(),
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadTasks,
          ),
        ],
      ),
      body: TabBarView(
        controller: _tabController,
        children: _tabs.map((t) => _buildTaskList()).toList(),
      ),
    );
  }

  Widget _buildTaskList() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_tasks.isEmpty) {
      return _buildEmptyState();
    }

    return RefreshIndicator(
      onRefresh: _loadTasks,
      child: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: _tasks.length,
        itemBuilder: (context, index) {
          final task = _tasks[index] as Map<String, dynamic>;
          return _buildTaskCard(task);
        },
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            Icons.task_alt,
            size: 80,
            color: Colors.grey[300],
          ),
          const SizedBox(height: 16),
          Text(
            '暂无任务',
            style: TextStyle(
              fontSize: 16,
              color: Colors.grey[500],
            ),
          ),
          const SizedBox(height: 8),
          Text(
            '从会议中提取的任务将显示在这里',
            style: TextStyle(
              fontSize: 14,
              color: Colors.grey[400],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTaskCard(Map<String, dynamic> task) {
    final status = task['status'] as String?;
    final statusColor = _getStatusColor(status);
    final deadline = task['deadline'] as String?;
    final meetingTitle = task['meeting_title'] as String?;

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
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () => _showTaskDetail(task),
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      width: 30,
                      height: 30,
                      decoration: BoxDecoration(
                        color: statusColor.withOpacity(0.1),
                        borderRadius: BorderRadius.circular(15),
                      ),
                      child: Center(
                        child: Text(
                          (task['executor_name'] as String? ?? '?')[0],
                          style: TextStyle(
                            color: statusColor,
                            fontWeight: FontWeight.bold,
                            fontSize: 12,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        task['title'] as String? ?? '未知任务',
                        style: const TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          color: Color(0xFF1F2329),
                        ),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: statusColor.withOpacity(0.1),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        _getStatusLabel(status),
                        style: TextStyle(
                          fontSize: 10,
                          fontWeight: FontWeight.w600,
                          color: statusColor,
                        ),
                      ),
                    ),
                    if (status == 'overdue') ...[
                      const SizedBox(width: 8),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(
                          color: const Color(0xFFF5455C).withOpacity(0.1),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: const Text(
                          '需要处理',
                          style: TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.w600,
                            color: Color(0xFFF5455C),
                          ),
                        ),
                      ),
                    ],
                    const Spacer(),
                    if (deadline != null)
                      Text(
                        '截止: ${_formatDeadline(deadline)}',
                        style: const TextStyle(
                          fontSize: 11,
                          color: Color(0xFF8F959E),
                        ),
                      ),
                  ],
                ),
                if (meetingTitle != null) ...[
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      const Icon(
                        Icons.meeting_room,
                        size: 12,
                        color: Color(0xFF8F959E),
                      ),
                      const SizedBox(width: 4),
                      Expanded(
                        child: Text(
                          meetingTitle,
                          style: const TextStyle(
                            fontSize: 11,
                            color: Color(0xFF8F959E),
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                ],
                if (status == 'pending') ...[
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton(
                          onPressed: () => _replyToTask(task['id'] as int, 'reject'),
                          style: OutlinedButton.styleFrom(
                            foregroundColor: const Color(0xFFF5455C),
                            side: const BorderSide(color: Color(0xFFF5455C)),
                            padding: const EdgeInsets.symmetric(vertical: 8),
                          ),
                          child: const Text('拒绝'),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: FilledButton(
                          onPressed: () => _replyToTask(task['id'] as int, 'accept'),
                          style: FilledButton.styleFrom(
                            backgroundColor: const Color(0xFF2DE0A5),
                            padding: const EdgeInsets.symmetric(vertical: 8),
                          ),
                          child: const Text('接受'),
                        ),
                      ),
                    ],
                  ),
                ] else if (status == 'in_progress' || status == 'overdue') ...[
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton(
                          onPressed: () => _showIncompleteDialog(task),
                          style: OutlinedButton.styleFrom(
                            foregroundColor: const Color(0xFFB8860B),
                            side: const BorderSide(color: Color(0xFFB8860B)),
                            padding: const EdgeInsets.symmetric(vertical: 8),
                          ),
                          child: const Text('未完成'),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: FilledButton(
                          onPressed: () => _replyToTask(task['id'] as int, 'complete'),
                          style: FilledButton.styleFrom(
                            backgroundColor: const Color(0xFF1D74F5),
                            padding: const EdgeInsets.symmetric(vertical: 8),
                          ),
                          child: const Text('完成'),
                        ),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  String _formatDeadline(String deadline) {
    try {
      final dt = DateTime.parse(deadline);
      final now = DateTime.now();
      final diff = dt.difference(now);

      if (diff.isNegative) {
        return '${dt.month}/${dt.day} (已逾期)';
      } else if (diff.inDays == 0) {
        return '今天';
      } else if (diff.inDays == 1) {
        return '明天';
      } else {
        return '${dt.month}/${dt.day}';
      }
    } catch (_) {
      return deadline;
    }
  }

  void _showTaskDetail(Map<String, dynamic> task) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => _TaskDetailSheet(
        task: task,
        onRefresh: _loadTasks,
        onReply: (action, reason) => _replyToTask(task['id'] as int, action, reason: reason),
      ),
    );
  }

  Future<void> _replyToTask(int taskId, String action, {String? reason}) async {
    try {
      await widget.api.replyToTask(
        taskId: taskId,
        action: action,
        reason: reason,
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('操作成功')),
        );
        _loadTasks();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('操作失败: $e')),
        );
      }
    }
  }

  Future<void> _showIncompleteDialog(Map<String, dynamic> task) async {
    final reasonController = TextEditingController();
    final reason = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('填写未完成原因'),
        content: TextField(
          controller: reasonController,
          maxLines: 3,
          decoration: const InputDecoration(
            hintText: '请输入未完成的原因',
            border: OutlineInputBorder(),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () {
              final text = reasonController.text.trim();
              if (text.isEmpty) return;
              Navigator.pop(context, text);
            },
            child: const Text('提交'),
          ),
        ],
      ),
    );
    if (reason != null) {
      await _replyToTask(task['id'] as int, 'incomplete', reason: reason);
    }
  }
}

class _StatusTab {
  final String label;
  final String? status;

  _StatusTab(this.label, this.status);
}

class _TaskDetailSheet extends StatefulWidget {
  final Map<String, dynamic> task;
  final VoidCallback onRefresh;
  final Future<void> Function(String action, String? reason) onReply;

  const _TaskDetailSheet({
    required this.task,
    required this.onRefresh,
    required this.onReply,
  });

  @override
  State<_TaskDetailSheet> createState() => _TaskDetailSheetState();
}

class _TaskDetailSheetState extends State<_TaskDetailSheet> {
  String? _selectedAction;
  bool _loading = false;
  final _reasonController = TextEditingController();

  @override
  void dispose() {
    _reasonController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final status = widget.task['status'] as String? ?? 'unknown';
    final isPending = status == 'pending';
    final isActionable = status == 'in_progress' || status == 'overdue';

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
              widget.task['title'] as String? ?? '任务详情',
              style: const TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: Color(0xFF1F2329),
              ),
            ),
            const SizedBox(height: 16),
            if (widget.task['description'] != null) ...[
              Text(
                widget.task['description'] as String,
                style: const TextStyle(
                  fontSize: 14,
                  color: Color(0xFF8F959E),
                  height: 1.6,
                ),
              ),
              const SizedBox(height: 16),
            ],
            _buildInfoRow(
              Icons.person,
              '执行人',
              widget.task['executor_name'] as String? ?? '未分配',
            ),
            const SizedBox(height: 12),
            _buildInfoRow(
              Icons.meeting_room,
              '来源会议',
              widget.task['meeting_title'] as String? ?? '未知',
            ),
            const SizedBox(height: 12),
            _buildInfoRow(
              Icons.flag,
              '状态',
              _getStatusLabel(status),
            ),
            if (widget.task['deadline'] != null) ...[
              const SizedBox(height: 12),
              _buildInfoRow(
                Icons.schedule,
                '截止时间',
                _formatDeadline(widget.task['deadline'] as String),
              ),
            ],
            if (isPending) ...[
              const SizedBox(height: 24),
              _buildActionButtons([
                _ActionOption('接受', 'accept', const Color(0xFF2DE0A5)),
                _ActionOption('拒绝', 'reject', const Color(0xFFF5455C)),
              ]),
            ] else if (isActionable) ...[
              const SizedBox(height: 24),
              _buildActionButtons([
                _ActionOption('完成', 'complete', const Color(0xFF1D74F5)),
                _ActionOption('未完成', 'incomplete', const Color(0xFFB8860B)),
              ]),
            ],
            if (_selectedAction == 'reject' || _selectedAction == 'incomplete') ...[
              const SizedBox(height: 12),
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
              const SizedBox(height: 16),
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
            ] else ...[
              const SizedBox(height: 20),
              SizedBox(
                width: double.infinity,
                child: TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('关闭'),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildActionButtons(List<_ActionOption> options) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: options.map((opt) {
        final isSelected = _selectedAction == opt.action;
        return InkWell(
          onTap: () => setState(() => _selectedAction = opt.action),
          borderRadius: BorderRadius.circular(10),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            decoration: BoxDecoration(
              color: isSelected ? opt.color : opt.color.withOpacity(0.1),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: isSelected ? opt.color : opt.color.withOpacity(0.3),
                width: 1.5,
              ),
            ),
            child: Text(
              opt.label,
              style: TextStyle(
                color: isSelected ? Colors.white : opt.color,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        );
      }).toList(),
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

  String _getStatusLabel(String? status) {
    switch (status) {
      case 'pending':
        return '待处理';
      case 'in_progress':
        return '进行中';
      case 'completed':
        return '已完成';
      case 'rejected':
        return '已拒绝';
      case 'overdue':
        return '已逾期';
      case 'incomplete':
        return '未完成';
      default:
        return status ?? '未知';
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
      await widget.onReply(_selectedAction!, reason);
      widget.onRefresh();
      if (mounted) Navigator.pop(context);
    } catch (_) {
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Widget _buildInfoRow(IconData icon, String label, String value) {
    return Row(
      children: [
        Icon(icon, size: 16, color: const Color(0xFF8F959E)),
        const SizedBox(width: 8),
        Text(
          '$label: ',
          style: const TextStyle(
            fontSize: 13,
            color: Color(0xFF8F959E),
          ),
        ),
        Expanded(
          child: Text(
            value,
            style: const TextStyle(
              fontSize: 13,
              color: Color(0xFF1F2329),
              fontWeight: FontWeight.w500,
            ),
          ),
        ),
      ],
    );
  }

  String _formatDeadline(String deadline) {
    try {
      final dt = DateTime.parse(deadline);
      return '${dt.year}-${dt.month.toString().padLeft(2, '0')}-${dt.day.toString().padLeft(2, '0')}';
    } catch (_) {
      return deadline;
    }
  }
}

class _ActionOption {
  final String label;
  final String action;
  final Color color;

  _ActionOption(this.label, this.action, this.color);
}
